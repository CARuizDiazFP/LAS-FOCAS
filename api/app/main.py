# Nombre de archivo: main.py
# Ubicación de archivo: api/app/main.py
# Descripción: Aplicación FastAPI principal (incluye rutas de health)

import logging
from fastapi import FastAPI
from .routes.health import router as health_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Crea y configura la instancia principal de FastAPI."""
    logger.debug("Creando aplicación FastAPI")
    app = FastAPI(title="LAS-FOCAS API", version="0.1.0")
    app.include_router(health_router, tags=["health"])
    return app


app = create_app()
