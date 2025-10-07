# Nombre de archivo: test_openai_mock.py
# Ubicación de archivo: nlp_intent/tests/test_openai_mock.py
# Descripción: Test que mockea el proveedor OpenAI para validar integración sin llamar a la API real

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))

import os

# Indicar modo testing para saltar validación de OPENAI_API_KEY al importar config
os.environ.setdefault("TESTING", "true")

from nlp_intent.app.service import classify_text, settings as svc_settings  # noqa: E402
from nlp_intent.app.schemas import IntentResponse  # noqa: E402


@dataclass
class _FakeResp:
    intent: str
    confidence: float
    provider: str
    normalized_text: str


def test_openai_provider_mock(monkeypatch):
    """Verifica que cuando LLM_PROVIDER=openai el flujo retorna el IntentResponse del mock.

    No se realizan llamadas externas: se monkeypatchea la función openai_provider.classify
    devolviendo un IntentResponse determinista.
    """

    # Forzar provider openai y setear key dummy para pasar validación.
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")

    # Import tardío para que lea las env vars correctas (el settings de config se evalúa al importar).
    from nlp_intent.app.providers import openai_provider  # noqa: WPS433,E402

    svc_settings.llm_provider = "openai"

    async def _fake_classify(text: str, normalized: str):
        return IntentResponse(intent="Consulta", confidence=0.88, provider="openai", normalized_text=normalized)

    monkeypatch.setattr(openai_provider, "classify", _fake_classify)

    # Ejecutar clasificación
    resp = asyncio.run(classify_text("¿Cómo genero el informe de repetitividad?"))
    assert resp.intent == "Consulta"
    assert resp.provider == "openai"
    assert resp.confidence == 0.88
    assert "repetitividad" in resp.normalized_text
