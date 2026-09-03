# Nombre de archivo: servicios_backfill_prov.py
# Ubicación de archivo: scripts/servicios_backfill_prov.py
# Descripción: Backfill masivo — enriquece Servicios existentes consultando la API PROV, respetando el rate limit de 5 req/s

"""Recorre `app.servicios` y enriquece cada fila con el contexto de PROV (última milla + historial
de upgrades), reusando `ingerir_contexto_prov` — la misma función que usa el endpoint on-demand
`POST /servicios/prov/refrescar`. Respeta el rate limit configurado en `ProvConfig`
(`PROV_RATE_LIMIT_PER_SECOND`, 5 req/s por defecto) durante todo el recorrido.

A diferencia de otros scripts de backfill del repo (síncronos, `SessionLocal`), este es async de
punta a punta porque el cliente PROV lo es — usa `AsyncSessionLocal` (`db/session.py`).

Uso (desde el host, fuera de los contenedores — no hay `/run/secrets/` acá, así que las
credenciales de PROV van por variable de entorno, y la DB de dev se alcanza por el puerto
publicado 5433):

    source .venv/bin/activate
    export POSTGRES_HOST=127.0.0.1
    export POSTGRES_PORT=5433
    export POSTGRES_USER=FOCALBOT
    export POSTGRES_DB=focas_dev
    export POSTGRES_PASSWORD=$(cat .secrets/Dev_db_password_v1.txt)
    export PROV_BASE_URL=https://prov.metrotel.com.ar/api/v1/ADMEQ
    export PROV_USER=$(cat .secrets/Dev_api_prov_user_v1.txt)
    export PROV_PASSWORD=$(cat .secrets/Dev_api_prov_pass_v1.txt)

    python scripts/servicios_backfill_prov.py                                   # sólo reporta (dry-run)
    python scripts/servicios_backfill_prov.py --apply                            # aplica el cambio
    python scripts/servicios_backfill_prov.py --solo-ids 122214,15872 --apply    # subconjunto acotado
    python scripts/servicios_backfill_prov.py --limit 500 --apply                # corrida en lotes de 500

Corriéndolo DENTRO del contenedor `api` (`docker exec lasfocasdev-api python
scripts/servicios_backfill_prov.py ...`) no hace falta ninguno de esos exports: ahí
`PROV_BASE_URL` viene de `.env.dev` y las credenciales de `/run/secrets/api_prov_*_v1`.
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


async def _obtener_candidatos(solo_ids: list[str] | None, limit: int | None) -> list[int]:
    async with AsyncSessionLocal() as session:
        stmt = select(Servicio.id).where(Servicio.numero_primer_servicio.isnot(None))
        if solo_ids:
            stmt = stmt.where(Servicio.numero_primer_servicio.in_(solo_ids))
        stmt = stmt.order_by(Servicio.id)
        if limit is not None:
            stmt = stmt.limit(limit)
        return [fila[0] for fila in (await session.execute(stmt)).all()]


async def main(apply: bool, solo_ids: list[str] | None, limit: int | None) -> None:
    inicio = time.perf_counter()
    ids_candidatos = await _obtener_candidatos(solo_ids, limit)
    logger.info(
        "action=backfill_prov candidatas=%d modo=%s", len(ids_candidatos), "aplicado" if apply else "dry_run"
    )

    exitosos = 0
    no_encontrados = 0
    errores = 0
    errores_ingesta = 0

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

                # Catch-all deliberadamente ancho: una corrida masiva desatendida (miles de filas)
                # no puede abortar entera por una sola fila anómala — un `IntegrityError` de
                # cualquier origen, un dato inesperado en el payload, etc. Se descarta esa fila
                # (rollback) y se sigue; el resumen final reporta cuántas cayeron acá.
                try:
                    await ingerir_contexto_prov(session, servicio, contexto)
                    if apply:
                        await session.commit()
                    else:
                        await session.rollback()
                except Exception:
                    errores_ingesta += 1
                    await session.rollback()
                    logger.exception(
                        "action=backfill_prov evento=error_ingesta numero=%s servicio_pk=%s",
                        numero_consulta,
                        servicio_id,
                    )
                    continue
                exitosos += 1

    elapsed = time.perf_counter() - inicio
    logger.info(
        "action=backfill_prov modo=%s candidatas=%d exitosos=%d no_encontrados=%d errores=%d "
        "errores_ingesta=%d elapsed_seg=%.1f",
        "aplicado" if apply else "dry_run",
        len(ids_candidatos),
        exitosos,
        no_encontrados,
        errores,
        errores_ingesta,
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
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Máxima cantidad de filas a procesar en esta corrida (para correr en lotes manejables)",
    )
    args = parser.parse_args()
    solo_ids_parsed = [valor.strip() for valor in args.solo_ids.split(",")] if args.solo_ids else None
    asyncio.run(main(apply=args.apply, solo_ids=solo_ids_parsed, limit=args.limit))
