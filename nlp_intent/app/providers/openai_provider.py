# Nombre de archivo: openai_provider.py
# Ubicación de archivo: nlp_intent/app/providers/openai_provider.py
# Descripción: Cliente para clasificar intención usando la API de OpenAI

from __future__ import annotations

import httpx
import orjson

from ..config import settings
from ..schemas import IntentResponse

SYSTEM_PROMPT = (
    "Sos un clasificador de intenciones. "
    "Clasificá el mensaje del usuario en exactamente una de: Consulta, Acción, Otros. "
    'Devolvé solo JSON con: {"intent": "<Consulta|Acción|Otros>", "confidence": 0.xx, "provider": "openai", "normalized_text": "<texto_normalizado>"}'
)

FEW_SHOTS = [
    ("hola, ¿cómo va?", "Otros"),
    ("¿cómo genero el reporte de repetitividad?", "Consulta"),
    ("generá el reporte de repetitividad de agosto 2025", "Acción"),
    ("podés explicarme qué hace el comparador de FO?", "Consulta"),
    ("armá el informe SLA de julio", "Acción"),
]


async def classify(text: str, normalized_text: str) -> IntentResponse:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for sample, intent in FEW_SHOTS:
        messages.append({"role": "user", "content": sample})
        messages.append(
            {
                "role": "assistant",
                "content": orjson.dumps(
                    {
                        "intent": intent,
                        "confidence": 0.9,
                        "provider": "openai",
                        "normalized_text": sample,
                    }
                ).decode(),
            }
        )
    messages.append({"role": "user", "content": text})

    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    payload = {"model": "gpt-3.5-turbo", "temperature": 0, "messages": messages}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    data = orjson.loads(content)
    data.setdefault("provider", "openai")
    data.setdefault("normalized_text", normalized_text)
    return IntentResponse(**data)


