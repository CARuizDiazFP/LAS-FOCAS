# Nombre de archivo: cromo_barrido_pelos_inner.py
# Ubicación de archivo: scripts/cromo_barrido_pelos_inner.py
# Descripción: Barrido manual /inner por cable (at.61/62/63 de los pelos) y conciliación de servicios por pelo; dry-run exacto por defecto

"""Barrido inicial de los atributos de pelo que sólo trae `GET /db/objects/{cable}/inner`.

Refresca la descripción (`at.61`), el ID de servicio (`at.62`) y el estado (`at.63`) de cada pelo, y
deja `app.cromo_servicio_match` según el orden de fuentes de `core/services/cromo/pelo_servicios.py`:
descripción > `at.62` del conector de ODF > `at.62` del pelo, con el ID vigente resuelto por PROV/alias.
La lógica vive en `ingesta.fase_pelos_inner`; el mismo código corre en el modo `SOLO_PELOS_INNER` del
worker (semanal, **deshabilitado** por defecto, config id=2).

**Dry-run exacto por defecto**: consulta Cromo de verdad y hace TODAS las escrituras dentro de una
transacción externa que al final se revierte (`join_transaction_mode="create_savepoint"`: los
`commit()` de la fase sólo liberan savepoints). El resumen es lo que haría `--apply`, no una
estimación. Sin `--apply` y sin `--cable`, sólo mira los primeros `--limite` cables (default 20).

Correr DENTRO del contenedor del worker de Cromo del entorno (tiene la config de Cromo y la
`DATABASE_URL`). El contenedor no tiene `scripts/`: el script entra por stdin.

    # 1. Un cable puntual, con el detalle pelo por pelo (no escribe nada)
    docker exec -i -w /app -e PYTHONPATH=/app lasfocasdev-cromo-worker \\
        python - --cable F-PE-AL-99 < scripts/cromo_barrido_pelos_inner.py

    # 2. Una muestra (no escribe nada)
    docker exec -i ... python - --limite 200 < scripts/cromo_barrido_pelos_inner.py

    # 3. Barrido completo real (~6 h con concurrencia 2). Corre en primer plano: usar nohup/tmux.
    docker exec -i ... python - --apply --usuario cruizdiaz@metrotel.com.ar < scripts/cromo_barrido_pelos_inner.py

    # 4. Si se cortó, continuar la MISMA corrida salteando los cables ya hechos
    docker exec -i ... python - --apply --reanudar 1234 < scripts/cromo_barrido_pelos_inner.py

El progreso sale por stderr cada `--cada` cables (default 500), con estimación del tiempo restante.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if "__file__" in globals() and not __file__.startswith("<"):  # por stdin no hay archivo: usa PYTHONPATH
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import setup_logging
from core.services.cable_consultas import resolver_cable
from core.services.cromo import ingesta
from core.services.cromo.client import CromoClient
from core.services.cromo.config import get_cromo_config
from db.models.cromo import CromoIngestaCorrida
from db.session import async_engine

logger = setup_logging("cromo_barrido_pelos_inner")

TIPO_CORRIDA = "MANUAL_BARRIDO_PELOS_INNER"
_LIMITE_DRY_RUN = 20


def _progreso(inicio: float, cada: int):
    ultimo = {"n": 0}

    def _al_avanzar(hechos: int, total: int, resumen: ingesta.ResumenPelosInner) -> None:
        if hechos - ultimo["n"] < cada and hechos != total:
            return
        ultimo["n"] = hechos
        transcurrido = time.perf_counter() - inicio
        restante = transcurrido / hechos * (total - hechos) if hechos else 0
        print(
            f"[{datetime.now():%H:%M:%S}] {hechos}/{total} cables ({hechos / total:.1%}) "
            f"pelos={resumen.pelos_leidos} creados={resumen.vinculos_creados} "
            f"retirados={resumen.vinculos_retirados} errores={resumen.cables_error} "
            f"restante≈{restante / 3600:.1f} h",
            file=sys.stderr,
            flush=True,
        )

    return _al_avanzar


async def _cables_objetivo(sesion: AsyncSession, cable: str | None) -> list[int] | None:
    if cable is None:
        return None
    candidatos = await resolver_cable(sesion, cable)
    if not candidatos:
        raise SystemExit(f"No existe un cable vigente {cable!r}")
    if len(candidatos) > 1:
        raise SystemExit(f"{cable!r} es ambiguo, usar el n_id: {[c.n_id for c in candidatos]}")
    return [candidatos[0].n_id]


async def ejecutar(args: argparse.Namespace) -> dict:
    inicio = time.perf_counter()
    async with async_engine.connect() as conn:
        externa = await conn.begin()
        try:
            async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False) as s:
                cables = await _cables_objetivo(s, args.cable)
                if args.reanudar:
                    corrida = await s.get(CromoIngestaCorrida, args.reanudar)
                    if corrida is None or (corrida.params or {}).get("tipo") != TIPO_CORRIDA:
                        raise SystemExit(f"La corrida {args.reanudar} no es un barrido {TIPO_CORRIDA}")
                    corrida.estado = "EN_CURSO"
                    corrida.finalizada_at = None
                else:
                    corrida = await ingesta.iniciar_corrida(
                        s, usuario=args.usuario, psize=0, max_paginas=None, clases=(),
                        params_extra={"tipo": TIPO_CORRIDA, "modo": "SOLO_PELOS_INNER"},
                    )
                contadores = ingesta.ContadoresCorrida()
                if args.reanudar:
                    contadores.leidas, contadores.errores = corrida.leidas or 0, corrida.errores or 0
                    contadores.actualizadas = corrida.actualizadas or 0
                limite = args.limite
                if limite is None and not args.apply and cables is None:
                    limite = _LIMITE_DRY_RUN
                async with CromoClient(get_cromo_config()) as cliente:
                    resumen = await ingesta.fase_pelos_inner(
                        cliente, s, corrida, contadores,
                        cables=cables, limite=limite, reanudar=bool(args.reanudar),
                        concurrencia=args.concurrencia, detallar=cables is not None,
                        al_avanzar=_progreso(inicio, args.cada),
                    )
                corrida.estado = "OK" if resumen.cables_error == 0 else "OK_CON_ERRORES"
                corrida.finalizada_at = datetime.now(timezone.utc)
                ingesta.sincronizar_contadores(corrida, contadores)
                await ingesta.registrar_evento(
                    s, corrida.id, None, None, "RESUMEN",
                    json.dumps({"estado": corrida.estado, "cables_ok": resumen.cables_ok,
                                "cables_error": resumen.cables_error}),
                )
                await s.commit()
                corrida_id = corrida.id
        except BaseException:
            await externa.rollback()
            raise
        if args.apply:
            await externa.commit()
        else:
            await externa.rollback()

    return {
        "modo": "apply" if args.apply else "dry-run",
        "corrida_id": corrida_id if args.apply else None,
        "duracion_s": round(time.perf_counter() - inicio, 1),
        "cables_ok": resumen.cables_ok,
        "cables_error": resumen.cables_error,
        "pelos_leidos": resumen.pelos_leidos,
        "pelos_nuevos": resumen.pelos_nuevos,
        "tubos_nuevos": resumen.tubos_nuevos,
        "pelos_con_manual_sin_tocar": resumen.pelos_con_manual,
        "vinculos_creados": resumen.vinculos_creados,
        "vinculos_retirados": resumen.vinculos_retirados,
        "vinculos_metodo_cambiado": resumen.vinculos_metodo_cambiado,
        "numeros_sin_servicio": len(resumen.numeros_sin_servicio),
        "numeros_sin_servicio_ejemplos": sorted(resumen.numeros_sin_servicio, key=resumen.numeros_sin_servicio.get,
                                                reverse=True)[:20],
        "detalle": resumen.detalle,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="escribe los cambios (sin esto: dry-run exacto)")
    parser.add_argument("--usuario", default="barrido-pelos-inner", help="quién corre el barrido (queda en la corrida)")
    parser.add_argument("--cable", help="nombre o n_id de un cable puntual; muestra el detalle pelo por pelo")
    parser.add_argument(
        "--limite", type=int, help=f"máximo de cables (default: todos con --apply, {_LIMITE_DRY_RUN} en dry-run)"
    )
    parser.add_argument("--reanudar", type=int, help="id de una corrida de este barrido para continuarla")
    parser.add_argument("--concurrencia", type=int, help="cables en vuelo (default CROMO_INNER_CONCURRENCIA)")
    parser.add_argument("--cada", type=int, default=500, help="cada cuántos cables imprimir el progreso")
    args = parser.parse_args()
    if args.reanudar and not args.apply:
        parser.error("--reanudar sólo tiene sentido con --apply")

    resultado = asyncio.run(ejecutar(args))
    logger.info(
        "action=cromo_barrido_pelos_inner modo=%s corrida_id=%s cables_ok=%s cables_error=%s pelos=%s "
        "creados=%s retirados=%s sin_servicio=%s duracion_s=%s",
        resultado["modo"], resultado["corrida_id"], resultado["cables_ok"], resultado["cables_error"],
        resultado["pelos_leidos"], resultado["vinculos_creados"], resultado["vinculos_retirados"],
        resultado["numeros_sin_servicio"], resultado["duracion_s"],
    )
    print(json.dumps(resultado, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
