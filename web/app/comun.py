# Nombre de archivo: comun.py
# Ubicación de archivo: web/app/comun.py
# Descripción: Helpers compartidos de la app web (auth, CSRF, configuración, rutas de datos, historial de informes)

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import HTTPException, Request, status

from core.config import get_secret
from core.services.report_history import ReportHistoryBackend, ReportHistoryService

# Mismo logger "web" que configura main.py con setup_logging("web", ...)
logger = logging.getLogger("web")

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")

# Config DB (usa las variables del .env del stack)
DB_HOST = os.getenv("POSTGRES_HOST", "postgres")
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
DB_NAME = os.getenv("POSTGRES_DB", "lasfocas")
DB_USER = os.getenv("POSTGRES_USER", "lasfocas")
DB_PASS = get_secret("db_password_v1", "POSTGRES_PASSWORD")
DB_DSN = f"dbname={DB_NAME} user={DB_USER} password={DB_PASS} host={DB_HOST} port={DB_PORT}"

# Rutas de datos basadas en la ubicación de este archivo (web/app/comun.py)
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
REPORTS_DIR = DATA_DIR / "reports"
DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

REPORT_HISTORY: ReportHistoryBackend = ReportHistoryService(DB_DSN)


def _internal_api_auth_headers() -> dict[str, str]:
    api_key = get_secret("api_key_v1", "LAS_FOCAS_API_KEY").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="API interna sin credenciales")
    return {
        "Authorization": f"Bearer {api_key}",
    }


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("action=config_invalid_int name=%s default=%s", name, default)
        return default


def get_current_user(request: Request) -> str | None:
    return request.session.get("username")


def _require_auth(request: Request) -> tuple[str, str]:
    username = request.session.get("username")
    role = request.session.get("role", "user")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return username, role


def _require_admin(request: Request) -> str:
    username, role = _require_auth(request)
    if role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permisos insuficientes")
    return username


def _validar_csrf(request: Request, token: str | None, accion: str, username: str) -> bool:
    """CSRF con el mismo criterio que el resto de los POST admin, incluida la excepción de tests."""
    if os.getenv("TESTING", "false").lower() == "true":
        return True
    esperado = request.session.get("csrf")
    if not token or token != esperado:
        logger.warning("action=%s result=fail reason=csrf user=%s", accion, username)
        return False
    return True
