# Nombre de archivo: config.py
# Ubicación de archivo: core/sla/config.py
# Descripción: Constantes y rutas para el módulo SLA
"""Configuración y constantes para el motor de SLA."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TEMPLATES_DIR = _PROJECT_ROOT / "Templates"
_DEFAULT_REPORTS_DIR = _PROJECT_ROOT / "Reports"

# Rutas configurables
TEMPLATES_DIR = Path(os.getenv("TEMPLATES_DIR", str(_DEFAULT_TEMPLATES_DIR)))
SLA_TEMPLATE_PATH = Path(
    os.getenv("SLA_TEMPLATE_PATH", str(TEMPLATES_DIR / "Template_Informe_SLA.docx"))
)
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", str(_DEFAULT_REPORTS_DIR)))
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", str(_PROJECT_ROOT / "tmp")))
SOFFICE_BIN: Optional[str] = os.getenv("SOFFICE_BIN")

# Configuración de zona horaria
DEFAULT_TZ = ZoneInfo(os.getenv("SLA_TIMEZONE", "America/Argentina/Buenos_Aires"))

# Parámetros de normalización
MERGE_GAP_MINUTES = int(os.getenv("SLA_MERGE_GAP_MINUTES", "15"))
MIN_DOWNTIME_MINUTES = int(os.getenv("SLA_MIN_DOWNTIME_MINUTES", "1"))

# Formato de meses para títulos
MESES_ES = [
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