# Nombre de archivo: cromo_backfill_conectores_odf.py
# Ubicación de archivo: scripts/cromo_backfill_conectores_odf.py
# Descripción: Backfill retroactivo de app.cromo_odf_conectores para las ODFs ya ingeridas antes de que el submódulo de Conectores existiera (2026-08-31)

"""El submódulo de Conectores de ODF (`app.cromo_odf_conectores`, ver `docs/decisiones.md`
2026-08-31 "submódulo nuevo") se sumó a `_procesar_odf_directo` — sólo corre para una ODF cuando
esa ODF pasa de nuevo por `fase_odfs`. Las ~7.955 ODFs ya ingeridas el 2026-08-28 (antes de que el
submódulo existiera) NO tienen conectores hasta que alguien corra una nueva corrida completa de
ODFs o este backfill puntual.

Mismo camino que `_procesar_odf_directo` (`core/services/cromo/ingesta.py`), pero sin re-tocar la
fila propia de `app.cromo_odfs` (se asume ya correcta): por cada ODF ya ingerida, llama
`cliente.get_inner(n_id)` — UNA llamada real a Cromo por objeto, no hay atajo de colección (ver
docstring de `_procesar_odf_directo`: el `inner[]` embebido en el barrido de colección, incluso con
`show=ALL`, es una forma liviana sin el atributo id=62 de servicio directo) — parsea con
`parse_odf_conectores`, resuelve `servicio_resuelto`/`servicio_id_historico` contra
`app.cromo_pelos` ya ingerido, y hace upsert en `app.cromo_odf_conectores`.

Por defecto corre en modo REPORTE (dry-run): sólo cuenta cuántas ODFs se procesarían y cuántos
conectores resultarían, sin escribir nada ni left tocar Cromo más de lo necesario para contar.
Requiere `--apply` explícito para persistir cambios — mismo criterio que
`scripts/servicios_fusionar_identidades_duplicadas.py` (mismo día, mismo ticket).

Uso:
    source .venv/bin/activate

    # Dry-run acotado, para validar contra unas pocas ODFs antes de la corrida completa
    python scripts/cromo_backfill_conectores_odf.py --limite 20

    # Corrida real completa (~7.955 llamadas a Cromo, una por ODF — puede tardar bastante,
    # correr en background o con nohup si la sesión puede cortarse)
    python scripts/cromo_backfill_conectores_odf.py --apply

    # Reanudar después de un corte: sólo las ODFs que todavía no tienen ningún conector guardado
    python scripts/cromo_backfill_conectores_odf.py --apply --solo-faltantes
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text

from core.logging import setup_logging
from core.services.cromo import ingesta
from core.services.cromo import parser as cromo_parser
from core.services.cromo.client import CromoClient, CromoClientError
from core.services.cromo.config import get_cromo_config
from db.models.cromo import CromoOdfConector
from db.session import AsyncSessionLocal

logger = setup_logging("cromo_backfill_conectores_odf")

_SQL_TODAS_LAS_ODFS = text("SELECT n_id FROM app.cromo_odfs WHERE vigente = true ORDER BY n_id")

_SQL_ODFS_SIN_CONECTORES = text(
    """
    SELECT o.n_id
    FROM app.cromo_odfs o
    WHERE o.vigente = true
      AND NOT EXISTS (SELECT 1 FROM app.cromo_odf_conectores c WHERE c.odf_n_id = o.n_id)
    ORDER BY o.n_id
    """
)


@dataclass(slots=True)
class ResultadoBackfill:
    candidatas: int = 0
    procesadas: int = 0
    odfs_con_conectores: int = 0
    conectores_guardados: int = 0
    errores: int = 0


async def _ids_odfs(*, solo_faltantes: bool, limite: Optional[int]) -> list[int]:
    sql = _SQL_ODFS_SIN_CONECTORES if solo_faltantes else _SQL_TODAS_LAS_ODFS
    async with AsyncSessionLocal() as sesion:
        filas = (await sesion.execute(sql)).all()
    ids = [int(fila[0]) for fila in filas]
    return ids[:limite] if limite is not None else ids


async def _backfill_odf(*, cliente: CromoClient, odf_n_id: int, dry_run: bool) -> int:
    """Devuelve la cantidad de conectores encontrados (0 si la ODF no tiene patchera)."""
    try:
        inner_completo = await cliente.get_inner(odf_n_id)
    except CromoClientError as exc:
        if exc.status_code == 404:
            logger.warning("action=cromo_backfill_conectores evento=odf_no_existe_en_cromo odf_n_id=%s", odf_n_id)
            return 0
        raise

    obj = {"n_id": odf_n_id, "inner": inner_completo.get("response") or []}
    conectores = cromo_parser.parse_odf_conectores(obj)
    if not conectores:
        return 0

    async with AsyncSessionLocal() as sesion:
        await ingesta.resolver_servicio_conectores(sesion, conectores)
        if not dry_run:
            for conector in conectores:
                await ingesta.upsert_simple(sesion, CromoOdfConector, conector, ingesta.CONECTOR_ODF_CAMPOS)
            await sesion.commit()

    return len(conectores)


async def main(args: argparse.Namespace) -> None:
    ids = await _ids_odfs(solo_faltantes=args.solo_faltantes, limite=args.limite)
    resultado = ResultadoBackfill(candidatas=len(ids))

    logger.info(
        "action=cromo_backfill_conectores inicio modo=%s solo_faltantes=%s candidatas=%d",
        "aplicado" if args.apply else "reporte",
        args.solo_faltantes,
        resultado.candidatas,
    )

    async with CromoClient(get_cromo_config()) as cliente:
        for idx, odf_n_id in enumerate(ids, start=1):
            try:
                cantidad = await _backfill_odf(cliente=cliente, odf_n_id=odf_n_id, dry_run=not args.apply)
                if cantidad:
                    resultado.odfs_con_conectores += 1
                    resultado.conectores_guardados += cantidad
            except Exception as exc:  # noqa: BLE001 - tolerancia deliberada: una ODF no aborta el lote
                resultado.errores += 1
                logger.error("action=cromo_backfill_conectores evento=error_odf odf_n_id=%s error=%s", odf_n_id, exc)
            finally:
                resultado.procesadas += 1

            if idx % 100 == 0 or idx == resultado.candidatas:
                logger.info(
                    "action=cromo_backfill_conectores progreso=%d/%d odfs_con_conectores=%d "
                    "conectores_guardados=%d errores=%d",
                    idx,
                    resultado.candidatas,
                    resultado.odfs_con_conectores,
                    resultado.conectores_guardados,
                    resultado.errores,
                )

    logger.info(
        "action=cromo_backfill_conectores fin modo=%s candidatas=%d procesadas=%d odfs_con_conectores=%d "
        "conectores_guardados=%d errores=%d",
        "aplicado" if args.apply else "reporte",
        resultado.candidatas,
        resultado.procesadas,
        resultado.odfs_con_conectores,
        resultado.conectores_guardados,
        resultado.errores,
    )
    if not args.apply:
        logger.info("action=cromo_backfill_conectores modo=reporte — no se aplicó ningún cambio, correr con --apply")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Aplica los cambios (por defecto sólo reporta)")
    parser.add_argument(
        "--solo-faltantes",
        action="store_true",
        help="Procesa únicamente las ODFs que todavía no tienen ningún conector guardado (para reanudar)",
    )
    parser.add_argument("--limite", type=int, default=None, help="Limita la cantidad de ODFs a procesar")
    argumentos = parser.parse_args()
    asyncio.run(main(argumentos))
