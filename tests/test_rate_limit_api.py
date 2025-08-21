# Nombre de archivo: test_rate_limit_api.py
# Ubicación de archivo: tests/test_rate_limit_api.py
# Descripción: Verifica la limitación de tasa en la API principal

from pathlib import Path
import os
import sys

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1] / "api"))
os.environ["API_RATE_LIMIT"] = "2/minute"

from app.main import create_app

app = create_app()
client = TestClient(app)


def test_api_rate_limit() -> None:
    """Tras dos solicitudes, la tercera debe ser rechazada."""
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    response = client.get("/health")
    assert response.status_code == 429
