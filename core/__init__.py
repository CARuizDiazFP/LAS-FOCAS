# Nombre de archivo: __init__.py
# Ubicación de archivo: core/__init__.py
# Descripción: Inicializa el paquete de utilidades centrales

"""Punto de entrada para utilidades compartidas del proyecto."""

from .secrets import get_secret

__all__ = ["get_secret"]
