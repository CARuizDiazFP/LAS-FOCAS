# Nombre de archivo: openai_provider.py
# Ubicación de archivo: nlp_intent/app/providers/openai_provider.py
# Descripción: Cliente para clasificar intención usando la API de OpenAI

from __future__ import annotations

import httpx
import orjson

from ..config import settings
from ..schemas import IntentResponse

SYSTEM_PROMPT = (
    "Sos un clasificador de intenciones para un asistente operacional. "
    "Clasificá el mensaje del usuario en exactamente una de: Consulta, Acción, Otros. "
    "'Otros' incluye saludos, agradecimientos o texto que no encaje claramente en las demás categorías. "
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


async def clarify_question(text: str, normalized_text: str) -> str:
    """Genera una pregunta breve pidiendo aclaración sobre un mensaje ambiguo.

    Reutiliza el mismo modelo con un prompt minimalista para controlar costos.
    """
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    prompt = (
        "El siguiente mensaje es poco claro o genérico. "
        "Escribí UNA sola pregunta breve y amable en español para pedir aclaración, sin añadir contexto adicional.\n"
        f"Mensaje: '{text}'.\nPregunta:"  # El modelo completa la pregunta
    )
    payload = {
        "model": "gpt-3.5-turbo",
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "Generás preguntas aclaratorias breves (<=15 palabras)."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 60,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
    # Sanitizar saltos / espacios
    return " ".join(content.split())


