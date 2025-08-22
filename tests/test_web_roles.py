# Nombre de archivo: test_web_roles.py
# Ubicación de archivo: tests/test_web_roles.py
# Descripción: Pruebas de permisos por rol en el servicio web

"""Valida que los roles admin y lector tengan permisos adecuados."""

from pathlib import Path
import importlib
import os
import sys

from fastapi.testclient import TestClient

# Agrega la ruta del módulo web al path de importación
sys.path.append(str(Path(__file__).resolve().parents[1] / "web"))


def get_client() -> TestClient:
    """Configura credenciales de prueba y retorna un cliente."""
    os.environ["WEB_ADMIN_USERNAME"] = "admin"
    os.environ["WEB_ADMIN_PASSWORD"] = "adminpass"
    os.environ["WEB_LECTOR_USERNAME"] = "lector"
    os.environ["WEB_LECTOR_PASSWORD"] = "lectpass"
    module = importlib.reload(importlib.import_module("main"))
    return TestClient(module.app)


def test_admin_access_allowed() -> None:
    """El usuario admin puede acceder al endpoint restringido."""
    client = get_client()
    response = client.get("/admin", auth=("admin", "adminpass"))
    assert response.status_code == 200
    assert response.json()["message"] == "Panel de administración"


def test_reader_access_denied() -> None:
    """El usuario lector no puede acceder al endpoint de admin."""
    client = get_client()
    response = client.get("/admin", auth=("lector", "lectpass"))
    assert response.status_code == 403
