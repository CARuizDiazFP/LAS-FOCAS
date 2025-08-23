# Nombre de archivo: test_metrics.py
# Ubicación de archivo: nlp_intent/tests/test_metrics.py
# Descripción: Pruebas del endpoint de métricas del servicio

from __future__ import annotations

import asyncio
import pathlib
import sys

from httpx import AsyncClient, ASGITransport

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from nlp_intent.app.main import app
from nlp_intent.app.metrics import reset_metrics


def test_metrics_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "heuristic")
    reset_metrics()

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/v1/intent:classify", json={"text": "hola"})
            await client.post("/v1/intent:classify", json={"text": "chau"})
            resp = await client.get("/metrics")
        return resp

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    cuerpo = resp.text
    assert "nlp_intent_requests_total 2.0" in cuerpo
    assert "nlp_intent_request_latency_seconds" in cuerpo
