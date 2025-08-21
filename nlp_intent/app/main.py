# Nombre de archivo: main.py
# Ubicación de archivo: nlp_intent/app/main.py
# Descripción: Servidor FastAPI para clasificación de intención de mensajes

from __future__ import annotations

from fastapi import FastAPI, Request
import time

from .schemas import IntentRequest, IntentResponse
from .service import classify_text
from .metrics import metrics

app = FastAPI(title="nlp_intent")


@app.middleware("http")
async def collect_metrics(request: Request, call_next):
    """Middleware para recolectar métricas básicas de latencia."""
    inicio = time.perf_counter()
    response = await call_next(request)
    if request.url.path == "/v1/intent:classify":
        metrics.record(time.perf_counter() - inicio)
    return response


@app.post("/v1/intent:classify", response_model=IntentResponse)
async def classify_endpoint(req: IntentRequest) -> IntentResponse:
    """Clasifica el texto recibido en una intención."""
    return await classify_text(req.text)


@app.get("/metrics")
async def metrics_endpoint() -> dict[str, float]:
    """Devuelve métricas básicas del servicio."""
    return metrics.snapshot()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
