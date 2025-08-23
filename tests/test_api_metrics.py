# Nombre de archivo: test_api_metrics.py
# Ubicación de archivo: tests/test_api_metrics.py
# Descripción: Prueba del endpoint /metrics de la API principal

from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[1] / "api"))

from app.main import create_app


def test_metrics_endpoint_muestra_datos() -> None:
    app = create_app()
    client = TestClient(app)
    client.get("/health")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_requests" in data
    assert "average_latency_ms" in data
