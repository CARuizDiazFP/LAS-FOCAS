# Nombre de archivo: test_rate_limit.py
# Ubicación de archivo: nlp_intent/tests/test_rate_limit.py
# Descripción: Verifica la limitación de tasa en el microservicio nlp_intent

from __future__ import annotations

import os
import pathlib
import sys

from fastapi.testclient import TestClient

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
os.environ["NLP_RATE_LIMIT"] = "2/minute"

import importlib
from nlp_intent.app import main as main_module
importlib.reload(main_module)
app = main_module.app

client = TestClient(app)


def test_nlp_rate_limit() -> None:
    """Tras dos clasificaciones, la tercera debe ser rechazada."""
    payload = {"text": "hola"}
    assert client.post("/v1/intent:classify", json=payload).status_code == 200
    assert client.post("/v1/intent:classify", json=payload).status_code == 200
    response = client.post("/v1/intent:classify", json=payload)
    assert response.status_code == 429
