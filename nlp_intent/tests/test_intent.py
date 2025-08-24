# Nombre de archivo: test_intent.py
# Ubicación de archivo: nlp_intent/tests/test_intent.py
# Descripción: Pruebas del clasificador de intención con dataset mínimo

from __future__ import annotations

import asyncio

import pathlib
import sys

from fastapi.testclient import TestClient

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from nlp_intent.app import service, main
from nlp_intent.app.schemas import IntentResponse

TEST_DATA = [
    ("hola", "Otros"),
    ("buen día", "Otros"),
    ("gracias", "Otros"),
    ("qué onda?", "Otros"),
    ("¿cómo genero el informe de repetitividad?", "Consulta"),
    ("qué es el comparador de FO?", "Consulta"),
    ("podés explicarme SLA?", "Consulta"),
    ("generá el informe SLA de julio", "Acción"),
    ("armá el reporte de repetitividad de agosto 2025", "Acción"),
    ("enviá el informe por correo", "Acción"),
    ("ejecutá el comparador FO contra archivo X", "Acción"),
    ("actualizá los datos", "Acción"),
]


def test_dataset_accuracy(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "heuristic")
    service.settings.llm_provider = "heuristic"
    service.cache.clear()
    service.disabled_providers.clear()
    service.failure_counts["openai"] = 0
    service.failure_counts["ollama"] = 0

    async def _run():
        hits = 0
        for text, expected in TEST_DATA:
            resp = await service.classify_text(text)
            if resp.intent == expected:
                hits += 1
        return hits / len(TEST_DATA)

    accuracy = asyncio.run(_run())
    assert accuracy >= 0.9


def test_config_endpoint_changes_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "heuristic")
    service.settings.llm_provider = "heuristic"
    service.cache.clear()
    service.disabled_providers.clear()
    service.failure_counts["openai"] = 0
    service.failure_counts["ollama"] = 0
    client = TestClient(main.app)

    resp = client.post("/config", json={"llm_provider": "heuristic"})
    assert resp.status_code == 200
    assert resp.json() == {"llm_provider": "heuristic"}

    resp = client.post("/v1/intent:classify", json={"text": "hola 1"})
    assert resp.json()["provider"] == "heuristic"

    async def fake_openai(text: str, normalized: str) -> IntentResponse:
        return IntentResponse(
            intent="Consulta",
            confidence=1.0,
            provider="openai",
            normalized_text=normalized,
        )

    monkeypatch.setattr(service.openai_provider, "classify", fake_openai)
    resp = client.post("/config", json={"llm_provider": "openai"})
    assert resp.status_code == 200
    service.cache.clear()
    resp = client.post("/v1/intent:classify", json={"text": "hola 2"})
    assert resp.json()["provider"] == "openai"
    main.limiter.reset()


