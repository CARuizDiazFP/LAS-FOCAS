# Nombre de archivo: worker.py
# Ubicación de archivo: modules/slack_baneo_notifier/worker.py
# Descripción: Worker principal que ejecuta notificaciones periódicas de baneos a Slack

"""Worker de notificaciones Slack para baneos de cámaras.

Ejecuta periódicamente un job que consulta cámaras baneadas en la DB,
genera un Excel y lo envía a canales de Slack configurados.
La configuración (intervalo, canales, activo) se lee de app.config_servicios
en cada ejecución para permitir cambios dinámicos desde el panel admin.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.config import get_settings
from core.logging import setup_logging
from db.session import SessionLocal
from db.models.servicios import ConfigServicios
from modules.slack_baneo_notifier.config import (
    HEALTH_PORT,
    INTERVALO_HORAS_DEFAULT,
    JOB_ID,
    NOMBRE_SERVICIO,
)
from modules.slack_baneo_notifier.notifier import enviar_reporte_baneos

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOGS_ROOT = Path(os.getenv("LOGS_DIR", "/app/Logs"))
logger = setup_logging(
    "slack_baneo_worker",
    LOG_LEVEL,
    enable_file=True,
    logs_dir=LOGS_ROOT,
    filename="slack_baneo_worker.log",
)

# Estado global del worker para health check
_worker_status: dict = {
    "status": "starting",
    "service": "slack_baneo_worker",
    "last_run": None,
    "last_error": None,
    "intervalo_horas": INTERVALO_HORAS_DEFAULT,
}
_status_lock = threading.Lock()


# ── Health Check HTTP embebido ──────────────────────────────────


class _HealthHandler(BaseHTTPRequestHandler):
    """Handler HTTP mínimo para el health check del worker."""

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            with _status_lock:
                safe_status = {
                    "status": _worker_status["status"],
                    "service": _worker_status["service"],
                    "last_run": _worker_status["last_run"],
                    "intervalo_horas": _worker_status["intervalo_horas"],
                    "time": datetime.now(timezone.utc).isoformat(),
                }
                body = json.dumps(safe_status)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silenciar logs del HTTP server para no ensuciar stdout."""


def _start_health_server() -> HTTPServer:
    """Inicia el servidor de health check en un thread daemon."""
    server = HTTPServer(("0.0.0.0", HEALTH_PORT), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health check disponible en http://0.0.0.0:%d/health", HEALTH_PORT)
    return server


# ── Lógica del Job ──────────────────────────────────────────────


def _leer_config() -> ConfigServicios | None:
    """Lee la configuración del servicio desde la DB."""
    session = SessionLocal()
    try:
        config = (
            session.query(ConfigServicios)
            .filter(ConfigServicios.nombre_servicio == NOMBRE_SERVICIO)
            .first()
        )
        if config:
            # Detach para poder usar los valores fuera de la sesión
            session.expunge(config)
        return config
    finally:
        session.close()


def _ejecutar_notificacion(scheduler: BlockingScheduler) -> None:
    """Job principal: lee config, envía notificación, actualiza timestamps."""
    logger.info("Ejecutando job de notificación de baneos...")

    config = _leer_config()
    if config is None:
        logger.error("No se encontró configuración para '%s' en config_servicios", NOMBRE_SERVICIO)
        return

    if not config.activo:
        logger.info("Servicio desactivado, omitiendo ejecución")
        return

    # Parsear canales
    canales = [c.strip() for c in config.slack_channels.split(",") if c.strip()]
    if not canales:
        logger.warning("No hay canales Slack configurados, omitiendo envío")
        return

    # Obtener token de Slack desde settings (.env)
    settings = get_settings()
    bot_token = settings.slack.bot_token

    # Ejecutar envío
    session = SessionLocal()
    try:
        error = enviar_reporte_baneos(canales, bot_token, session)

        # Actualizar última ejecución y error en DB
        db_config = (
            session.query(ConfigServicios)
            .filter(ConfigServicios.nombre_servicio == NOMBRE_SERVICIO)
            .first()
        )
        if db_config:
            db_config.ultima_ejecucion = datetime.now(timezone.utc)
            db_config.ultimo_error = error
            session.commit()

        # Actualizar estado del worker
        with _status_lock:
            _worker_status["status"] = "ok" if error is None else "error"
            _worker_status["last_run"] = datetime.now(timezone.utc).isoformat()
            _worker_status["last_error"] = error

    except Exception as exc:
        session.rollback()
        logger.error("Error en job de notificación: %s", exc, exc_info=True)
        with _status_lock:
            _worker_status["status"] = "error"
            _worker_status["last_error"] = str(exc)
    finally:
        session.close()

    # Verificar si el intervalo cambió para reprogramar
    config_actual = _leer_config()
    if config_actual and config_actual.intervalo_horas != _worker_status.get("intervalo_horas"):
        nuevo_intervalo = max(1, config_actual.intervalo_horas)
        logger.info(
            "Intervalo cambió de %d a %d horas, reprogramando...",
            _worker_status.get("intervalo_horas", INTERVALO_HORAS_DEFAULT),
            nuevo_intervalo,
        )
        scheduler.reschedule_job(
            JOB_ID,
            trigger=IntervalTrigger(hours=nuevo_intervalo),
        )
        with _status_lock:
            _worker_status["intervalo_horas"] = nuevo_intervalo


# ── Entry Point ─────────────────────────────────────────────────


def main() -> None:
    """Punto de entrada del worker."""
    logger.info("Inicializando worker de notificaciones de baneos...")

    # Iniciar health check
    health_server = _start_health_server()

    # Leer configuración inicial
    config = _leer_config()
    intervalo = INTERVALO_HORAS_DEFAULT
    if config:
        intervalo = max(1, config.intervalo_horas)
        logger.info(
            "Configuración cargada: intervalo=%dh, canales='%s', activo=%s",
            intervalo,
            config.slack_channels,
            config.activo,
        )
    else:
        logger.warning(
            "No se encontró configuración en DB, usando defaults (intervalo=%dh)",
            intervalo,
        )

    with _status_lock:
        _worker_status["status"] = "ok"
        _worker_status["intervalo_horas"] = intervalo

    # Configurar scheduler
    scheduler = BlockingScheduler()
    scheduler.add_job(
        _ejecutar_notificacion,
        trigger=IntervalTrigger(hours=intervalo),
        id=JOB_ID,
        name="Notificación de baneos a Slack",
        args=[scheduler],
        max_instances=1,
    )

    # Señales para apagado limpio
    def _shutdown(signum: int, frame: object) -> None:
        logger.info("Señal %d recibida, apagando worker...", signum)
        scheduler.shutdown(wait=False)
        health_server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("Worker iniciado. Próxima ejecución en %d hora(s).", intervalo)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker detenido.")
    finally:
        health_server.shutdown()


if __name__ == "__main__":  # pragma: no cover
    main()
