# Nombre de archivo: __init__.py
# Ubicación de archivo: office_service/app/__init__.py
# Descripción: Inicializa el paquete de la aplicación FastAPI del servicio LibreOffice

"""Aplicación FastAPI para exponer capacidades UNO/LibreOffice."""

from .main import create_app

__all__ = ["create_app"]
