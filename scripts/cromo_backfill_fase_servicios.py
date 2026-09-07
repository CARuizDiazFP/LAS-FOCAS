# Nombre de archivo: cromo_backfill_fase_servicios.py
# Ubicación de archivo: scripts/cromo_backfill_fase_servicios.py
# Descripción: Catch-up puntual de FASE 6 · SERVICIOS (matching cromo_pelos.servicio_numero → app.servicios)

"""El scheduler de ingesta Cromo está deshabilitado a propósito desde antes del 2026-08-29, y todas
las corridas manuales posteriores usaron `modo="SOLO_ODF"` o `tipo="MANUAL_REPOBLAR_CABLES"` — dos
caminos que saltan `fase_servicios` por diseño (ver `core/services/cromo/ingesta.py::continuar_corrida`
y `repoblacion_service.py::repoblar_cables`). Resultado real verificado en dev (2026-09-07): 944 pelos
con `servicio_numero` ya ingerido (algunos con match EXACTO y sin ambigüedad, ej. n_id=10216368/
10256800 → servicio_id=122519) nunca generaron fila en `app.cromo_servicio_match`, porque esa fase no
volvió a correr desde 2026-08-07.

Este script NO reimplementa el algoritmo de matching — llama directamente a la misma
`ingesta.fase_servicios()` ya desplegada y probada (corrió correctamente el 2026-08-06/07), la
diferencia con una corrida completa es que NO toca cables/botellas/fusiones/ODFs ni hace ninguna
llamada de red a Cromo (fase_servicios es 100% contra datos ya ingeridos en `app.cromo_pelos`/
`app.servicios`) — evita reactivar el scheduler o disparar tráfico contra la API real de Cromo,
ambos fuera de alcance por decisión explícita del usuario.

Se registra como una corrida sintética más en `cromo_ingesta_corridas` (mismo patrón que
`repoblacion_service.py`, `params_extra={"tipo": "MANUAL_CATCHUP_SERVICIOS"}`), visible en el mismo
histórico admin que una corrida regular.

Por defecto corre en modo REPORTE (dry-run): sólo cuenta cuántos pelos están pendientes de match, sin
invocar `fase_servicios` (que comitea internamente y no tiene modo dry-run propio). Requiere `--apply`
explícito para ejecutar la fase real y persistir cambios.

Uso:
    source .venv/bin/activate

    # Ver cuántos pelos están pendientes, sin tocar nada
    python scripts/cromo_backfill_fase_servicios.py

    # Ejecutar el catch-up real
    python scripts/cromo_backfill_fase_servicios.py --apply --usuario "cruizdiaz@metrotel.com.ar"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.logging import setup_logging
from core.services.cromo import ingesta
from db.session import AsyncSessionLocal

logger = setup_logging("cromo_backfill_fase_servicios")


async def _contar_pendientes() -> int:
    async with AsyncSessionLocal() as sesion:
        filas = (await sesion.execute(ingesta._SQL_PELOS_SIN_MATCH)).all()
    return len(filas)


async def main(args: argparse.Namespace) -> None:
    pendientes_antes = await _contar_pendientes()
    logger.info(
        "action=cromo_catchup_servicios inicio modo=%s pelos_pendientes=%d",
        "aplicado" if args.apply else "reporte",
        pendientes_antes,
    )

    if not args.apply:
        logger.info(
            "action=cromo_catchup_servicios modo=reporte — no se ejecutó fase_servicios, correr con --apply"
        )
        return

    async with AsyncSessionLocal() as sesion:
        corrida = await ingesta.iniciar_corrida(
            sesion,
            usuario=args.usuario,
            psize=0,
            max_paginas=None,
            clases=(),
            params_extra={"tipo": "MANUAL_CATCHUP_SERVICIOS"},
        )
        contadores = ingesta.ContadoresCorrida()
        await ingesta.fase_servicios(sesion, corrida, contadores)

        corrida.estado = "OK" if contadores.errores == 0 else "OK_CON_ERRORES"
        from datetime import datetime, timezone

        corrida.finalizada_at = datetime.now(timezone.utc)
        await sesion.commit()
        corrida_id = corrida.id

    pendientes_despues = await _contar_pendientes()
    logger.info(
        "action=cromo_catchup_servicios fin corrida_id=%d pelos_pendientes_antes=%d pelos_pendientes_despues=%d "
        "resueltos=%d errores=%d",
        corrida_id,
        pendientes_antes,
        pendientes_despues,
        pendientes_antes - pendientes_despues,
        contadores.errores,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Ejecuta fase_servicios real (por defecto sólo reporta)")
    parser.add_argument("--usuario", default="catchup-script", help="Usuario a registrar en la corrida sintética")
    argumentos = parser.parse_args()
    asyncio.run(main(argumentos))
