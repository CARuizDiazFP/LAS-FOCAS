# Nombre de archivo: test_config_endpoint.py
# Ubicación de archivo: nlp_intent/tests/test_config_endpoint.py
# Descripción: Pruebas para el endpoint /config del servicio de NLP

import asyncio
import pathlib
import sys

from httpx import AsyncClient, ASGITransport

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from nlp_intent.app.main import app
from nlp_intent.app.config import settings


def test_config_get_y_post() -> None:
    original = settings.llm_provider

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/config")
            assert resp.status_code == 200
            assert resp.json() == {"llm_provider": original}

            nuevo = "heuristic" if original != "heuristic" else "openai"
            resp = await client.post("/config", json={"llm_provider": nuevo})
            assert resp.status_code == 200
            assert resp.json() == {"llm_provider": nuevo}

            resp = await client.get("/config")
            assert resp.json() == {"llm_provider": nuevo}

    asyncio.run(_run())
    settings.llm_provider = original
