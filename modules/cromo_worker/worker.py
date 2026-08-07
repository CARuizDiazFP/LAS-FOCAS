# Nombre de archivo: worker.py
# Ubicación de archivo: modules/cromo_worker/worker.py
# Descripción: Worker dedicado que ejecuta la ingesta Cromo Red — a demanda (proxeado desde web/app/main.py) y por scheduler configurable

"""Worker de ingesta de inventario Cromo Red.

Corre en su propio contenedor, separado del proceso `web`, para poder programar corridas periódicas
sin competir con el tráfico del panel. Todo el dominio (`core/services/cromo/*`) ya es async, así que
el servidor de control es una app FastAPI mínima servida con uvicorn en el mismo loop de asyncio que
`AsyncIOScheduler` — sin threads, sin puente sync/async (a diferencia de `slack_baneo_notifier/worker.py`,
que es 100% síncrono y por eso usa `http.server` + threads).

La configuración (intervalo, hora de inicio, habilitado, psize/max_paginas/clases) se lee de
`app.cromo_ingesta_config` (fila única) en cada `/reload`, para permitir cambios desde el panel admin
sin reiniciar el contenedor.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from core.logging import setup_logging
from core.services.cromo.client import CromoClient
from core.services.cromo.config import get_cromo_config
from core.services.cromo.ingesta import continuar_corrida, iniciar_corrida
from db.models.cromo import CromoIngestaConfig, CromoIngestaCorrida, CromoIngestaEvento
from db.session import AsyncSessionLocal
from modules.cromo_worker.config import (
    HEALTH_PORT,
    INTERVALO_HORAS_DEFAULT,
    JOB_ID,
    NOMBRE_SERVICIO,
    USUARIO_SCHEDULER,
)

TZ_ARG = ZoneInfo("America/Argentina/Buenos_Aires")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOGS_ROOT = Path(os.getenv("LOGS_DIR", "/app/Logs"))
logger = setup_logging(
    "cromo_worker", LOG_LEVEL, enable_file=True, logs_dir=LOGS_ROOT, filename="cromo_worker.log"
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

_worker_status: dict = {
    "status": "starting",
    "service": NOMBRE_SERVICIO,
    "habilitado": False,
    "intervalo_horas": INTERVALO_HORAS_DEFAULT,
    "hora_inicio": None,
    "ultima_ejecucion": None,
    "ultimo_error": None,
    "corrida_en_curso": None,
}
_scheduler: Optional[AsyncIOScheduler] = None


class RunRequest(BaseModel):
    """`corrida_id` presente: continuar una corrida ya creada por `web` (params ya persistidos en
    `corrida.params`). `corrida_id` ausente: crear una corrida nueva a partir de la config guardada
    — usado tanto por el job programado como por el botón "Ejecutar ahora" del panel."""

    corrida_id: Optional[int] = None
    usuario: Optional[str] = None


def _build_trigger(intervalo: int, hora_inicio: Optional[int]) -> IntervalTrigger:
    """Ancla el ciclo a `hora_inicio` (GMT-3) si se indicó; si no, arranca de inmediato."""
    if hora_inicio is not None:
        now = datetime.now(TZ_ARG)
        start = now.replace(hour=hora_inicio, minute=0, second=0, microsecond=0)
        if start <= now:
            start += timedelta(hours=intervalo)
        return IntervalTrigger(hours=intervalo, start_date=start, timezone=TZ_ARG)
    return IntervalTrigger(hours=intervalo)


async def _leer_config() -> Optional[CromoIngestaConfig]:
    async with AsyncSessionLocal() as sesion:
        return await sesion.get(CromoIngestaConfig, 1)


async def _sincronizar_configuracion() -> dict:
    """Relee `cromo_ingesta_config` y agrega/quita/reprograma el job según corresponda."""
    config = await _leer_config()
    if config is None:
        logger.error("action=cromo_worker evento=config_no_encontrada")
        return {"ok": False, "error": "Configuración no encontrada"}

    nuevo_intervalo = max(1, config.intervalo_horas or INTERVALO_HORAS_DEFAULT)
    nuevo_hora_inicio = config.hora_inicio
    nuevo_habilitado = bool(config.habilitado)
    cambio_horario = (
        nuevo_intervalo != _worker_status["intervalo_horas"]
        or nuevo_hora_inicio != _worker_status["hora_inicio"]
    )

    _worker_status["intervalo_horas"] = nuevo_intervalo
    _worker_status["hora_inicio"] = nuevo_hora_inicio
    _worker_status["habilitado"] = nuevo_habilitado

    if _scheduler is not None:
        existente = _scheduler.get_job(JOB_ID)
        if nuevo_habilitado:
            trigger = _build_trigger(nuevo_intervalo, nuevo_hora_inicio)
            if existente is None:
                _scheduler.add_job(_job_programado, trigger=trigger, id=JOB_ID, max_instances=1)
                logger.info("action=cromo_worker evento=job_agregado intervalo_horas=%s", nuevo_intervalo)
            elif cambio_horario:
                _scheduler.reschedule_job(JOB_ID, trigger=trigger)
                logger.info("action=cromo_worker evento=job_reprogramado intervalo_horas=%s", nuevo_intervalo)
        elif existente is not None:
            _scheduler.remove_job(JOB_ID)
            logger.info("action=cromo_worker evento=job_removido motivo=deshabilitado")

    return {
        "ok": True,
        "habilitado": nuevo_habilitado,
        "intervalo_horas": nuevo_intervalo,
        "hora_inicio": nuevo_hora_inicio,
    }


async def _reconciliar_corridas_huerfanas() -> None:
    """Cierra como FALLIDA cualquier corrida que haya quedado EN_CURSO de un proceso anterior
    (el `asyncio.create_task` viejo en `web`, o un crash de este mismo worker)."""
    async with AsyncSessionLocal() as sesion:
        filas = (
            await sesion.execute(select(CromoIngestaCorrida).where(CromoIngestaCorrida.estado == "EN_CURSO"))
        ).scalars().all()
        for corrida in filas:
            corrida.estado = "FALLIDA"
            corrida.finalizada_at = datetime.now(timezone.utc)
            sesion.add(
                CromoIngestaEvento(
                    corrida_id=corrida.id,
                    accion="ERROR",
                    detalle="Interrumpida: worker reiniciado antes de completar la corrida.",
                )
            )
            logger.warning("action=cromo_worker evento=corrida_huerfana_reconciliada corrida_id=%s", corrida.id)
        if filas:
            await sesion.commit()


async def _crear_corrida_desde_config(usuario: str) -> int:
    """Crea una corrida nueva usando `cromo_ingesta_config` (scheduler o "Ejecutar ahora")."""
    config = await _leer_config()
    if config is None:
        raise RuntimeError("No hay configuración de ingesta Cromo persistida")

    async with AsyncSessionLocal() as sesion:
        corrida = await iniciar_corrida(
            sesion,
            usuario=usuario,
            psize=config.psize,
            max_paginas=config.max_paginas,
            clases=config.clases,
        )
        return corrida.id


async def _continuar_en_bg(corrida_id: int) -> None:
    """Corre las fases de una corrida ya creada, leyendo sus propios params — no depende de que el
    caller (web o el propio worker) los reenvíe: ya quedaron persistidos en `corrida.params`."""
    error: Optional[str] = None
    try:
        async with AsyncSessionLocal() as sesion:
            corrida = await sesion.get(CromoIngestaCorrida, corrida_id)
            if corrida is None:
                logger.error("action=cromo_worker evento=corrida_no_encontrada corrida_id=%s", corrida_id)
                return
            params = corrida.params or {}
            async with CromoClient(config=get_cromo_config()) as cliente:
                await continuar_corrida(
                    cliente,
                    sesion,
                    corrida_id,
                    psize=params.get("psize"),
                    max_paginas=params.get("max_paginas"),
                    clases=params.get("clases") or [],
                )
    except Exception as exc:  # noqa: BLE001 - tarea de background: no hay nadie a quien propagar
        error = str(exc)
        logger.exception("action=cromo_worker evento=error_continuar_corrida corrida_id=%s", corrida_id)
    finally:
        _worker_status["corrida_en_curso"] = None
        _worker_status["ultima_ejecucion"] = datetime.now(timezone.utc).isoformat()
        _worker_status["ultimo_error"] = error
        try:
            async with AsyncSessionLocal() as sesion:
                config = await sesion.get(CromoIngestaConfig, 1)
                if config is not None:
                    config.ultima_ejecucion = datetime.now(timezone.utc)
                    config.ultimo_error = error
                    await sesion.commit()
        except Exception:  # noqa: BLE001
            logger.exception("action=cromo_worker evento=error_actualizando_config_post_corrida")


async def _job_programado() -> None:
    """Callback del `IntervalTrigger`. Chequea `habilitado` en vivo contra la DB, no un snapshot."""
    config = await _leer_config()
    if config is None or not config.habilitado:
        logger.info("action=cromo_worker evento=job_omitido motivo=deshabilitado")
        return
    corrida_id = await _crear_corrida_desde_config(USUARIO_SCHEDULER)
    _worker_status["corrida_en_curso"] = corrida_id
    logger.info("action=cromo_worker evento=job_programado_disparado corrida_id=%s", corrida_id)
    await _continuar_en_bg(corrida_id)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    global _scheduler
    logger.info("action=cromo_worker evento=iniciando")

    await _reconciliar_corridas_huerfanas()

    scheduler = AsyncIOScheduler(timezone=TZ_ARG)
    _scheduler = scheduler
    scheduler.start()
    await _sincronizar_configuracion()

    _worker_status["status"] = "ok"
    logger.info(
        "action=cromo_worker evento=iniciado habilitado=%s intervalo_horas=%s",
        _worker_status["habilitado"], _worker_status["intervalo_horas"],
    )
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        logger.info("action=cromo_worker evento=apagando")


app = FastAPI(title="cromo_worker", lifespan=_lifespan)


@app.get("/health")
async def health() -> dict:
    return {
        **{k: v for k, v in _worker_status.items()},
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/reload")
async def reload_config():
    resultado = await _sincronizar_configuracion()
    return JSONResponse(resultado, status_code=200 if resultado["ok"] else 500)


@app.post("/run")
async def run(body: RunRequest):
    if body.corrida_id is not None:
        _worker_status["corrida_en_curso"] = body.corrida_id
        asyncio.create_task(_continuar_en_bg(body.corrida_id))
        return JSONResponse({"ok": True, "corrida_id": body.corrida_id}, status_code=202)

    try:
        corrida_id = await _crear_corrida_desde_config(body.usuario or USUARIO_SCHEDULER)
    except RuntimeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)

    _worker_status["corrida_en_curso"] = corrida_id
    asyncio.create_task(_continuar_en_bg(corrida_id))
    return JSONResponse({"ok": True, "corrida_id": corrida_id}, status_code=202)


def main() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=HEALTH_PORT, log_level="warning")
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":  # pragma: no cover
    main()
