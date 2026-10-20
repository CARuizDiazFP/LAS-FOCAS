# Nombre de archivo: main.py
# Ubicación de archivo: web/app/main.py
# Descripción: Aplicación FastAPI para la UI (página dark, barra y chat REST)

from __future__ import annotations

import asyncio  # noqa: F401  (los tests parchean web_main.asyncio.to_thread)
import os
from dataclasses import dataclass
from typing import Any, List

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from core.config import get_secret
from core.logging import setup_logging
from web.admin_ws import mount_admin_websocket
from web.fo_monitor_routes import mount_fo_monitor_routes
from web.chat_ws import ChatWebSocketSettings, mount_chat_websocket
import psycopg  # noqa: F401  (los tests parchean web_main.psycopg.connect)
from pathlib import Path

from .routers import admin_datos, camaras, chat, cromo, servicios, sesion
from .comun import (
    BASE_DIR,
    BUILD_VERSION,
    DB_DSN,
    REPORTS_DIR,
    UPLOADS_DIR,
    _env_int,
)

# Configuración básica
NLP_INTENT_URL = os.getenv("NLP_INTENT_URL", "http://nlp_intent:8100")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOGS_ROOT = Path(os.getenv("LOGS_DIR", str(Path(__file__).resolve().parents[2] / "Logs")))
logger = setup_logging("web", LOG_LEVEL, enable_file=True, logs_dir=LOGS_ROOT, filename="web.log")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


WEB_SESSION_HTTPS_ONLY = _env_bool("WEB_SESSION_HTTPS_ONLY", False)
WEB_SESSION_MAX_AGE = _env_int("WEB_SESSION_MAX_AGE", 60 * 60 * 8)


def _session_middleware_options() -> dict[str, Any]:
    return {
        "secret_key": get_secret("web_secret_key_v1", "WEB_SECRET_KEY", "cambiar_por_clave_web_segura"),
        "https_only": WEB_SESSION_HTTPS_ONLY,
        "same_site": "lax",
        "max_age": WEB_SESSION_MAX_AGE,
    }

app = FastAPI(title="LAS-FOCAS Web UI", version=BUILD_VERSION)
app.add_middleware(
    SessionMiddleware,
    **_session_middleware_options(),
)

# Middleware de trazabilidad de requests (ayuda a depurar ERR_INVALID_HTTP_RESPONSE en navegador)
@app.middleware("http")
async def log_requests(request, call_next):  # type: ignore
    try:
        logger.debug("action=request_start path=%s client=%s", request.url.path, request.client.host if request.client else "?")
    except Exception:  # noqa: BLE001
        pass
    try:
        response = await call_next(request)
        logger.debug(
            "action=request_end path=%s status=%s len=%s", request.url.path, getattr(response, "status_code", "?"), getattr(response, "body", None) and len(getattr(response, "body"))
        )
        return response
    except Exception as exc:  # noqa: BLE001
        logger.exception("action=request_error path=%s error=%s", getattr(request, 'url', '?'), exc)
        raise

# Rutas absolutas a static/templates basadas en la ubicación de este archivo (web/app/main.py)
DIST_DIR = BASE_DIR / "frontend" / "dist"
SPA_INDEX = DIST_DIR / "index.html"
DEFAULT_TEMPLATES_PATH = Path(__file__).resolve().parents[2] / "Templates"
TEMPLATES_ROOT = os.getenv("TEMPLATES_DIR", str(DEFAULT_TEMPLATES_PATH))
# Variables de entorno para que los módulos de informes respeten rutas
os.environ.setdefault("UPLOADS_DIR", str(UPLOADS_DIR))
os.environ.setdefault("REPORTS_DIR", str(REPORTS_DIR))
os.environ.setdefault("TEMPLATES_DIR", TEMPLATES_ROOT)

# Importar servicio de informes después de setear variables de entorno
from .routers import informes  # noqa: E402

# Montar assets del build Vite si existen
_vite_assets = DIST_DIR / "assets"
if _vite_assets.exists():
    app.mount("/assets", StaticFiles(directory=str(_vite_assets)), name="vite-assets")
app.mount("/reports", StaticFiles(directory=str(informes._mount_reports)), name="reports")


def _parse_allowed_origins(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


CHAT_ALLOWED_ORIGINS = _parse_allowed_origins(os.getenv("WEB_CHAT_ALLOWED_ORIGINS"))
if not CHAT_ALLOWED_ORIGINS:
    inferred_origin = os.getenv("WEB_INFERRED_ORIGIN")
    if inferred_origin:
        CHAT_ALLOWED_ORIGINS = [inferred_origin]

mount_chat_websocket(
    app,
    settings=ChatWebSocketSettings(
        dsn=DB_DSN,
        allowed_origins=CHAT_ALLOWED_ORIGINS,
        uploads_dir=str(UPLOADS_DIR),
    ),
    logger=logger,
)
mount_admin_websocket(app, allowed_origins=CHAT_ALLOWED_ORIGINS, logger=logger)
mount_fo_monitor_routes(app)


@dataclass
class IntentResponse:
    intent: str
    confidence: float
    provider: str
    normalized_text: str


async def classify_text(text: str) -> IntentResponse:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{NLP_INTENT_URL}/v1/intent:classify", json={"text": text}
        )
        resp.raise_for_status()
        data = resp.json()
        return IntentResponse(**data)


# =============================================================================
# TRACKING V2: ANÁLISIS Y RESOLUCIÓN INTELIGENTE
# =============================================================================


# ── Routers por dominio (antes del catch-all SPA) ───────────────────
app.include_router(sesion.router)
app.include_router(informes.router)
app.include_router(chat.router)
app.include_router(admin_datos.router)
app.include_router(servicios.router)
app.include_router(cromo.router)
app.include_router(camaras.router)


# ── SPA Catch-all (DEBE ser la última ruta) ─────────────────────────
# Devuelve el index.html del build Vite para todas las rutas no reconocidas.
# Esto permite que Vue Router maneje el routing del lado del cliente.
@app.get("/{path:path}")
async def spa_fallback(path: str) -> FileResponse:
    if SPA_INDEX.exists():
        return FileResponse(str(SPA_INDEX))
    return FileResponse(str(SPA_INDEX), status_code=404)
