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
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

TZ_ARG = ZoneInfo("America/Argentina/Buenos_Aires")

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
    "hora_inicio": None,
}
_status_lock = threading.Lock()
_scheduler: BlockingScheduler | None = None


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
                    "last_error": _worker_status["last_error"],
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

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/reload":
            resultado = _sincronizar_configuracion_worker(_scheduler)
            status_code = 200 if resultado["ok"] else 500
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resultado).encode())
        elif self.path == "/trigger":
            # Ejecutar el job inmediatamente en un thread separado
            if _scheduler is not None:
                thread = threading.Thread(
                    target=_ejecutar_notificacion,
                    args=[_scheduler],
                    daemon=True,
                )
                thread.start()
                self.send_response(202)
            else:
                self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": _scheduler is not None, "msg": "Ejecución iniciada"}).encode())
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


# ── Utilidades de scheduling ────────────────────────────────────


def _build_trigger(intervalo: int, hora_inicio: int | None) -> IntervalTrigger:
    """Construye el IntervalTrigger anclado a hora_inicio (GMT-3) si se indicó.

    Si ``hora_inicio`` es None el trigger empieza de inmediato.
    Si se especifica (0-23), la primera ejecución ocurre en la próxima
    ocurrencia de esa hora y luego cada ``intervalo`` horas.
    """
    if hora_inicio is not None:
        now = datetime.now(TZ_ARG)
        start = now.replace(hour=hora_inicio, minute=0, second=0, microsecond=0)
        if start <= now:
            start += timedelta(hours=intervalo)
        return IntervalTrigger(hours=intervalo, start_date=start, timezone=TZ_ARG)
    return IntervalTrigger(hours=intervalo)


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


def _sincronizar_configuracion_worker(scheduler: BlockingScheduler | None) -> dict[str, object]:
    """Sincroniza el scheduler y el estado expuesto con la configuración persistida."""
    config = _leer_config()
    if config is None:
        logger.error("No se encontró configuración para '%s' al sincronizar", NOMBRE_SERVICIO)
        return {"ok": False, "error": "Configuración no encontrada"}

    nuevo_intervalo = max(1, config.intervalo_horas or INTERVALO_HORAS_DEFAULT)
    nuevo_hora_inicio: int | None = config.hora_inicio  # puede ser None

    with _status_lock:
        intervalo_actual = _worker_status.get("intervalo_horas", INTERVALO_HORAS_DEFAULT)
        hora_inicio_actual = _worker_status.get("hora_inicio")
        _worker_status["intervalo_horas"] = nuevo_intervalo
        _worker_status["hora_inicio"] = nuevo_hora_inicio

    config_cambio = nuevo_intervalo != intervalo_actual or nuevo_hora_inicio != hora_inicio_actual
    if scheduler is not None and config_cambio:
        logger.info(
            "Config cambiada (intervalo %dh→%dh, hora_inicio %s→%s), reprogramando scheduler",
            intervalo_actual, nuevo_intervalo, hora_inicio_actual, nuevo_hora_inicio,
        )
        scheduler.reschedule_job(
            JOB_ID,
            trigger=_build_trigger(nuevo_intervalo, nuevo_hora_inicio),
        )

    return {
        "ok": True,
        "service": _worker_status["service"],
        "intervalo_horas": nuevo_intervalo,
        "hora_inicio": nuevo_hora_inicio,
        "activo": bool(config.activo),
    }


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

    _sincronizar_configuracion_worker(scheduler)


# ── Entry Point ─────────────────────────────────────────────────


def main() -> None:
    """Punto de entrada del worker."""
    global _scheduler

    logger.info("Inicializando worker de notificaciones de baneos...")

    # Iniciar health check
    health_server = _start_health_server()

    # Leer configuración inicial
    config = _leer_config()
    intervalo = INTERVALO_HORAS_DEFAULT
    hora_inicio: int | None = None
    if config:
        intervalo = max(1, config.intervalo_horas)
        hora_inicio = config.hora_inicio
        logger.info(
            "Configuración cargada: intervalo=%dh, hora_inicio=%s, canales='%s', activo=%s",
            intervalo,
            hora_inicio,
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
        _worker_status["hora_inicio"] = hora_inicio

    # Configurar scheduler
    scheduler = BlockingScheduler()
    _scheduler = scheduler
    scheduler.add_job(
        _ejecutar_notificacion,
        trigger=_build_trigger(intervalo, hora_inicio),
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
