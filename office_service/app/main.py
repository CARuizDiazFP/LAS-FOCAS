# Nombre de archivo: main.py
# Ubicación de archivo: office_service/app/main.py
# Descripción: Punto de entrada FastAPI del microservicio LibreOffice/UNO

"""Aplicación FastAPI para exponer operaciones respaldadas por LibreOffice UNO."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .uno_client import UnoHealth, UnoUnavailableError, uno_client

LOGGER = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Respuesta del endpoint de salud."""

    service: str = Field(..., description="Nombre lógico del servicio")
    uno: UnoHealth = Field(..., description="Estado del conector UNO")
    version: str = Field(..., description="Versión del microservicio")


class ConvertRequest(BaseModel):
    """Payload para conversiones de documentos."""

    output_format: str = Field(..., description="Formato destino (ej. pdf, odt, docx)")


class ConvertResponse(BaseModel):
    """Respuesta placeholder para la conversión."""

    message: str
    output_path: Path | None = Field(default=None, description="Ruta del archivo generado")


def get_logger() -> logging.Logger:
    logger = logging.getLogger("office_service")
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s|%(name)s|%(message)s")
    return logger


def create_app() -> FastAPI:
    """Construye la instancia de FastAPI."""

    settings = get_settings()
    logger = get_logger()
    logger.setLevel(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Servicio LibreOffice/UNO iniciando...")
        try:
            yield
        finally:
            logger.info("Servicio LibreOffice/UNO finalizando...")

    app = FastAPI(
        title="LibreOffice UNO Service",
        version="0.1.0",
        docs_url=settings.docs_url,
        openapi_url=settings.openapi_url,
        default_response_class=JSONResponse,
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
        uno_health = uno_client.health()
        # Si se deshabilitó dinámicamente (modo degradado) ajustar mensaje
        if not settings.enable_uno and "deshabilitado" not in uno_health.message.lower():
            from .uno_client import UnoHealth  # import local para evitar ciclos
            uno_health = UnoHealth(available=False, message="UNO deshabilitado o no disponible (modo degradado)")
        return HealthResponse(service=settings.service_name, uno=uno_health, version=app.version)

    @app.post("/convert", response_model=ConvertResponse, tags=["conversions"])
    async def convert_document(
        info: ConvertRequest,
        file: UploadFile,
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> ConvertResponse:
        if not settings.enable_uno:
            raise HTTPException(status_code=503, detail="UNO deshabilitado; no se puede procesar la solicitud")

        try:
            uno_client.get_connection()
        except UnoUnavailableError as exc:
            raise HTTPException(status_code=503, detail=f"UNO no disponible: {exc}") from exc

        # TODO: Implementar conversión real utilizando UNO (ver docs/office_service.md)
        LOGGER.info(
            "Solicitud de conversión recibida: filename=%s output_format=%s",
            file.filename,
            info.output_format,
        )
        return ConvertResponse(
            message="Conversión aún no implementada; placeholder OK",
            output_path=None,
        )

    return app


app = create_app()

__all__ = ["app", "create_app"]
