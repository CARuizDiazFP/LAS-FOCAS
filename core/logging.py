# Nombre de archivo: logging.py
# Ubicación de archivo: core/logging.py
# Descripción: Utilidades centralizadas de logging (stdout + archivo rotativo opcional)

from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os
from typing import Optional
from zoneinfo import ZoneInfo

_DEFAULT_LOGS_DIR = Path(os.getenv("LOGS_DIR", str(Path(__file__).resolve().parents[2] / "Logs")))
_APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Argentina/Buenos_Aires")

_FORMAT = "%(asctime)s service=%(name)s level=%(levelname)s msg=%(message)s"


class _ArgTzFormatter(logging.Formatter):
    """Formatter que emite timestamps en la zona horaria configurada (GMT-3 por defecto)."""

    _tz = ZoneInfo(_APP_TIMEZONE)

    def converter(self, timestamp: float):  # type: ignore[override]
        from datetime import datetime
        return datetime.fromtimestamp(timestamp, tz=self._tz).timetuple()


def setup_logging(
    service: str,
    level: str | int = "INFO",
    enable_file: bool | None = None,
    logs_dir: str | Path | None = None,
    filename: str | None = None,
    max_bytes: int = 5_000_000,
    backup_count: int = 3,
) -> logging.Logger:
    """Configura logging estándar para un servicio.

    Args:
        service: nombre lógico del servicio (web, api, bot, etc.)
        level: nivel (str o int) por defecto INFO
        enable_file: fuerza escritura a archivo; si None se activa si ENV=development
        logs_dir: carpeta destino (default: ../Logs relativa al cwd)
        filename: nombre archivo (default: f"{service}.log")
        max_bytes: tamaño máximo antes de rotar
        backup_count: cantidad de backups
    """
    lvl = logging.getLevelName(level) if isinstance(level, str) else level
    formatter = _ArgTzFormatter(_FORMAT)
    logging.basicConfig(level=lvl, format=_FORMAT)
    # Aplicar formatter GMT-3 al handler raíz existente
    for handler in logging.root.handlers:
        handler.setFormatter(formatter)
    logger = logging.getLogger(service)
    # Evitar duplicados al llamar varias veces
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return logger
    if enable_file is None:
        enable_file = os.getenv("ENV", "development").lower() == "development"
    if enable_file:
        try:
            base_dir = Path(logs_dir) if logs_dir else _DEFAULT_LOGS_DIR
            base_dir.mkdir(parents=True, exist_ok=True)
            file_name = filename or f"{service}.log"
            fh = RotatingFileHandler(base_dir / file_name, maxBytes=max_bytes, backupCount=backup_count)
            fh.setFormatter(formatter)
            fh.setLevel(lvl)
            logger.addHandler(fh)
            logger.debug("action=logging file_handler=enabled path=%s", base_dir / file_name)
        except Exception as exc:  # noqa: BLE001
            logger.error("action=logging file_handler=failed error=%s", exc)
    return logger

__all__ = ["setup_logging"]
