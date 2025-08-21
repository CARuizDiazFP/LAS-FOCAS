# Nombre de archivo: main.py
# Ubicación de archivo: nlp_intent/app/main.py
# Descripción: Servidor FastAPI para clasificación de intención de mensajes

from __future__ import annotations

from fastapi import FastAPI

from .schemas import IntentRequest, IntentResponse
from .service import classify_text

app = FastAPI(title="nlp_intent")


@app.post("/v1/intent:classify", response_model=IntentResponse)
async def classify_endpoint(req: IntentRequest) -> IntentResponse:
    """Clasifica el texto recibido en una intención."""
    return await classify_text(req.text)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


