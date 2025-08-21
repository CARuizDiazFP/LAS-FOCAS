# Nombre de archivo: logging.py
# Ubicación de archivo: core/logging.py
# Descripción: Configuración centralizada de logging en formato JSON y variables de contexto

import contextvars
import logging
from datetime import datetime
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
    """Configura logging básico con salida JSON."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

