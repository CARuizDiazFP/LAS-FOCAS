# Nombre de archivo: conftest.py
# Ubicación de archivo: tests/conftest.py
# Descripción: Configuraciones comunes para Pytest (ajuste de PYTHONPATH)

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:  # pragma: no cover - inicialización
    sys.path.insert(0, str(ROOT_DIR))
