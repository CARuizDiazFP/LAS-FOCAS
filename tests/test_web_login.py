# Nombre de archivo: test_web_login.py
# Ubicación de archivo: tests/test_web_login.py
# Descripción: Pruebas de la ruta /login en el servicio web

"""Verifica que la ruta /login responda sin autenticación."""

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


def test_login_accessible_without_auth() -> None:
    """La ruta /login debe estar disponible sin credenciales."""
    client = get_client()
    response = client.get("/login")
    assert response.status_code == 200
    assert "Formulario de login pendiente" in response.text
