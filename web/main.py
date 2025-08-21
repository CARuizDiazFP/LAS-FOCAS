# Nombre de archivo: main.py
# Ubicación de archivo: web/main.py
# Descripción: Servicio FastAPI básico para el módulo web

"""Módulo principal del servicio web de LAS-FOCAS."""

from fastapi import FastAPI
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web")

app = FastAPI(title="Servicio Web LAS-FOCAS")


@app.get("/health")
async def health() -> dict[str, str]:
    """Verifica que el servicio esté disponible."""
    logger.info("Chequeo de salud del servicio web")
    return {"status": "ok"}


@app.get("/")
async def read_root() -> dict[str, str]:
    """Retorna un mensaje inicial."""
    logger.info("Solicitud recibida en la ruta raíz")
    return {"message": "Hola desde el servicio web"}

