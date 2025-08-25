# Nombre de archivo: test_web_auth.py
# Ubicación de archivo: tests/test_web_auth.py
# Descripción: Pruebas para la autenticación básica del servicio web

"""Verifica el acceso al servicio web bajo autenticación básica."""

from pathlib import Path
import importlib
import os
import sys

from fastapi.testclient import TestClient

# Agrega la ruta del módulo web al path de importación
sys.path.append(str(Path(__file__).resolve().parents[1] / "web"))


def get_client(admin_user: str, admin_pass: str) -> TestClient:
    """Crea un cliente de pruebas con credenciales específicas."""
    os.environ["WEB_ADMIN_USERNAME"] = admin_user
    os.environ["WEB_ADMIN_PASSWORD"] = admin_pass
    os.environ["WEB_LECTOR_USERNAME"] = "lector"
    os.environ["WEB_LECTOR_PASSWORD"] = "lectura"
    module = importlib.reload(importlib.import_module("main"))
    return TestClient(module.app)


def test_redirect_without_credentials() -> None:
    """El acceso sin credenciales redirige al formulario de login."""
    client = get_client("user", "pass")
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/login"


def test_authorized_access() -> None:
    """Con credenciales válidas se permite el acceso."""
    client = get_client("user", "pass")
    response = client.get("/", auth=("user", "pass"))
    assert response.status_code == 200
    assert "Bienvenido" in response.text


def test_denied_with_invalid_credentials() -> None:
    """El uso de credenciales incorrectas devuelve 401."""
    client = get_client("user", "pass")
    response = client.get("/", auth=("user", "wrong"))
    assert response.status_code == 401


def test_redirect_on_malformed_header() -> None:
    """Un encabezado Authorization inválido redirige a /login."""
    client = get_client("user", "pass")
    response = client.get("/", headers={"Authorization": "Basic ???"}, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/login"

