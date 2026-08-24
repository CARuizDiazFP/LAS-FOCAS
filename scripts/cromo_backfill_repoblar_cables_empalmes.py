# Nombre de archivo: cromo_backfill_repoblar_cables_empalmes.py
# Ubicación de archivo: scripts/cromo_backfill_repoblar_cables_empalmes.py
# Descripción: Backfill retroactivo para repoblar cables en botellas sin cables y empalmes en todas las botellas Cromo

"""Backfill retroactivo de inventario Cromo ya ingerido.

Objetivos:
1. Repoblar cables únicamente en botellas vigentes que hoy no tienen ningún cable local con
   `extremo_a_n_id`/`extremo_b_n_id` apuntando a su `n_id`.
2. Repoblar empalmes (fusiones de `inner[]`) para TODAS las botellas vigentes, anclando siempre
   `botella_n_id` al `n_id` estable local.

No escribe en Cromo, sólo consume la API de lectura y persiste en `app.cromo_*`.

Uso típico:
    source .venv/bin/activate
    python scripts/cromo_backfill_repoblar_cables_empalmes.py

Opciones:
    --dry-run             Sólo calcula/consulta; no persiste cambios.
    --solo-sin-cables     Corre únicamente la fase 1.
    --solo-empalmes       Corre únicamente la fase 2.
    --limite-sin-cables N Limita cuántas botellas procesa en fase 1.
    --limite-empalmes N   Limita cuántas botellas procesa en fase 2.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy import text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.logging import setup_logging
from core.services.cromo import id_dual_resolver, ingesta, parser as cromo_parser
from core.services.cromo.client import CromoClient, CromoClientError
from core.services.cromo.config import get_cromo_config
from core.services.cromo.modelos import Fusion
from core.services.cromo.repoblacion_service import detectar_cables_faltantes, repoblar_cables
from db.models.cromo import CromoFusion
from db.session import AsyncSessionLocal

logger = setup_logging("cromo_backfill_repoblar_cables_empalmes")

_SQL_BOTELLAS_SIN_CABLES = text(
    """
    SELECT b.n_id
    FROM app.cromo_botellas b
    WHERE b.vigente = true
      AND NOT EXISTS (
          SELECT 1
          FROM app.cromo_cables c
          WHERE c.extremo_a_n_id = b.n_id OR c.extremo_b_n_id = b.n_id
      )
    ORDER BY b.n_id
    """
)

_SQL_TODAS_BOTELLAS_VIGENTES = text(
    """
    SELECT n_id
    FROM app.cromo_botellas
    WHERE vigente = true
    ORDER BY n_id
    """
)

_FUSION_CAMPOS = ("botella_n_id", "nombre_par", "tipo", "pelo_a_n_id", "pelo_b_n_id", "latitud", "longitud")


@dataclass(slots=True)
class ResultadoFaseCables:
    candidatas: int = 0
    procesadas: int = 0
    corridas_creadas: int = 0
    cables_creados: int = 0
    cables_actualizados: int = 0
    errores: int = 0


@dataclass(slots=True)
class ResultadoFaseEmpalmes:
    candidatas: int = 0
    procesadas: int = 0
    fusiones_detectadas: int = 0
    fusiones_creadas: int = 0
    fusiones_actualizadas: int = 0
    errores: int = 0


def _fusion_requiere_repoblacion(fila_local: Optional[CromoFusion], fusion: Fusion) -> bool:
    if fila_local is None:
        return True
    return any(
        (
            fila_local.botella_n_id != fusion.botella_n_id,
            fila_local.nombre_par != fusion.nombre_par,
            fila_local.tipo != fusion.tipo,
            fila_local.pelo_a_n_id != fusion.pelo_a_n_id,
            fila_local.pelo_b_n_id != fusion.pelo_b_n_id,
            fila_local.latitud != fusion.latitud,
            fila_local.longitud != fusion.longitud,
        )
    )


async def _ids_desde_sql(sql: str) -> list[int]:
    async with AsyncSessionLocal() as sesion:
        filas = (await sesion.execute(text(sql))).all()
    return [int(fila[0]) for fila in filas]


async def _repoblar_empalmes_de_botella(*, cliente: CromoClient, botella_n_id: int, dry_run: bool) -> tuple[int, int, int]:
    """Devuelve (fusiones_detectadas, creadas, actualizadas)."""
    try:
        obj_inicial = await id_dual_resolver.fetch_objeto(cliente, botella_n_id)
    except CromoClientError as exc:
        if exc.status_code == 404:
            logger.warning(
                "action=cromo_backfill_empalmes evento=botella_no_existe_en_cromo botella_n_id=%s",
                botella_n_id,
            )
            return 0, 0, 0
        raise

    obj_vigente, _ids_cadena = await id_dual_resolver.resolver_cadena_objetos(
        cliente,
        botella_n_id,
        obj_inicial,
        esta_vigente=lambda o: bool((o.get("inner") or []) or (o.get("tp") or [])),
    )

    snapshots = [obj_inicial]
    if obj_vigente is not obj_inicial:
        snapshots.append(obj_vigente)

    fusiones_unicas: dict[int, Fusion] = {}
    for snapshot in snapshots:
        for item in snapshot.get("inner") or []:
            if item.get("class") != ingesta.CLASE_FUSION:
                continue
            try:
                fusion = cromo_parser.parse_fusion(item)
            except Exception as exc:  # noqa: BLE001 - tolerancia por objeto inválido
                logger.warning(
                    "action=cromo_backfill_empalmes evento=fusion_inner_invalida botella_n_id=%s fusion_n_id=%s error=%s",
                    botella_n_id,
                    item.get("n_id") or item.get("id"),
                    exc,
                )
                continue
            fusion.botella_n_id = botella_n_id
            fusiones_unicas[fusion.n_id] = fusion

    if not fusiones_unicas:
        return 0, 0, 0

    creadas = 0
    actualizadas = 0
    async with AsyncSessionLocal() as sesion:
        for fusion in fusiones_unicas.values():
            fila_local = await sesion.get(CromoFusion, fusion.n_id)
            if not _fusion_requiere_repoblacion(fila_local, fusion):
                continue
            if fila_local is None:
                creadas += 1
            else:
                actualizadas += 1
            if not dry_run:
                await ingesta.upsert_simple(sesion, CromoFusion, fusion, _FUSION_CAMPOS)
        if not dry_run and (creadas or actualizadas):
            await sesion.commit()

    return len(fusiones_unicas), creadas, actualizadas


async def _fase_cables_sin_cables(*, cliente: CromoClient, limite: Optional[int], dry_run: bool) -> ResultadoFaseCables:
    ids = await _ids_desde_sql(str(_SQL_BOTELLAS_SIN_CABLES))
    if limite is not None:
        ids = ids[:limite]

    r = ResultadoFaseCables(candidatas=len(ids))
    for idx, botella_n_id in enumerate(ids, start=1):
        try:
            if dry_run:
                # En dry-run no persistimos: sólo medimos pendientes.
                async with AsyncSessionLocal() as sesion:
                    deteccion = await detectar_cables_faltantes(cliente, sesion, botella_n_id)
                if deteccion.cables_pendientes:
                    r.corridas_creadas += 1
                    r.cables_creados += len([c for c in deteccion.cables_pendientes if c.estado_local == "FALTA"])
                    r.cables_actualizados += len(
                        [c for c in deteccion.cables_pendientes if c.estado_local == "DESACTUALIZADO"]
                    )
            else:
                async with AsyncSessionLocal() as sesion:
                    resultado = await repoblar_cables(
                        cliente,
                        sesion,
                        botella_n_id=botella_n_id,
                        usuario="backfill_retroactivo",
                    )
                if resultado.corrida_id is not None:
                    r.corridas_creadas += 1
                    r.cables_creados += resultado.creados
                    r.cables_actualizados += resultado.actualizados
                    r.errores += resultado.errores
        except Exception as exc:  # noqa: BLE001 - continuar lote completo
            r.errores += 1
            logger.error(
                "action=cromo_backfill_cables evento=error_botella botella_n_id=%s error=%s",
                botella_n_id,
                exc,
            )
        finally:
            r.procesadas += 1

        if idx % 100 == 0:
            logger.info(
                "action=cromo_backfill_cables progreso=%s/%s corridas=%s creados=%s actualizados=%s errores=%s",
                idx,
                r.candidatas,
                r.corridas_creadas,
                r.cables_creados,
                r.cables_actualizados,
                r.errores,
            )

    return r


async def _fase_empalmes_todas(*, cliente: CromoClient, limite: Optional[int], dry_run: bool) -> ResultadoFaseEmpalmes:
    ids = await _ids_desde_sql(str(_SQL_TODAS_BOTELLAS_VIGENTES))
    if limite is not None:
        ids = ids[:limite]

    r = ResultadoFaseEmpalmes(candidatas=len(ids))
    for idx, botella_n_id in enumerate(ids, start=1):
        try:
            detectadas, creadas, actualizadas = await _repoblar_empalmes_de_botella(
                cliente=cliente,
                botella_n_id=botella_n_id,
                dry_run=dry_run,
            )
            r.fusiones_detectadas += detectadas
            r.fusiones_creadas += creadas
            r.fusiones_actualizadas += actualizadas
        except Exception as exc:  # noqa: BLE001 - continuar lote completo
            r.errores += 1
            logger.error(
                "action=cromo_backfill_empalmes evento=error_botella botella_n_id=%s error=%s",
                botella_n_id,
                exc,
            )
        finally:
            r.procesadas += 1

        if idx % 100 == 0:
            logger.info(
                "action=cromo_backfill_empalmes progreso=%s/%s detectadas=%s creadas=%s actualizadas=%s errores=%s",
                idx,
                r.candidatas,
                r.fusiones_detectadas,
                r.fusiones_creadas,
                r.fusiones_actualizadas,
                r.errores,
            )

    return r


async def main(args: argparse.Namespace) -> None:
    correr_fase_cables = not args.solo_empalmes
    correr_fase_empalmes = not args.solo_sin_cables

    if not correr_fase_cables and not correr_fase_empalmes:
        raise RuntimeError("No hay fases habilitadas para ejecutar.")

    cfg = get_cromo_config()
    logger.info(
        "action=cromo_backfill_retroactivo inicio dry_run=%s fase_cables=%s fase_empalmes=%s",
        args.dry_run,
        correr_fase_cables,
        correr_fase_empalmes,
    )

    async with CromoClient(cfg) as cliente:
        if correr_fase_cables:
            r_cables = await _fase_cables_sin_cables(
                cliente=cliente,
                limite=args.limite_sin_cables,
                dry_run=args.dry_run,
            )
            logger.info(
                "action=cromo_backfill_retroactivo resumen_fase=cables_sin_cables candidatas=%s procesadas=%s "
                "corridas=%s creados=%s actualizados=%s errores=%s",
                r_cables.candidatas,
                r_cables.procesadas,
                r_cables.corridas_creadas,
                r_cables.cables_creados,
                r_cables.cables_actualizados,
                r_cables.errores,
            )

        if correr_fase_empalmes:
            r_emp = await _fase_empalmes_todas(
                cliente=cliente,
                limite=args.limite_empalmes,
                dry_run=args.dry_run,
            )
            logger.info(
                "action=cromo_backfill_retroactivo resumen_fase=empalmes_todas candidatas=%s procesadas=%s "
                "detectadas=%s creadas=%s actualizadas=%s errores=%s",
                r_emp.candidatas,
                r_emp.procesadas,
                r_emp.fusiones_detectadas,
                r_emp.fusiones_creadas,
                r_emp.fusiones_actualizadas,
                r_emp.errores,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="No persiste cambios")
    parser.add_argument("--solo-sin-cables", action="store_true", help="Ejecuta sólo fase de botellas sin cables")
    parser.add_argument("--solo-empalmes", action="store_true", help="Ejecuta sólo fase de empalmes")
    parser.add_argument("--limite-sin-cables", type=int, default=None, help="Límite de botellas en fase sin cables")
    parser.add_argument("--limite-empalmes", type=int, default=None, help="Límite de botellas en fase empalmes")
    argumentos = parser.parse_args()
    asyncio.run(main(argumentos))
