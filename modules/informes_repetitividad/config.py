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
# Este diccionario se usa para normalizar las columnas de entrada a un formato estándar.
# Las claves son los nombres posibles en el Excel (en minúsculas y sin acentos normalizados por clean_key)
# y los valores son los nombres internos que usa el sistema.
#
# IMPORTANTE: Evitar mapear múltiples columnas al mismo destino para prevenir duplicados.
COLUMNAS_MAPPER: Dict[str, str] = {
    # Mapeos para CLIENTE
    "cliente": "CLIENTE",
    "nombre cliente": "CLIENTE",
    "nombre_cliente": "CLIENTE",
    "customer name": "CLIENTE",
    "nombre del cliente": "CLIENTE",

    # Mapeos para SERVICIO (identificador numérico del servicio/línea)
    "servicio": "SERVICIO",
    "numero linea": "SERVICIO",        # 'Número Línea' es el ID único del servicio
    "numero_linea": "SERVICIO",
    "numero de linea": "SERVICIO",

    # Mapeos para TIPO_SERVICIO (descripción del tipo, ej: "Internet Dedicado")
    "tipo servicio": "TIPO_SERVICIO",
    "tipo_servicio": "TIPO_SERVICIO",
    "service type": "TIPO_SERVICIO",
    "tipo de servicio": "TIPO_SERVICIO",

    # Mapeos para FECHA (priorizar fecha de cierre)
    "fecha": "FECHA",
    "fecha cierre reclamo": "FECHA",
    "fecha_cierre_reclamo": "FECHA",
    "fecha de cierre": "FECHA",
    "cierre reclamo": "FECHA",
    "date": "FECHA",

    # Mapeos alternativos para fecha (si no hay cierre, usar inicio)
    "fecha cierre problema reclamo": "FECHA_CIERRE_PROBLEMA",
    "fecha_cierre_problema_reclamo": "FECHA_CIERRE_PROBLEMA",
    "fecha inicio reclamo": "FECHA_INICIO",
    "fecha_inicio_reclamo": "FECHA_INICIO",

    # Mapeos para ID_SERVICIO (identificador de cada caso/reclamo)
    "id_servicio": "ID_SERVICIO",
    "numero reclamo": "ID_SERVICIO",   # 'Número Reclamo' es el ID de cada caso
    "numero_reclamo": "ID_SERVICIO",
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
