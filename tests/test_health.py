# Nombre de archivo: test_health.py
# Ubicación de archivo: tests/test_health.py
# Descripción: Pruebas para la ruta de health de la API

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "api"))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    """Verifica que el endpoint /health responde correctamente."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "api"
    assert "time" in data

