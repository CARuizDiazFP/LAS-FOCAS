# Nombre de archivo: __init__.py
# Ubicación de archivo: core/sla/__init__.py
# Descripción: Punto de entrada del módulo SLA (exports públicos)
"""Funciones públicas del módulo SLA."""

from .parser import cargar_fuente_excel
from .engine import calcular_sla
from .report import generar_documento
from .preview import construir_preview

__all__ = [
    "cargar_fuente_excel",
    "calcular_sla",
    "generar_documento",
    "construir_preview",
]
