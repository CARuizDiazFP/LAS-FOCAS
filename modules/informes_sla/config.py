# Nombre de archivo: config.py
# Ubicación de archivo: modules/informes_sla/config.py
# Descripción: Configuración y constantes para el informe de SLA

from pathlib import Path
from typing import Dict, List

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

# Directorios de trabajo dentro del contenedor del bot
BASE_UPLOADS = Path("/app/data/uploads")
BASE_REPORTS = Path("/app/data/reports")
