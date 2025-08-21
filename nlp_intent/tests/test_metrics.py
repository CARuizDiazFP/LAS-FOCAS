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
from nlp_intent.app.metrics import metrics


def test_metrics_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "heuristic")
    metrics.reset()

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/v1/intent:classify", json={"text": "hola"})
            await client.post("/v1/intent:classify", json={"text": "chau"})
            resp = await client.get("/metrics")
        return resp.json()

    datos = asyncio.run(_run())
    assert datos["total_requests"] == 2
    assert datos["average_latency_ms"] >= 0
