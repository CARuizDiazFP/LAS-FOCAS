# Nombre de archivo: config.py
# Ubicación de archivo: core/sla/config.py
# Descripción: Constantes y rutas para el módulo SLA
"""Configuración y constantes para el motor de SLA."""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from core.config import MESES_ES as _MESES_ES
from core.config import reports_dir, templates_dir, uploads_dir

# Rutas configurables (default único en core/config)
TEMPLATES_DIR = templates_dir()
SLA_TEMPLATE_PATH = Path(
    os.getenv("SLA_TEMPLATE_PATH", str(TEMPLATES_DIR / "Template_Informe_SLA.docx"))
)
REPORTS_DIR = reports_dir()
UPLOADS_DIR = uploads_dir()

# Configuración de zona horaria
DEFAULT_TZ = ZoneInfo(os.getenv("SLA_TIMEZONE", "America/Argentina/Buenos_Aires"))

# Parámetros de normalización
MERGE_GAP_MINUTES = int(os.getenv("SLA_MERGE_GAP_MINUTES", "15"))
MIN_DOWNTIME_MINUTES = int(os.getenv("SLA_MIN_DOWNTIME_MINUTES", "1"))

# Formato de meses para títulos
MESES_ES = list(_MESES_ES)