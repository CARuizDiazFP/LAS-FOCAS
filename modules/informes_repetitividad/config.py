# Nombre de archivo: config.py
# Ubicación de archivo: modules/informes_repetitividad/config.py
# Descripción: Configuración y constantes para el informe de repetitividad

import os
from pathlib import Path
from typing import Dict, List, Optional

# Paths configurables mediante variables de entorno
TEMPLATES_DIR = Path(os.getenv("TEMPLATES_DIR", "/app/Templates"))
REP_TEMPLATE_PATH = Path(os.getenv("REP_TEMPLATE_PATH", TEMPLATES_DIR / "Plantilla_Informe_Repetitividad.docx"))
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "/app/data/reports"))
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "/app/data/uploads"))
SOFFICE_BIN: Optional[str] = os.getenv("SOFFICE_BIN")
MAPS_ENABLED: bool = os.getenv("MAPS_ENABLED", "false").lower() == "true"
MAPS_LIGHTWEIGHT: bool = os.getenv("MAPS_LIGHTWEIGHT", "true").lower() == "true"
REPORTS_API_BASE = os.getenv("REPORTS_API_BASE", "http://api:8000")
REPORTS_API_TIMEOUT = float(os.getenv("REPORTS_API_TIMEOUT", "60"))

# Alias para compatibilidad con otros módulos
BASE_UPLOADS = UPLOADS_DIR
BASE_REPORTS = REPORTS_DIR

# Mapeo de columnas esperadas en el Excel de casos
COLUMNAS_MAPPER: Dict[str, str] = {
    "CLIENTE": "CLIENTE",
    "SERVICIO": "SERVICIO",
    "ID_SERVICIO": "ID_SERVICIO",
    "FECHA": "FECHA",
}

# Columnas obligatorias para procesar el informe
COLUMNAS_OBLIGATORIAS: List[str] = [
    "CLIENTE",
    "SERVICIO",
    "FECHA",
]

# Clientes que nunca deben ser excluidos por filtros
CLIENTES_PRESERVAR: List[str] = ["BANCO MACRO SA"]

# Lista de meses en español para formatear encabezados
MESES_ES: List[str] = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
