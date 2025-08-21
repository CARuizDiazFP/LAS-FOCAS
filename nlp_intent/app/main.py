# Nombre de archivo: main.py
# Ubicación de archivo: nlp_intent/app/main.py
# Descripción: Servidor FastAPI para clasificación de intención con limitación de tasa


from fastapi import FastAPI, Request
import os
from slowapi.middleware import SlowAPIMiddleware
import time
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .schemas import IntentRequest, IntentResponse
from .service import classify_text
from .metrics import metrics
from core.logging import configure_logging
from core.middlewares import RequestIDMiddleware

configure_logging("nlp_intent")

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="nlp_intent")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestIDMiddleware)


@app.middleware("http")
async def collect_metrics(request: Request, call_next):
    """Middleware para recolectar métricas básicas de latencia."""
    inicio = time.perf_counter()
    response = await call_next(request)
    if request.url.path == "/v1/intent:classify":
        metrics.record(time.perf_counter() - inicio)
    return response


@app.post("/v1/intent:classify", response_model=IntentResponse)
@limiter.limit(os.getenv("NLP_RATE_LIMIT", "60/minute"))
async def classify_endpoint(request: Request, req: IntentRequest) -> IntentResponse:
    """Clasifica el texto recibido en una intención."""
    return await classify_text(req.text)


@app.get("/metrics")
async def metrics_endpoint() -> dict[str, float]:
    """Devuelve métricas básicas del servicio."""
    return metrics.snapshot()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
