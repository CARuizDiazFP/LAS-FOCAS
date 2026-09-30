# Nombre de archivo: logging_setup.py
# Ubicación de archivo: office_service/app/logging_setup.py
# Descripción: Logging del microservicio office a stdout + Logs/office.log con buffer (copia de core/logging.py)

"""Copia deliberada del handler de `core/logging.py`: `office_service` se construye con su propio
contexto (`deploy/compose.yml`, `context: ../office_service`) y no tiene `core/` en la imagen. Si se
cambia el comportamiento del handler, cambiarlo en los dos lugares (lo cubre
`tests/test_office_logging_setup.py`, que compara ambas clases).
"""

from __future__ import annotations

import atexit
import logging
import os
import sys
import threading
from pathlib import Path

_FORMAT = "%(asctime)s service=%(name)s level=%(levelname)s msg=%(message)s"
_FLUSH_SEGUNDOS = float(os.getenv("LOG_FLUSH_SECONDS", "2"))
_CAPACIDAD_BUFFER = 500


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


def configurar_logging(level: str = "INFO", *, service: str = "office") -> None:
    """stdout + `LOGS_DIR/<service>.log` (sólo si `LOGS_DIR` está definido, como en compose)."""
    logging.basicConfig(level=level, format=_FORMAT)
    root = logging.getLogger()
    logs_dir = os.getenv("LOGS_DIR")
    if not logs_dir or any(isinstance(h, BufferedAppendFileHandler) for h in root.handlers):
        return
    # El usuario `office` de la imagen no es el dueño de Logs/ (1001): escribe por grupo
    # (`group_add: ["1001"]`). Con umask 002 su archivo queda también escribible por el grupo, así
    # `scripts/logs_cleanup.py --truncar` lo puede vaciar desde el host.
    os.umask(0o002)
    fh = BufferedAppendFileHandler(Path(logs_dir) / f"{service}.log")
    fh.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(fh)
