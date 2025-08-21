# Nombre de archivo: test_failover.py
# Ubicación de archivo: nlp_intent/tests/test_failover.py
# Descripción: Verifica la degradación a heurística tras fallos consecutivos del proveedor

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from nlp_intent.app import service


def _classify(text: str):
    async def _run():
        return await service.classify_text(text)

    return asyncio.run(_run())


def test_openai_degrade(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    service.settings.llm_provider = "openai"
    service.cache.clear()
    service.failure_counts["openai"] = 0
    service.disabled_providers.clear()

    async def fake_classify(text: str, normalized: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(service.openai_provider, "classify", fake_classify)

    for i in range(service.MAX_PROVIDER_ERRORS):
        resp = _classify(f"hola {i}")
        assert resp.provider == "none"

    resp = _classify("hola final")
    assert resp.provider == "heuristic"
    assert "openai" in service.disabled_providers
