# Nombre de archivo: conftest.py
# Ubicación de archivo: tests/conftest.py
# Descripción: Configuraciones comunes para Pytest (ajuste de PYTHONPATH)

from __future__ import annotations

import sys
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:  # pragma: no cover - inicialización
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("LAS_FOCAS_API_KEY", "test-api-key")
# web/app/main.py no arranca sin una clave de sesión real (fail-closed); ésta sólo existe en pytest.
os.environ.setdefault("WEB_SECRET_KEY", "test-web-secret-key-solo-para-pytest")

# Las métricas de intención se persisten en un archivo versionado (web/data/intent_metrics.json);
# se apunta a un directorio temporal ANTES de importar la app para no ensuciar el árbol del repo.
# Asignación directa: un valor heredado del entorno no debe apuntar al archivo versionado.
_METRICAS_TMP_DIR = tempfile.mkdtemp(prefix="focas-tests-")
os.environ["METRICS_PERSIST_PATH"] = os.path.join(_METRICAS_TMP_DIR, "intent_metrics.json")


# Directorio ignorado por Git donde la app escribe informes reales; los tests no deben dejar nada ahí.
_REPORTES_VIGILADOS = ROOT_DIR / "web" / "data" / "reports"
_snapshot_reportes: set[str] = set()
_snapshot_git_data: set[str] = set()


def _estado_git_web_data() -> set[str]:
    """Líneas de `git status --porcelain -- web/data` (archivos versionados modificados o nuevos)."""
    try:
        salida = subprocess.run(
            ["git", "status", "--porcelain", "--", "web/data"],
            cwd=ROOT_DIR, capture_output=True, text=True, timeout=30, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {linea for linea in salida.splitlines() if linea.strip()}


def _listar_reportes() -> set[str]:
    if not _REPORTES_VIGILADOS.is_dir():
        return set()
    return {str(p.relative_to(_REPORTES_VIGILADOS)) for p in _REPORTES_VIGILADOS.rglob("*") if p.is_file()}


def pytest_sessionstart(session) -> None:
    """Toma el snapshot inicial de los archivos de informes."""
    global _snapshot_reportes, _snapshot_git_data
    _snapshot_reportes = _listar_reportes()
    _snapshot_git_data = _estado_git_web_data()


def pytest_sessionfinish(session, exitstatus) -> None:
    """Falla la sesión si los tests ensuciaron web/data (informes nuevos o cambios git nuevos); no borra nada."""
    nuevos = sorted(_listar_reportes() - _snapshot_reportes)
    if nuevos:
        print("\nLos tests dejaron archivos en web/data/reports/ (deben usar tmp_path):")
        for ruta in nuevos:
            print(f"  - {ruta}")
    cambios = sorted(_estado_git_web_data() - _snapshot_git_data)
    if cambios:
        print("\nLos tests modificaron archivos bajo web/data (git status --porcelain):")
        for linea in cambios:
            print(f"  - {linea}")
    shutil.rmtree(_METRICAS_TMP_DIR, ignore_errors=True)
    if nuevos or cambios:
        session.exitstatus = 1


@pytest.fixture
def con_sesion():
    """Sesión simulada de la SPA vía `app.dependency_overrides`; ver `tests/soporte_sesion.py`.

    `con_sesion("admin")`, `con_sesion("user", username="pepe")` o `con_sesion(None)` (sin sesión).
    Los overrides se restauran al terminar el test, aunque falle.
    """
    from tests.soporte_sesion import sesion_simulada

    with sesion_simulada() as activar:
        yield activar


@pytest.fixture
def csrf_real(monkeypatch):
    """Reactiva la validación CSRF (`requiere_csrf` la saltea con `TESTING=true`).

    Exige una sesión real (login o cookie) con `username` y `csrf`: con `con_sesion` la cookie queda
    vacía y la dependencia no decide (sin usuario en sesión responde la autenticación).
    """
    monkeypatch.setenv("TESTING", "false")
