# Nombre de archivo: uno_client.py
# Ubicación de archivo: office_service/app/uno_client.py
# Descripción: Gestión de conexiones UNO hacia LibreOffice y utilidades de salud

"""Gestor de conexión UNO para interactuar con LibreOffice."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from collections.abc import Callable

from .config import Settings, get_settings

try:
    import uno  # type: ignore
    from com.sun.star.connection import NoConnectException  # type: ignore
except ImportError:  # pragma: no cover - depende de LibreOffice
    uno = None  # type: ignore
    NoConnectException = Exception  # type: ignore

LOGGER = logging.getLogger(__name__)


class UnoUnavailableError(RuntimeError):
    """Indica que no se pudo establecer la conexión UNO."""


class UnoPythonNotInstalledError(RuntimeError):
    """Indica que el módulo python-uno no está instalado en el entorno."""


@dataclass(slots=True)
class UnoConnection:
    """Representa una conexión UNO válida."""

    context: Any
    manager: Any


class UnoHealth(BaseModel):
    """Modelo de respuesta para la salud del conector UNO."""

    available: bool
    message: str


class UnoClient:
    """Administra la conexión perezosa con LibreOffice UNO."""

    def __init__(self, settings_factory: Callable[[], Settings] | None = None) -> None:
        self._settings_factory = settings_factory or get_settings
        self._lock = threading.Lock()
        self._connection: UnoConnection | None = None

    @property
    def settings(self) -> Settings:
        return self._settings_factory()

    def _resolve_context(self) -> UnoConnection:
        if uno is None:
            LOGGER.error("python-uno no está disponible en el entorno")
            raise UnoPythonNotInstalledError("python-uno no está disponible")

        local_context = uno.getComponentContext()
        resolver = local_context.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver",
            local_context,
        )
        settings = self.settings
        accept_parts = settings.accept_descriptor.split(";")
        accept_parts[0] = f"socket,host={settings.soffice_connect_host},port={settings.soffice_port}"
        uno_descriptor = "uno:" + ";".join(accept_parts)

        try:
            remote_context = resolver.resolve(uno_descriptor)
            service_manager = remote_context.ServiceManager
            LOGGER.debug("Conexión UNO establecida correctamente")
            return UnoConnection(context=remote_context, manager=service_manager)
        except NoConnectException as exc:  # pragma: no cover - entorno sin UNO real
            LOGGER.warning("No fue posible conectar con LibreOffice UNO: %s", exc)
            raise UnoUnavailableError(str(exc)) from exc

    def get_connection(self, force_refresh: bool = False) -> UnoConnection:
        """Obtiene (y cachea) la conexión UNO."""

        settings = self.settings
        if not settings.enable_uno:
            raise UnoUnavailableError("UNO se encuentra deshabilitado por configuración")

        with self._lock:
            if self._connection is None or force_refresh:
                self._connection = self._resolve_context()
            return self._connection

    def health(self) -> UnoHealth:
        """Evalúa la salud de la conexión UNO."""

        settings = self.settings
        if not settings.enable_uno:
            return UnoHealth(available=False, message="UNO está deshabilitado (OFFICE_ENABLE_UNO=false)")

        try:
            self.get_connection()
            return UnoHealth(available=True, message="UNO disponible")
        except UnoPythonNotInstalledError as exc:
            return UnoHealth(available=False, message=str(exc))
        except UnoUnavailableError as exc:
            return UnoHealth(available=False, message=str(exc))


uno_client = UnoClient()

__all__ = [
    "UnoClient",
    "UnoHealth",
    "UnoUnavailableError",
    "UnoPythonNotInstalledError",
    "uno_client",
]
