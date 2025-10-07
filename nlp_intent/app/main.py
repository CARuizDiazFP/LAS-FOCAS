# Nombre de archivo: main.py
# Ubicación de archivo: nlp_intent/app/main.py
# Descripción: Servidor FastAPI para clasificación de intención de mensajes

from __future__ import annotations

from fastapi import FastAPI

from .schemas import IntentRequest, IntentResponse, IntentionResult
from .service import classify_text, analyze_intention

app = FastAPI(title="nlp_intent")


@app.post("/v1/intent:classify", response_model=IntentResponse, deprecated=True)
async def classify_endpoint(req: IntentRequest) -> IntentResponse:
    """(DEPRECADO) Clasifica el texto en la intención básica. Usar /v1/intent:analyze."""
    return await classify_text(req.text)


@app.post("/v1/intent:analyze", response_model=IntentionResult)
async def analyze_endpoint(req: IntentRequest) -> IntentionResult:
    """Analiza el texto y devuelve intención mapeada y posible pregunta de aclaración."""
    return await analyze_intention(req.text)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


