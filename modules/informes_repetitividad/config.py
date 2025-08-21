# Nombre de archivo: config.py
# Ubicación de archivo: modules/informes_repetitividad/config.py
# Descripción: Configuración y constantes para el informe de repetitividad

from pathlib import Path
from typing import Dict, List

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

# Directorios base de trabajo dentro del contenedor del bot
BASE_UPLOADS = Path("/app/data/uploads")
BASE_REPORTS = Path("/app/data/reports")
