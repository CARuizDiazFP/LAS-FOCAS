# Nombre de archivo: ollama_provider.py
# Ubicación de archivo: nlp_intent/app/providers/ollama_provider.py
# Descripción: Cliente para clasificar intención usando Ollama (modelo llama3)

from __future__ import annotations

import httpx
import orjson

from ..config import settings
from ..schemas import IntentResponse

PROMPT_TEMPLATE = (
    "Clasificá el mensaje del usuario en exactamente una de: Consulta, Acción, Otros. "
    'Devolvé solo JSON con: {"intent": "<Consulta|Acción|Otros>", '
    '"confidence": 0.xx, "provider": "ollama", "normalized_text": "<texto_normalizado>"}\n'
    "Ejemplos:\n"
    "Usuario: hola, ¿cómo va?\n"
    "Respuesta: {\"intent\": \"Otros\", \"confidence\": 0.9, \"provider\": \"ollama\", \"normalized_text\": \"hola, ¿cómo va?\"}\n"
    "Usuario: ¿cómo genero el reporte de repetitividad?\n"
    "Respuesta: {\"intent\": \"Consulta\", \"confidence\": 0.9, \"provider\": \"ollama\", \"normalized_text\": \"¿cómo genero el reporte de repetitividad?\"}\n"
    "Usuario: generá el reporte de repetitividad de agosto 2025\n"
    "Respuesta: {\"intent\": \"Acción\", \"confidence\": 0.9, \"provider\": \"ollama\", \"normalized_text\": \"generá el reporte de repetitividad de agosto 2025\"}\n"
    "Usuario: podés explicarme qué hace el comparador de FO?\n"
    "Respuesta: {\"intent\": \"Consulta\", \"confidence\": 0.9, \"provider\": \"ollama\", \"normalized_text\": \"podés explicarme qué hace el comparador de fo?\"}\n"
    "Usuario: armá el informe SLA de julio\n"
    "Respuesta: {\"intent\": \"Acción\", \"confidence\": 0.9, \"provider\": \"ollama\", \"normalized_text\": \"armá el informe sla de julio\"}\n"
    "Usuario: {user_text}\n"
    "Respuesta:"
)


async def classify(text: str, normalized_text: str) -> IntentResponse:
    payload = {"model": "llama3", "prompt": PROMPT_TEMPLATE.format(user_text=text), "options": {"temperature": 0}}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{settings.ollama_url}/api/generate", json=payload)
        resp.raise_for_status()
        raw = resp.json().get("response", "{}")
    data = orjson.loads(raw)
    data.setdefault("provider", "ollama")
    data.setdefault("normalized_text", normalized_text)
    return IntentResponse(**data)


