# Nombre de archivo: main.py
# Ubicación de archivo: api/app/main.py
# Descripción: Aplicación FastAPI principal con limitación de tasa

from fastapi import FastAPI
import os
from slowapi.middleware import SlowAPIMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.routes.health import router as health_router


def create_app() -> FastAPI:
    """Crea la instancia principal de FastAPI y aplica rate limiting."""
    rate_limit = os.getenv("API_RATE_LIMIT", "60/minute")
    limiter = Limiter(key_func=get_remote_address, default_limits=[rate_limit])

    app = FastAPI(title="LAS-FOCAS API", version="0.1.0")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(health_router, tags=["health"])
    return app


app = create_app()
