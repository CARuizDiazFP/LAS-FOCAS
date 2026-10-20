# Nombre de archivo: conftest.py
# Ubicación de archivo: tests/conftest.py
# Descripción: Configuraciones comunes para Pytest (ajuste de PYTHONPATH)

from __future__ import annotations

import sys
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:  # pragma: no cover - inicialización
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("LAS_FOCAS_API_KEY", "test-api-key")


# Directorio ignorado por Git donde la app escribe informes reales; los tests no deben dejar nada ahí.
_REPORTES_VIGILADOS = ROOT_DIR / "web" / "data" / "reports"
_snapshot_reportes: set[str] = set()


def _listar_reportes() -> set[str]:
    if not _REPORTES_VIGILADOS.is_dir():
        return set()
    return {str(p.relative_to(_REPORTES_VIGILADOS)) for p in _REPORTES_VIGILADOS.rglob("*") if p.is_file()}


def pytest_sessionstart(session) -> None:
    """Toma el snapshot inicial de los archivos de informes."""
    global _snapshot_reportes
    _snapshot_reportes = _listar_reportes()


def pytest_sessionfinish(session, exitstatus) -> None:
    """Falla la sesión si los tests dejaron archivos nuevos en web/data/reports (no borra nada)."""
    nuevos = sorted(_listar_reportes() - _snapshot_reportes)
    if not nuevos:
        return
    print("\nLos tests dejaron archivos en web/data/reports/ (deben usar tmp_path):")
    for ruta in nuevos:
        print(f"  - {ruta}")
    session.exitstatus = 1
