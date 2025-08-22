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


def get_client(username: str, password: str) -> TestClient:
    """Crea un cliente de pruebas con credenciales específicas."""
    os.environ["WEB_USERNAME"] = username
    os.environ["WEB_PASSWORD"] = password
    module = importlib.reload(importlib.import_module("main"))
    return TestClient(module.app)


def test_denied_without_credentials() -> None:
    """El acceso sin credenciales debe ser rechazado."""
    client = get_client("user", "pass")
    response = client.get("/")
    assert response.status_code == 401


def test_authorized_access() -> None:
    """Con credenciales válidas se permite el acceso."""
    client = get_client("user", "pass")
    response = client.get("/", auth=("user", "pass"))
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Hola desde el servicio web"


def test_denied_with_invalid_credentials() -> None:
    """El uso de credenciales incorrectas devuelve 401."""
    client = get_client("user", "pass")
    response = client.get("/", auth=("user", "wrong"))
    assert response.status_code == 401

