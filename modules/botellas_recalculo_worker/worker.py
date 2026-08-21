# Nombre de archivo: worker.py
# Ubicación de archivo: modules/botellas_recalculo_worker/worker.py
# Descripción: Worker dedicado — consume la cola Redis de recálculo de Botellas duplicadas, recalcula y publica el aviso

"""Corre en su propio contenedor (mismo patrón que `modules/cromo_worker/`, pero sin scheduler: acá
el trigger es un job en una lista Redis, no un intervalo). Un solo loop asyncio hace `BLPOP` sobre
`admin:recompute:jobs`; el dispatch table de abajo tiene un único `kind` registrado hoy
(`botellas_duplicados`) — agregar uno nuevo (p. ej. para Cámaras duplicadas) es agregar una entrada
al dict, no rediseñar el loop."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

import uvicorn
from fastapi import FastAPI

from core.cache.redis_client import get_redis
from core.logging import setup_logging
from core.services.botella_duplicados_service import detectar_grupos_duplicados_botellas
from core.services.botella_recompute_queue import (
    JOB_KIND_BOTELLAS_DUPLICADOS,
    QUEUE_KEY,
    guardar_cache_duplicados,
)
from db.session import SessionLocal
from modules.botellas_recalculo_worker.config import BLPOP_TIMEOUT_SECONDS, HEALTH_PORT, NOMBRE_SERVICIO

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOGS_ROOT = Path(os.getenv("LOGS_DIR", "/app/Logs"))
logger = setup_logging(
    "botellas_recalculo_worker", LOG_LEVEL, enable_file=True, logs_dir=LOGS_ROOT,
    filename="botellas_recalculo_worker.log",
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

ADMIN_NOTIFICATIONS_CHANNEL = "admin-notifications"

_worker_status: dict = {
    "status": "starting",
    "service": NOMBRE_SERVICIO,
    "ultimo_job": None,
    "ultimo_error": None,
    "jobs_procesados": 0,
}
_loop_task: asyncio.Task | None = None


async def _recalcular_botellas_duplicados() -> None:
    with SessionLocal() as session:
        grupos = detectar_grupos_duplicados_botellas(session)
    await guardar_cache_duplicados(grupos)
    await get_redis().publish(
        ADMIN_NOTIFICATIONS_CHANNEL,
        json.dumps({
            "type": "botellas_duplicados_recalculado",
            "at": datetime.now(timezone.utc).isoformat(),
        }),
    )


DISPATCH: dict[str, Callable[[], Awaitable[None]]] = {
    JOB_KIND_BOTELLAS_DUPLICADOS: _recalcular_botellas_duplicados,
}


async def _procesar_job(raw: str) -> None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("action=botellas_recalculo_worker evento=job_invalido raw=%s", raw)
        return

    if not isinstance(payload, dict):
        logger.warning("action=botellas_recalculo_worker evento=job_invalido reason=no_es_dict raw=%s", raw)
        return

    kind = payload.get("kind")
    try:
        handler = DISPATCH.get(kind)
    except TypeError:
        logger.warning("action=botellas_recalculo_worker evento=job_invalido reason=kind_no_hasheable raw=%s", raw)
        return

    if handler is None:
        logger.warning("action=botellas_recalculo_worker evento=kind_desconocido kind=%s", kind)
        return

    try:
        await handler()
        _worker_status["ultimo_job"] = payload
        _worker_status["jobs_procesados"] += 1
        _worker_status["ultimo_error"] = None
        logger.info("action=botellas_recalculo_worker evento=job_procesado kind=%s", kind)
    except Exception as exc:  # noqa: BLE001 - loop de background: no hay a quién propagar
        _worker_status["ultimo_error"] = str(exc)
        logger.exception("action=botellas_recalculo_worker evento=job_error kind=%s", kind)


async def _loop_principal() -> None:
    client = get_redis()
    while True:
        try:
            resultado = await client.blpop(QUEUE_KEY, timeout=BLPOP_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 - Redis caído: reintentar tras una pausa, nunca morir
            logger.warning("action=botellas_recalculo_worker evento=blpop_error", exc_info=True)
            await asyncio.sleep(BLPOP_TIMEOUT_SECONDS)
            continue
        if resultado is None:
            continue  # timeout del BLPOP sin jobs — vuelta normal del loop
        _, raw = resultado
        try:
            await _procesar_job(raw)
        except Exception:  # noqa: BLE001 - el loop nunca debe morir por un job individual
            logger.exception("action=botellas_recalculo_worker evento=loop_error_inesperado")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    global _loop_task
    logger.info("action=botellas_recalculo_worker evento=iniciando")
    _loop_task = asyncio.create_task(_loop_principal())
    _worker_status["status"] = "ok"
    try:
        yield
    finally:
        if _loop_task is not None:
            _loop_task.cancel()
        logger.info("action=botellas_recalculo_worker evento=apagando")


app = FastAPI(title="botellas_recalculo_worker", lifespan=_lifespan)


@app.get("/health")
async def health() -> dict:
    loop_vivo = _loop_task is not None and not _loop_task.done()
    return {
        **_worker_status,
        "status": "ok" if loop_vivo else "loop_muerto",
        "time": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=HEALTH_PORT, log_level="warning")
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":  # pragma: no cover
    main()
