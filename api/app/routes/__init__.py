# Nombre de archivo: __init__.py
# Ubicación de archivo: api/app/routes/__init__.py
# Descripción: Init del paquete routes

"""Configuración inicial del paquete de rutas de la API.

Se crea un objeto ``APIRouter`` que se utilizará para registrar y
agrupar todas las rutas del servicio.
"""

from fastapi import APIRouter

router = APIRouter()

__all__ = ["router"]