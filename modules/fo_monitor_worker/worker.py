# Nombre de archivo: worker.py
# Ubicación de archivo: modules/fo_monitor_worker/worker.py
# Descripción: Loop del worker de FO Monitor — tick del motor cada 10 s con advisory lock y health en :8098

"""Corre en su propio contenedor (mismo esqueleto que `modules/botellas_recalculo_worker/`), pero
el disparador es un tick periódico: toda la lógica y el estado viven en `core/services/fo_monitor/
motor.py` + tablas `app.fomon_*`, así que el worker no guarda nada en memoria salvo métricas.

- El tick es síncrono (SQLAlchemy sync + slack_sdk) y corre en `asyncio.to_thread` para que
  `/health` siga respondiendo.
- Sólo el proceso que obtiene `pg_try_advisory_lock(ADVISORY_LOCK_KEY)` ejecuta el motor; la
  conexión que lo sostiene queda abierta toda la vida del proceso.
- Slack sólo vía `WebClient` con el bot token (nunca Socket Mode: ver `slack_gateway.py`).
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from sqlalchemy import text

from core.config import get_settings
from core.logging import setup_logging
from core.services.fo_monitor.motor import tick
from core.services.fo_monitor.slack_gateway import SlackGatewayWebClient
from db.session import SessionLocal, engine
from modules.fo_monitor_worker.config import ADVISORY_LOCK_KEY, HEALTH_PORT, NOMBRE_SERVICIO, TICK_SECONDS

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOGS_ROOT = Path(os.getenv("LOGS_DIR", "/app/Logs"))
logger = setup_logging(
    "fo_monitor_worker", LOG_LEVEL, enable_file=True, logs_dir=LOGS_ROOT, filename="fo_monitor_worker.log",
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

_status: dict = {
    "status": "starting",
    "service": NOMBRE_SERVICIO,
    "lock": False,
    "ultimo_tick": None,
    "ultimo_resumen": None,
    "ultimo_error": None,
    "ticks": 0,
}
_loop_task: asyncio.Task | None = None
_lock_conn = None
_gateway: SlackGatewayWebClient | None = None


def _intentar_lock() -> bool:
    global _lock_conn
    if _lock_conn is not None:
        return True
    conn = engine.connect()
    obtenido = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY}).scalar()
    conn.commit()
    if obtenido:
        _lock_conn = conn
        return True
    conn.close()
    return False


def _tick_sync() -> dict:
    with SessionLocal() as session:
        resumen = tick(session, _gateway)
    return asdict(resumen)


async def _loop_principal() -> None:
    global _gateway
    while True:
        try:
            if _gateway is None:
                token = get_settings().slack.bot_token
                if not token:
                    _status["ultimo_error"] = "sin slack_bot_token_v1"
                    await asyncio.sleep(TICK_SECONDS * 6)
                    continue
                _gateway = SlackGatewayWebClient(token)
            _status["lock"] = await asyncio.to_thread(_intentar_lock)
            if _status["lock"]:
                resumen = await asyncio.to_thread(_tick_sync)
                _status["ultimo_resumen"] = resumen
                _status["ultimo_tick"] = datetime.now(timezone.utc).isoformat()
                _status["ticks"] += 1
                _status["ultimo_error"] = "; ".join(resumen["errores"]) or None
                if resumen["consultas_enviadas"] or resumen["intervenciones_nuevas"] or resumen["intervenciones_cerradas"]:
                    logger.info("action=fo_monitor_worker evento=tick resumen=%s", resumen)
        except Exception as exc:  # noqa: BLE001 — el loop nunca debe morir
            _status["ultimo_error"] = str(exc)
            logger.exception("action=fo_monitor_worker evento=loop_error")
        await asyncio.sleep(TICK_SECONDS)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    global _loop_task
    logger.info("action=fo_monitor_worker evento=iniciando")
    _loop_task = asyncio.create_task(_loop_principal())
    _status["status"] = "ok"
    try:
        yield
    finally:
        if _loop_task is not None:
            _loop_task.cancel()
        if _lock_conn is not None:
            _lock_conn.close()
        logger.info("action=fo_monitor_worker evento=apagando")


app = FastAPI(title="fo_monitor_worker", lifespan=_lifespan)


@app.get("/health")
async def health() -> dict:
    loop_vivo = _loop_task is not None and not _loop_task.done()
    return {**_status, "status": "ok" if loop_vivo else "loop_muerto", "time": datetime.now(timezone.utc).isoformat()}


def main() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=HEALTH_PORT, log_level="warning", log_config=None)
    asyncio.run(uvicorn.Server(config).serve())


if __name__ == "__main__":  # pragma: no cover
    main()
