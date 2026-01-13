# Nombre de archivo: config.py
# Ubicación de archivo: modules/informes_sla/config.py
# Descripción: Configuración y constantes para el informe de SLA

import os
from pathlib import Path
from typing import Dict, List, Optional

# Paths configurables mediante variables de entorno
TEMPLATES_DIR = Path(os.getenv("TEMPLATES_DIR", "/app/Templates"))
SLA_TEMPLATE_PATH = Path(os.getenv("SLA_TEMPLATE_PATH", TEMPLATES_DIR / "Template_Informe_SLA.docx"))
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "/app/data/reports"))
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "/app/data/uploads"))
SOFFICE_BIN: Optional[str] = os.getenv("SOFFICE_BIN")

# Alias para compatibilidad con módulos existentes
BASE_UPLOADS = UPLOADS_DIR
BASE_REPORTS = REPORTS_DIR

# Mapeo de nombres de columnas crudas a nombres canónicos
COLUMNAS_MAPPER: Dict[str, str] = {
    "TicketID": "ID",
    "ID_TICKET": "ID",
    "Cliente": "CLIENTE",
    "CLIENTE": "CLIENTE",
    "Servicio": "SERVICIO",
    "SERVICIO": "SERVICIO",
    "Apertura": "FECHA_APERTURA",
    "Fecha Apertura": "FECHA_APERTURA",
    "FECHA_APERTURA": "FECHA_APERTURA",
    "Cierre": "FECHA_CIERRE",
    "Fecha Cierre": "FECHA_CIERRE",
    "FECHA_CIERRE": "FECHA_CIERRE",
    "SLA": "SLA_OBJETIVO_HORAS",
    "SLA_OBJETIVO_HORAS": "SLA_OBJETIVO_HORAS",
    # Columna P del Excel: Horas Netas Cierre Problema (tiempo de resolución en horas)
    "Horas Netas Cierre Problema": "TTR_h",
    "HORAS_NETAS_CIERRE_PROBLEMA": "TTR_h",
    "TTR_h": "TTR_h",
}

# Columnas obligatorias para el cálculo del SLA
COLUMNAS_OBLIGATORIAS: List[str] = [
    "ID",
    "CLIENTE",
    "SERVICIO",
    "FECHA_APERTURA",
    "FECHA_CIERRE",
]

# Valores de SLA objetivo por servicio
SLA_POR_SERVICIO: Dict[str, float] = {
    "Default": 24.0,
    "VIP": 12.0,
}

# Lista de meses en español para encabezados
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
