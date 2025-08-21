# Nombre de archivo: test_request_id.py
# Ubicación de archivo: tests/test_request_id.py
# Descripción: Verifica que los servicios FastAPI generen X-Request-ID

import uuid

from fastapi.testclient import TestClient

from api.app.main import app as api_app
from nlp_intent.app.main import app as nlp_app


def _assert_request_id(client: TestClient, path: str) -> None:
    resp = client.get(path)
    assert resp.status_code == 200
    header = resp.headers.get("X-Request-ID")
    assert header is not None
    uuid.UUID(header)


def test_request_id_api() -> None:
    client = TestClient(api_app)
    _assert_request_id(client, "/health")


def test_request_id_nlp_intent() -> None:
    client = TestClient(nlp_app)
    _assert_request_id(client, "/health")

