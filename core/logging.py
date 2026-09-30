# Nombre de archivo: logging.py
# Ubicación de archivo: core/logging.py
# Descripción: Utilidades centralizadas de logging (stdout + archivo en Logs/ con buffer, borrable en uso)

from __future__ import annotations

import atexit
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

_APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Argentina/Buenos_Aires")

_FORMAT = "%(asctime)s service=%(name)s level=%(levelname)s msg=%(message)s"

# Cada cuánto se vuelca el buffer a disco. Es la ventana "de algunos segundos" en la que un borrado o
# truncado del archivo no pierde nada: el archivo sólo está abierto mientras se escribe cada tanda.
_FLUSH_SEGUNDOS = float(os.getenv("LOG_FLUSH_SECONDS", "2"))
_CAPACIDAD_BUFFER = 500

# Lanzado por CLI (`uvicorn app.main:app`), uvicorn configura "uvicorn" y "uvicorn.access" con
# `propagate=False` ANTES de importar la app, así que el handler del raíz nunca les llega: se les
# cuelga el mismo handler, pero sólo si en ese momento no propagan ("uvicorn.error" propaga a
# "uvicorn", y con `uvicorn.Config(log_config=None)` todos propagan al raíz: colgarlo igual duplicaría
# cada línea).
_LOGGERS_SIN_PROPAGACION = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _logs_dir_por_defecto() -> Path:
    """`LOGS_DIR` si está (los contenedores montan `Logs/` en `/app/Logs`), si no `<repo>/Logs`.

    Hasta 2026-09-30 el default era `parents[2]`, que desde `core/logging.py` apunta al directorio
    PADRE del repo (`/home/support-focal-01/Logs` en el host, `/Logs` en un contenedor).
    """
    return Path(os.getenv("LOGS_DIR") or Path(__file__).resolve().parents[1] / "Logs")


class _ArgTzFormatter(logging.Formatter):
    """Formatter que emite timestamps en la zona horaria configurada (GMT-3 por defecto)."""

    _tz = ZoneInfo(_APP_TIMEZONE)

    def converter(self, timestamp: float):  # type: ignore[override]
        from datetime import datetime
        return datetime.fromtimestamp(timestamp, tz=self._tz).timetuple()


class BufferedAppendFileHandler(logging.Handler):
    """Handler de archivo que nunca retiene el archivo abierto.

    Junta los registros en memoria y los vuelca cada `flush_interval` segundos, al llenar
    `capacity` registros o de inmediato ante un `ERROR` o más grave. Cada volcado abre la ruta en
    modo append, escribe y cierra. Consecuencias buscadas:

    - El archivo se puede **borrar, truncar o renombrar mientras el servicio corre**: el volcado
      siguiente vuelve a abrir la ruta (y la carpeta, si también se borró). No hay offset guardado,
      así que truncar no deja huecos, y renombrar sirve como rotación externa.
    - Varios procesos pueden escribir el mismo archivo: cada tanda es un único `write` en `O_APPEND`.
      Por eso la rotación ya no la hace el handler (`RotatingFileHandler` rota mal con varios
      procesos) sino `scripts/logs_cleanup.py`.

    Un hilo daemon vuelca aunque no lleguen registros nuevos, y `atexit`/`close()` vuelcan lo
    pendiente al terminar.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        flush_interval: float = _FLUSH_SEGUNDOS,
        capacity: int = _CAPACIDAD_BUFFER,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__()
        self.path = Path(path)
        self.flush_interval = flush_interval
        self.capacity = capacity
        self.encoding = encoding
        self._buffer: list[str] = []
        self._buffer_lock = threading.Lock()
        self._cerrado = threading.Event()
        self._aviso_error_emitido = False
        self._hilo = threading.Thread(target=self._volcar_periodicamente, name=f"log-flush-{self.path.name}", daemon=True)
        self._hilo.start()
        atexit.register(self.flush)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            linea = self.format(record) + "\n"
        except Exception:  # noqa: BLE001 - mismo contrato que logging.Handler.handleError
            self.handleError(record)
            return
        with self._buffer_lock:
            self._buffer.append(linea)
            lleno = len(self._buffer) >= self.capacity
        if lleno or record.levelno >= logging.ERROR:
            self.flush()

    def flush(self) -> None:
        with self._buffer_lock:
            if not self._buffer:
                return
            bloque, self._buffer = "".join(self._buffer), []
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding=self.encoding) as archivo:
                archivo.write(bloque)
        except OSError as exc:
            # Sin disco o sin permisos no hay a dónde escribir el error: una sola vez por stderr, que
            # igual termina en `docker logs`.
            if not self._aviso_error_emitido:
                self._aviso_error_emitido = True
                print(f"action=logging evento=error_escritura path={self.path} error={exc}", file=sys.stderr)

    def _volcar_periodicamente(self) -> None:
        while not self._cerrado.wait(self.flush_interval):
            self.flush()

    def close(self) -> None:
        self._cerrado.set()
        self.flush()
        super().close()


def _tiene_handler_de_archivo(logger: logging.Logger) -> bool:
    return any(isinstance(h, BufferedAppendFileHandler) for h in logger.handlers)


def setup_logging(
    service: str,
    level: str | int = "INFO",
    enable_file: bool | None = None,
    logs_dir: str | Path | None = None,
    filename: str | None = None,
    max_bytes: Optional[int] = None,
    backup_count: Optional[int] = None,
) -> logging.Logger:
    """Configura logging estándar para un servicio: stdout + `Logs/<service>.log`.

    El archivo se cuelga del logger **raíz** (y de los `uvicorn.*`, que no propagan), así que
    llegan también los módulos que usan `getLogger(__name__)`. Un proceso escribe un solo archivo: el
    primer `setup_logging` con archivo gana y los siguientes reutilizan ese handler.

    Args:
        service: nombre lógico del servicio (web, api, bot, etc.)
        level: nivel (str o int) por defecto INFO
        enable_file: fuerza escritura a archivo; si None se activa si ENV=development
        logs_dir: carpeta destino (default: `LOGS_DIR` o `<repo>/Logs`)
        filename: nombre archivo (default: f"{service}.log")
        max_bytes, backup_count: ignorados desde 2026-09-30; la rotación la hace `scripts/logs_cleanup.py`
    """
    lvl = logging.getLevelName(level) if isinstance(level, str) else level
    formatter = _ArgTzFormatter(_FORMAT)
    logging.basicConfig(level=lvl, format=_FORMAT)
    root = logging.getLogger()
    for handler in root.handlers:
        handler.setFormatter(formatter)
    logger = logging.getLogger(service)
    if enable_file is None:
        enable_file = os.getenv("ENV", "development").lower() == "development"
    if not enable_file or _tiene_handler_de_archivo(root):
        return logger
    try:
        base_dir = Path(logs_dir) if logs_dir else _logs_dir_por_defecto()
        base_dir.mkdir(parents=True, exist_ok=True)
        fh = BufferedAppendFileHandler(base_dir / (filename or f"{service}.log"))
        fh.setFormatter(formatter)
        fh.setLevel(lvl)
        root.addHandler(fh)
        for nombre in _LOGGERS_SIN_PROPAGACION:
            otro = logging.getLogger(nombre)
            if not otro.propagate and not _tiene_handler_de_archivo(otro):
                otro.addHandler(fh)
        # Primera línea garantizada de cada proceso: `scripts/logs_verificar.py` la usa para confirmar
        # que el servicio escribe su archivo desde que arrancó, aunque todavía no haya tenido tráfico.
        logger.info("action=logging evento=inicio servicio=%s pid=%s path=%s", service, os.getpid(), fh.path)
    except Exception as exc:  # noqa: BLE001
        logger.error("action=logging file_handler=failed error=%s", exc)
    return logger


__all__ = ["BufferedAppendFileHandler", "setup_logging"]
