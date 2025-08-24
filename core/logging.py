# Nombre de archivo: logging.py
# Ubicación de archivo: core/logging.py
# Descripción: Configuración centralizada de logging en formato JSON y variables de contexto

import contextvars
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Dict

import orjson

# Variables de contexto accesibles por los middlewares y el formatter
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
tg_user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("tg_user_id", default="-")


class JsonFormatter(logging.Formatter):
    """Formatter que serializa los registros en formato JSON."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service
        self._base_fields = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
        }

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        message = record.getMessage()
        log: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "service": self.service,
            "message": message,
            "action": getattr(record, "action", message),
            "tg_user_id": getattr(record, "tg_user_id", tg_user_id_var.get()),
            "request_id": getattr(record, "request_id", request_id_var.get()),
        }
        for key, value in record.__dict__.items():
            if key not in self._base_fields and key not in log:
                log[key] = value
        return orjson.dumps(log).decode()


def configure_logging(service: str) -> None:
    """Configura logging con salida JSON y parámetros desde el entorno."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, level_name, logging.INFO)
    log_dir = os.getenv("LOG_DIR")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(JsonFormatter(service))
    handlers = [stream_handler]

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_path = os.path.join(log_dir, f"{service}.log")
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonFormatter(service))
        handlers.append(file_handler)

    root = logging.getLogger()
    root.handlers = handlers
    root.setLevel(log_level)

