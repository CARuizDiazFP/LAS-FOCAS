# Nombre de archivo: cromo_backfill_servicio_prefijos.py
# Ubicación de archivo: scripts/cromo_backfill_servicio_prefijos.py
# Descripción: Backfill one-off de servicio_numero/tipo_asociacion en cromo_pelos ya ingeridos, tras ampliar los prefijos reconocidos (Etapa 9c)

"""Reintenta `parsear_servicio()` sobre pelos ya ingeridos que quedaron `INDETERMINADO` con
`servicio_numero IS NULL` — el regex original sólo reconocía el prefijo "FO"; desde Etapa 9c también
reconoce TLS/DWDM/INT/EWS/RPV/TDM/ATD/VID/TRUNK (`core/services/cromo/parser.py::_REGEX_SERVICIO`).
Un fix de parser no reescribe filas ya guardadas (`_upsert_versionado` no toca columnas en el camino
`SIN_CAMBIOS`) — de ahí este backfill, mismo patrón que `scripts/cromo_backfill_geo.py`.

Dos pasos, cada uno idempotente:
1. Re-extrae `servicio_numero` de `servicio_raw` para pelos con `servicio_numero IS NULL` — sólo
   actualiza los que ahora matchean con el regex ampliado.
2. Corre el mismo matching de `ingesta.fase_servicios()` (reusa sus queries, no duplica la lógica)
   contra `app.servicios` para todo `servicio_numero` sin fila en `cromo_servicio_match` — incluye los
   recién actualizados por el paso 1 y cualquier otro pendiente de corridas previas.

No pega contra Cromo — sólo lee/escribe la base ya poblada.

Uso:
    source .venv/bin/activate
    python scripts/cromo_backfill_servicio_prefijos.py [--dry-run]
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
from core.services.cromo.ingesta import _SQL_BUSCAR_SERVICIO, _SQL_PELOS_SIN_MATCH
from core.services.cromo.parser import parsear_servicio
from db.models.cromo import CromoPelo, CromoServicioMatch
from db.session import AsyncSessionLocal

logger = setup_logging("cromo_backfill_servicio_prefijos")


async def _reextraer_numeros(*, dry_run: bool) -> tuple[int, int]:
    """Devuelve (candidatos, actualizados)."""
    actualizados = 0
    async with AsyncSessionLocal() as sesion:
        filas = (
            await sesion.execute(
                select(CromoPelo).where(CromoPelo.servicio_numero.is_(None), CromoPelo.servicio_raw.is_not(None))
            )
        ).scalars().all()
        candidatos = len(filas)

        for pelo in filas:
            numero, tipo = parsear_servicio(pelo.servicio_raw)
            if numero is None:
                continue
            if not dry_run:
                pelo.servicio_numero = numero
                pelo.tipo_asociacion = tipo
            actualizados += 1

        if not dry_run and actualizados:
            await sesion.commit()

    return candidatos, actualizados


async def _matchear_pendientes(*, dry_run: bool) -> tuple[int, int]:
    """Reusa las mismas queries de `ingesta.fase_servicios` (REGEX_EXACTO) sin duplicar la lógica de
    matching. Devuelve (pendientes, resueltos)."""
    resueltos = 0
    async with AsyncSessionLocal() as sesion:
        pendientes = (await sesion.execute(_SQL_PELOS_SIN_MATCH)).all()
        total_pendientes = len(pendientes)

        for pelo_n_id, servicio_numero in pendientes:
            fila = (await sesion.execute(_SQL_BUSCAR_SERVICIO, {"numero": servicio_numero})).first()
            servicio_id = fila[0] if fila else None
            if servicio_id:
                resueltos += 1
            if not dry_run:
                sesion.add(
                    CromoServicioMatch(
                        pelo_n_id=pelo_n_id,
                        servicio_numero=servicio_numero,
                        servicio_id=servicio_id,
                        metodo="REGEX_EXACTO",
                        confianza=100 if servicio_id else 0,
                    )
                )

        if not dry_run and total_pendientes:
            await sesion.commit()

    return total_pendientes, resueltos


async def main(dry_run: bool) -> None:
    candidatos, actualizados = await _reextraer_numeros(dry_run=dry_run)
    accion = "a actualizar (dry-run)" if dry_run else "actualizados"
    logger.info(
        "action=cromo_backfill_servicio_prefijos paso=reextraer candidatos=%s %s=%s",
        candidatos, accion, actualizados,
    )

    pendientes, resueltos = await _matchear_pendientes(dry_run=dry_run)
    accion2 = "a resolver (dry-run)" if dry_run else "resueltos"
    logger.info(
        "action=cromo_backfill_servicio_prefijos paso=matchear pendientes=%s %s=%s",
        pendientes, accion2, resueltos,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Sólo reporta cuántas filas se actualizarían")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
