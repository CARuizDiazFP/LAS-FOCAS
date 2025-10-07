# Nombre de archivo: __init__.py
# Ubicación de archivo: modules/informes_repetitividad/__init__.py
# Descripción: Inicializa el paquete de informes de repetitividad

from .service import ReportResult, generate_report

__all__ = ["ReportResult", "generate_report"]
