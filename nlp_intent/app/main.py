# Nombre de archivo: main.py
# Ubicación de archivo: nlp_intent/app/main.py
# Descripción: Servidor FastAPI para clasificación de intención con limitación de tasa


from fastapi import FastAPI, Request, Response
import os
from slowapi.middleware import SlowAPIMiddleware
import time
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import logging

from .schemas import IntentRequest, IntentResponse, ProviderConfig
from .service import classify_text
from .config import settings
from .metrics import (
    CONTENT_TYPE_LATEST,
    export_metrics,
    record_request,
)
from core.logging import configure_logging
from core.middlewares import RequestIDMiddleware

configure_logging("nlp_intent")
logger = logging.getLogger(__name__)

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
        record_request(time.perf_counter() - inicio)
    return response


@app.post("/v1/intent:classify", response_model=IntentResponse)
@limiter.limit(os.getenv("NLP_RATE_LIMIT", "60/minute"))
async def classify_endpoint(request: Request, req: IntentRequest) -> IntentResponse:
    """Clasifica el texto recibido en una intención."""
    return await classify_text(req.text)


@app.get("/config", response_model=ProviderConfig)
async def get_config() -> ProviderConfig:
    """Devuelve el proveedor LLM actualmente configurado."""
    return ProviderConfig(llm_provider=settings.llm_provider)


@app.post("/config", response_model=ProviderConfig)
async def set_config(cfg: ProviderConfig) -> ProviderConfig:
    """Actualiza el proveedor LLM en tiempo de ejecución."""
    settings.llm_provider = cfg.llm_provider
    logger.info("llm_provider_actualizado", extra={"llm_provider": cfg.llm_provider})
    return ProviderConfig(llm_provider=settings.llm_provider)


@app.get("/metrics")
async def metrics_endpoint() -> Response:
    """Exposición de métricas en formato Prometheus."""
    return Response(export_metrics(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
