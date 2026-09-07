# Nombre de archivo: cromo_backfill_geo.py
# Ubicación de archivo: scripts/cromo_backfill_geo.py
# Descripción: Backfill one-off de latitud/longitud en cromo_botellas/cromo_fusiones ya ingeridas, sin re-crawlear Cromo

"""Recalcula `latitud`/`longitud` a partir de `pts_raw` ya almacenado (Gauss-Krüger Faja 5, POSGAR94,
EPSG:22185) para filas ingeridas antes del fix del parser (Etapa 8) — `_resolver_geo()` buscaba una
clave `ll` que nunca aparece en un barrido real; el punto geográfico viaja en `pts`.

Sólo aplica a `cromo_botellas`: es la única tabla que guarda `pts_raw` (`cromo_fusiones` no lo
almacena — nunca lo tuvo — así que sus filas ya existentes con lat/lon en `NULL` se corrigen solas la
próxima vez que una corrida real las vuelva a upsertear, no con este backfill).

No pega contra Cromo — sólo lee/escribe la base ya poblada. Idempotente: sólo toca filas con
`pts_raw` presente y `latitud` todavía `NULL`, así que correrlo dos veces no hace nada la segunda vez.

Uso:
    source .venv/bin/activate
    python scripts/cromo_backfill_geo.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.logging import setup_logging
from core.services.cromo.parser import resolver_lat_lon_gauss_kruger
from db.models.cromo import CromoBotella
from db.session import AsyncSessionLocal

logger = setup_logging("cromo_backfill_geo")


async def _backfill_modelo(modelo_cls: type, *, dry_run: bool) -> tuple[int, int]:
    """Devuelve (candidatas, actualizadas)."""
    actualizadas = 0
    async with AsyncSessionLocal() as sesion:
        filas = (
            await sesion.execute(
                select(modelo_cls).where(modelo_cls.pts_raw.is_not(None), modelo_cls.latitud.is_(None))
            )
        ).scalars().all()
        candidatas = len(filas)

        for fila in filas:
            latitud, longitud = resolver_lat_lon_gauss_kruger(fila.pts_raw)
            if latitud is None:
                continue
            if not dry_run:
                fila.latitud = latitud
                fila.longitud = longitud
            actualizadas += 1

        if not dry_run and actualizadas:
            await sesion.commit()

    return candidatas, actualizadas


async def main(dry_run: bool) -> None:
    candidatas, actualizadas = await _backfill_modelo(CromoBotella, dry_run=dry_run)
    accion = "a actualizar (dry-run)" if dry_run else "actualizadas"
    logger.info(
        "action=cromo_backfill_geo tabla=cromo_botellas candidatas=%s %s=%s",
        candidatas, accion, actualizadas,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Sólo reporta cuántas filas se actualizarían")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
