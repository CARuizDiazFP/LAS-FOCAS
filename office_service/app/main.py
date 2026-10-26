# Nombre de archivo: main.py
# Ubicación de archivo: office_service/app/main.py
# Descripción: Punto de entrada FastAPI del microservicio LibreOffice/UNO

"""Aplicación FastAPI para exponer operaciones respaldadas por LibreOffice UNO."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import conversion
from .config import Settings, get_settings
from .uno_client import UnoHealth, uno_client

LOGGER = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Respuesta del endpoint de salud."""

    service: str = Field(..., description="Nombre lógico del servicio")
    uno: UnoHealth = Field(..., description="Estado del conector UNO")
    version: str = Field(..., description="Versión del microservicio")


_MEDIA_TYPES = {"pdf": "application/pdf"}


async def _leer_con_limite(file: UploadFile, limite: int) -> bytes:
    """Lee el upload por bloques y corta apenas supera `limite` bytes (no lo carga entero)."""

    partes: list[bytes] = []
    total = 0
    while bloque := await file.read(1024 * 1024):
        total += len(bloque)
        if total > limite:
            raise HTTPException(status_code=413, detail=f"El archivo supera el máximo de {limite} bytes")
        partes.append(bloque)
    return b"".join(partes)


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

    @app.post("/convert", tags=["conversions"], response_class=Response)
    async def convert_document(
        file: UploadFile,
        settings: Annotated[Settings, Depends(get_settings)],
        output_format: str = "pdf",
    ) -> Response:
        formato = output_format.lower()
        if formato not in conversion.FORMATOS_SALIDA:
            raise HTTPException(status_code=400, detail=f"Formato de salida no soportado: {output_format}")
        extension = Path(file.filename or "").suffix.lower()
        if extension not in conversion.EXTENSIONES_ENTRADA:
            raise HTTPException(
                status_code=400,
                detail=f"Extensión no soportada: {extension or '(sin extensión)'}; "
                f"se aceptan {', '.join(sorted(conversion.EXTENSIONES_ENTRADA))}",
            )
        if not Path(settings.soffice_binary).exists():
            raise HTTPException(status_code=503, detail="LibreOffice no está instalado en el servicio")

        contenido = await _leer_con_limite(file, settings.max_file_size)
        if not contenido:
            raise HTTPException(status_code=400, detail="El archivo está vacío")

        inicio = time.perf_counter()
        try:
            datos, nombre_salida = await conversion.convertir(
                contenido, file.filename or "documento", formato, settings.soffice_binary, settings.convert_timeout
            )
        except conversion.ConversionTimeout as exc:
            LOGGER.warning("action=convert_timeout filename=%s error=%s", file.filename, exc)
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except conversion.ConversionError as exc:
            LOGGER.warning("action=convert_error filename=%s error=%s", file.filename, exc)
            raise HTTPException(status_code=500, detail="La conversión falló") from exc
        LOGGER.info(
            "action=convert filename=%s output_format=%s bytes_in=%s bytes_out=%s duration_ms=%.0f",
            file.filename,
            formato,
            len(contenido),
            len(datos),
            (time.perf_counter() - inicio) * 1000,
        )
        return Response(
            content=datos,
            media_type=_MEDIA_TYPES[formato],
            headers={"Content-Disposition": f'attachment; filename="{nombre_salida}"'},
        )

    return app


app = create_app()

__all__ = ["app", "create_app"]
