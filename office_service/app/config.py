# Nombre de archivo: config.py
# Ubicación de archivo: office_service/app/config.py
# Descripción: Configuración y settings del microservicio LibreOffice/UNO

"""Configuración central del microservicio LibreOffice/UNO."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Parámetros configurables del servicio."""

    service_name: str = Field(default="office-service", description="Nombre lógico del servicio")
    log_level: str = Field(default="INFO", description="Nivel de logging del servicio")
    enable_uno: bool = Field(default=True, description="Habilita la conexión real a LibreOffice UNO")
    soffice_host: str = Field(default="0.0.0.0", description="Host de escucha para LibreOffice UNO (modo accept)")
    soffice_connect_host: str = Field(
        default="127.0.0.1",
        description="Host utilizado por el cliente UNO para conectarse a LibreOffice",
    )
    soffice_port: int = Field(default=2002, description="Puerto de escucha para LibreOffice UNO")
    soffice_binary: str = Field(default="/usr/bin/soffice", description="Ruta al binario de LibreOffice")
    soffice_accept_string: str | None = Field(
        default=None,
        description="Cadena UNO ACCEPT personalizada; si no se define se arma con host/port",
    )
    soffice_health_timeout: float = Field(
        default=2.0,
        description="Timeout en segundos para verificar conexión UNO",
    )
    uvicorn_host: str = Field(default="0.0.0.0", description="Host de escucha para Uvicorn")
    uvicorn_port: int = Field(default=8090, description="Puerto HTTP del servicio")
    uvicorn_reload: bool = Field(default=False, description="Activa auto-reload (solo desarrollo)")
    metrics_enabled: bool = Field(default=False, description="Expone métricas Prometheus (TODO)")
    docs_url: Literal["/docs", None] = Field(default="/docs", description="Ruta de la documentación interactiva")
    openapi_url: str = Field(default="/openapi.json", description="Ruta del schema OpenAPI")
    external_base_url: HttpUrl | None = Field(default=None, description="URL externa para construir enlaces (opcional)")

    model_config = ConfigDict(env_prefix="OFFICE_", case_sensitive=False)

    @property
    def accept_descriptor(self) -> str:
        if self.soffice_accept_string:
            return self.soffice_accept_string
        return (
            f"socket,host={self.soffice_host},port={self.soffice_port};"
            "urp;StarOffice.ComponentContext"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna settings cacheados para reutilizar en el proyecto."""

    return Settings()


__all__ = ["Settings", "get_settings"]
