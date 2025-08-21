# Nombre de archivo: test_cache.py
# Ubicación de archivo: nlp_intent/tests/test_cache.py
# Descripción: Pruebas del uso de caché en classify_text

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from nlp_intent.app import service
from nlp_intent.app.providers import heuristic


def test_cache_hits(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "heuristic")
    service.cache.clear()
    llamadas = 0

    def falso_classify(texto: str):
        nonlocal llamadas
        llamadas += 1
        return ("Otros", 1.0)

    monkeypatch.setattr(heuristic, "classify", falso_classify)

    async def _run():
        await service.classify_text("hola")
        await service.classify_text("hola")

    asyncio.run(_run())
    assert llamadas == 1
