# Nombre de archivo: __init__.py
# Ubicación de archivo: modules/informes_repetitividad/__init__.py
# Descripción: Inicializa el paquete de informes de repetitividad

from .service import ReportConfig, ReportResult, generar_informe_desde_excel

__all__ = ["ReportConfig", "ReportResult", "generar_informe_desde_excel"]
