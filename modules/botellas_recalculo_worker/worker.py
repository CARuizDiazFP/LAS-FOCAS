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
from core.services.cromo.arbitro.aviso import avisar_en_curso, avisar_evaluacion
from core.services.cromo.arbitro.cola import JOB_KIND_ARBITRO
from core.services.cromo.arbitro.senales import DISPAROS, USUARIO_ARBITRO, Alcance
from core.services.botella_recompute_queue import (
    ADMIN_NOTIFICATIONS_CHANNEL,
    JOB_KIND_BOTELLAS_DUPLICADOS,
    QUEUE_KEY,
    guardar_cache_duplicados,
)
from db.models.cromo import CromoArbitroEvaluacion
from db.session import AsyncSessionLocal, SessionLocal
from modules.botellas_recalculo_worker.config import BLPOP_TIMEOUT_SECONDS, HEALTH_PORT, NOMBRE_SERVICIO

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOGS_ROOT = Path(os.getenv("LOGS_DIR", "/app/Logs"))
logger = setup_logging(
    "botellas_recalculo_worker", LOG_LEVEL, enable_file=True, logs_dir=LOGS_ROOT,
    filename="botellas_recalculo_worker.log",
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

_worker_status: dict = {
    "status": "starting",
    "service": NOMBRE_SERVICIO,
    "ultimo_job": None,
    "ultimo_error": None,
    "jobs_procesados": 0,
}
_loop_task: asyncio.Task | None = None


def _detectar_duplicados_sync() -> list:
    with SessionLocal() as session:
        return detectar_grupos_duplicados_botellas(session)


async def _recalcular_botellas_duplicados() -> None:
    # A un hilo aparte: `detectar_grupos_duplicados_botellas` es SÍNCRONA y pesada (2 queries sin
    # paginar + agrupación en Python; ~100s medidos contra el dev real). Ejecutarla directo en el
    # event loop lo bloqueaba entero, y `GET /health` — el que le dice a Docker si el loop sigue
    # vivo — dejaba de responder durante todo el recálculo: el contenedor se marcaba `unhealthy`
    # justo mientras hacía bien su trabajo. Medido en la verificación en vivo del 2026-08-22.
    # El loop principal sigue serializando jobs (hace `await` de esto), no se paraleliza nada.
    grupos = await asyncio.to_thread(_detectar_duplicados_sync)
    await guardar_cache_duplicados(grupos)
    await get_redis().publish(
        ADMIN_NOTIFICATIONS_CHANNEL,
        json.dumps({
            "type": "botellas_duplicados_recalculado",
            "at": datetime.now(timezone.utc).isoformat(),
        }),
    )


async def _cerrar_evaluacion(evaluacion_id: int, **campos) -> None:
    """Cierra la fila de la corrida en una transacción propia (nueva)."""
    async with AsyncSessionLocal() as sesion:
        fila = await sesion.get(CromoArbitroEvaluacion, evaluacion_id)
        if fila is None:
            return
        for nombre, valor in campos.items():
            setattr(fila, nombre, valor)
        fila.terminada_en = datetime.now(timezone.utc)
        await sesion.commit()


async def _evaluar_arbitro(payload: dict) -> None:
    from core.services.cromo.arbitro.motor import evaluar  # diferido: el motor es pesado

    disparo = payload.get("disparo")
    try:
        alcance = Alcance.desde_dict(payload["alcance"])
    except (ValueError, TypeError, KeyError):
        alcance = None
    if alcance is None or disparo not in DISPAROS:
        logger.warning("action=botellas_recalculo_worker evento=job_invalido kind=%s reason=payload_arbitro", JOB_KIND_ARBITRO)
        return

    reglas = payload.get("reglas")
    evaluacion_id = payload.get("evaluacion_id")
    ahora = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as sesion:
        fila = await sesion.get(CromoArbitroEvaluacion, evaluacion_id) if evaluacion_id else None
        if fila is None:
            fila = CromoArbitroEvaluacion(
                disparo=disparo, alcance=alcance.a_dict(), reglas=reglas, solicitada_por=USUARIO_ARBITRO
            )
            sesion.add(fila)
        fila.estado = "EN_CURSO"
        fila.iniciada_en = ahora
        await sesion.flush()
        evaluacion_id = fila.id
        await sesion.commit()
    await avisar_en_curso(evaluacion_id)

    resumen = None
    error = ""
    async with AsyncSessionLocal() as sesion:
        try:
            resumen = await evaluar(sesion, alcance, disparo, codigos=reglas)
            await sesion.commit()
        except Exception as exc:  # noqa: BLE001 - se registra en la fila, no se propaga
            await sesion.rollback()
            logger.exception("action=botellas_recalculo_worker evento=arbitro_error evaluacion_id=%s", evaluacion_id)
            error = "codigos_invalidos" if isinstance(exc, ValueError) and reglas else (
                f"{type(exc).__name__}: falló la evaluación del árbitro (ver logs del worker)"
            )
    if resumen is None:
        await _cerrar_evaluacion(evaluacion_id, estado="FALLIDA", error=error)
        return
    await _cerrar_evaluacion(
        evaluacion_id, estado="OMITIDA" if resumen.omitida else "OK", resumen=resumen.a_dict()
    )
    await avisar_evaluacion(resumen, evaluacion_id)


DISPATCH: dict[str, Callable[[dict], Awaitable[None]]] = {
    JOB_KIND_BOTELLAS_DUPLICADOS: lambda payload: _recalcular_botellas_duplicados(),
    JOB_KIND_ARBITRO: _evaluar_arbitro,
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
        await handler(payload)
        _worker_status["ultimo_job"] = payload
        _worker_status["jobs_procesados"] += 1
        _worker_status["ultimo_error"] = None
        logger.info("action=botellas_recalculo_worker evento=job_procesado kind=%s", kind)
    except Exception as exc:  # noqa: BLE001 - loop de background: no hay a quién propagar
        _worker_status["ultimo_error"] = str(exc)
        logger.exception("action=botellas_recalculo_worker evento=job_error kind=%s", kind)


async def _loop_principal() -> None:
    while True:
        try:
            # `get_redis()` va DENTRO del try del loop: construir el cliente puede fallar (config/
            # secreto ilegible, URL inválida) y si eso pasara afuera, el loop moriría antes de poder
            # reintentar — justo el modo de falla que el resto de este loop ya evita.
            client = get_redis()
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
    config = uvicorn.Config(app, host="0.0.0.0", port=HEALTH_PORT, log_level="warning", log_config=None)
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":  # pragma: no cover
    main()
