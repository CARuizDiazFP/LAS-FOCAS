# Nombre de archivo: servicios_backfill_prov.py
# Ubicación de archivo: scripts/servicios_backfill_prov.py
# Descripción: Backfill masivo — enriquece Servicios existentes consultando la API PROV, respetando el rate limit de 5 req/s

"""Recorre `app.servicios` y enriquece cada fila con el contexto de PROV (última milla + historial
de upgrades), reusando `ingerir_contexto_prov` — la misma función que usa el endpoint on-demand
`POST /servicios/prov/refrescar`. Respeta el rate limit configurado en `ProvConfig`
(`PROV_RATE_LIMIT_PER_SECOND`, 5 req/s por defecto) durante todo el recorrido.

A diferencia de otros scripts de backfill del repo (síncronos, `SessionLocal`), este es async de
punta a punta porque el cliente PROV lo es — usa `AsyncSessionLocal` (`db/session.py`).

Uso:
    source .venv/bin/activate
    python scripts/servicios_backfill_prov.py                                   # sólo reporta (dry-run)
    python scripts/servicios_backfill_prov.py --apply                            # aplica el cambio
    python scripts/servicios_backfill_prov.py --solo-ids 122214,15872 --apply    # subconjunto acotado
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.logging import setup_logging
from core.services.prov.client import ProvClient, ProvClientError, ProvServicioNoEncontradoError
from core.services.prov.ingesta import ingerir_contexto_prov
from db.models.infra import Servicio
from db.session import AsyncSessionLocal

logger = setup_logging("servicios_backfill_prov")


async def _obtener_candidatos(solo_ids: list[str] | None) -> list[int]:
    async with AsyncSessionLocal() as session:
        stmt = select(Servicio.id).where(Servicio.numero_primer_servicio.isnot(None))
        if solo_ids:
            stmt = stmt.where(Servicio.numero_primer_servicio.in_(solo_ids))
        stmt = stmt.order_by(Servicio.id)
        return [fila[0] for fila in (await session.execute(stmt)).all()]


async def main(apply: bool, solo_ids: list[str] | None) -> None:
    inicio = time.perf_counter()
    ids_candidatos = await _obtener_candidatos(solo_ids)
    logger.info(
        "action=backfill_prov candidatas=%d modo=%s", len(ids_candidatos), "aplicado" if apply else "dry_run"
    )

    exitosos = 0
    no_encontrados = 0
    errores = 0

    async with ProvClient() as cliente:
        for servicio_id in ids_candidatos:
            async with AsyncSessionLocal() as session:
                stmt = (
                    select(Servicio)
                    .options(selectinload(Servicio.historial_ids), selectinload(Servicio.equipos_ultima_milla))
                    .where(Servicio.id == servicio_id)
                )
                servicio = (await session.execute(stmt)).scalars().first()
                if servicio is None:
                    continue

                numero_consulta = servicio.numero_primer_servicio or servicio.servicio_id
                try:
                    contexto = await cliente.obtener_contexto_servicio(numero_consulta)
                except ProvServicioNoEncontradoError:
                    no_encontrados += 1
                    logger.warning("action=backfill_prov evento=no_encontrado numero=%s", numero_consulta)
                    continue
                except ProvClientError as exc:
                    errores += 1
                    logger.error(
                        "action=backfill_prov evento=error_cliente numero=%s error=%s", numero_consulta, exc
                    )
                    continue

                await ingerir_contexto_prov(session, servicio, contexto)
                if apply:
                    await session.commit()
                else:
                    await session.rollback()
                exitosos += 1

    elapsed = time.perf_counter() - inicio
    logger.info(
        "action=backfill_prov modo=%s candidatas=%d exitosos=%d no_encontrados=%d errores=%d elapsed_seg=%.1f",
        "aplicado" if apply else "dry_run",
        len(ids_candidatos),
        exitosos,
        no_encontrados,
        errores,
        elapsed,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Aplica los cambios (por defecto sólo reporta)")
    parser.add_argument(
        "--solo-ids",
        type=str,
        default=None,
        help="Lista de numero_primer_servicio separados por coma, para correr sobre un subconjunto acotado",
    )
    args = parser.parse_args()
    solo_ids_parsed = [valor.strip() for valor in args.solo_ids.split(",")] if args.solo_ids else None
    asyncio.run(main(apply=args.apply, solo_ids=solo_ids_parsed))
