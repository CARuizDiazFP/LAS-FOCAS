# Nombre de archivo: runner.py
# Ubicación de archivo: office_service/app/runner.py
# Descripción: Orquestador que inicia LibreOffice headless y el servidor Uvicorn

"""Motor de arranque del microservicio LibreOffice/UNO."""

from __future__ import annotations

import asyncio
import logging
import signal
import subprocess
import sys
from contextlib import suppress
from typing import Sequence

import uvicorn

from .config import Settings, get_settings
from .uno_client import UnoUnavailableError, UnoPythonNotInstalledError, uno_client

LOGGER = logging.getLogger(__name__)


class LibreOfficeProcess:
    """Gestiona el proceso de LibreOffice en modo headless."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._process: subprocess.Popen[str] | None = None

    def _build_command(self) -> Sequence[str]:
        return (
            self._settings.soffice_binary,
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            "--norestore",
            f"--accept={self._settings.accept_descriptor}",
        )

    def start(self) -> None:
        if self._process and self._process.poll() is None:
            LOGGER.debug("LibreOffice headless ya está en ejecución")
            return

        command = list(self._build_command())
        LOGGER.info("Iniciando LibreOffice headless: %s", " ".join(command))

        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def stop(self) -> None:
        if not self._process or self._process.poll() is not None:
            LOGGER.debug("LibreOffice headless ya estaba detenido")
            return

        LOGGER.info("Deteniendo LibreOffice headless")
        self._process.terminate()
        with suppress(subprocess.TimeoutExpired):
            self._process.wait(timeout=10)

        if self._process.poll() is None:
            LOGGER.warning("LibreOffice headless no respondió a terminate; enviando kill")
            self._process.kill()

    async def wait_until_ready(self, timeout: float) -> None:
        if not self._process:
            raise RuntimeError("LibreOffice aún no fue iniciado")

        LOGGER.info("Esperando a que LibreOffice UNO acepte conexiones...")
        deadline = loop_time() + timeout
        last_error: Exception | None = None

        while loop_time() < deadline:
            await asyncio.sleep(0.5)
            try:
                uno_client.get_connection(force_refresh=True)
                LOGGER.info("LibreOffice UNO está disponible")
                return
            except UnoUnavailableError as exc:
                last_error = exc
        raise TimeoutError(f"LibreOffice UNO no respondió en {timeout} segundos: {last_error}")


def loop_time() -> float:
    return asyncio.get_event_loop().time()


async def serve() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s|%(name)s|%(message)s")

    if not settings.enable_uno:
        LOGGER.warning("UNO está deshabilitado; se iniciará solo la API FastAPI")

    office_process = LibreOfficeProcess(settings=settings)

    if settings.enable_uno:
        office_process.start()
        try:
            await office_process.wait_until_ready(timeout=15)
        except TimeoutError as exc:
            LOGGER.error("No fue posible iniciar LibreOffice UNO: %s", exc)
            office_process.stop()
            LOGGER.warning("Continuando en modo degradado: API disponible sin capacidades de conversión UNO")
            settings.enable_uno = False  # type: ignore[attr-defined]
        except UnoPythonNotInstalledError as exc:  # pragma: no cover - depende del entorno de imagen
            LOGGER.error("python-uno no disponible: %s", exc)
            office_process.stop()
            LOGGER.warning("Continuando en modo degradado sin UNO. Verificar instalación de paquete python3-uno")
            settings.enable_uno = False  # type: ignore[attr-defined]

    config = uvicorn.Config(
        "app.main:app",
        host=settings.uvicorn_host,
        port=settings.uvicorn_port,
        reload=settings.uvicorn_reload,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config=config)

    loop = asyncio.get_event_loop()

    def handle_exit(*_: object) -> None:
        LOGGER.info("Recibida señal de parada; cerrando servicios")
        if settings.enable_uno:
            office_process.stop()
        server.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_exit)

    await server.serve()


def main() -> None:
    try:
        asyncio.run(serve())
    except Exception as exc:  # pragma: no cover - rutas críticas de arranque
        LOGGER.error("Fallo crítico al iniciar el servicio: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
