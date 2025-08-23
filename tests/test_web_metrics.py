# Nombre de archivo: test_web_metrics.py
# Ubicación de archivo: tests/test_web_metrics.py
# Descripción: Pruebas del endpoint /metrics del servicio web

from pathlib import Path
import importlib
import os
import sys

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[1] / "web"))


def get_client() -> TestClient:
    os.environ["WEB_ADMIN_USERNAME"] = "user"
    os.environ["WEB_ADMIN_PASSWORD"] = "pass"
    module = importlib.reload(importlib.import_module("main"))
    return TestClient(module.app)


def test_metrics_endpoint_devuelve_datos() -> None:
    client = get_client()
    client.get("/health")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_requests" in data
    assert "average_latency_ms" in data
