# Nombre de archivo: health.py
# Ubicación de archivo: api/api_app/routes/health.py
# Descripción: Endpoints de health, versión de build y verificación de DB
from fastapi import APIRouter
from datetime import datetime, timezone
import os

from api.app.db import db_health

router = APIRouter()

@router.get("/health")
def health():
    base_response = {
        "status": "ok",
        "service": "api",
        "time": datetime.now(timezone.utc).isoformat(),
    }
    return {**base_response, **db_health()}

def _detect_build_version() -> str:
    # Preferir variables específicas y luego un fallback simple
    return (
        os.getenv("API_BUILD_VERSION")
        or os.getenv("BUILD_VERSION")
        or os.getenv("APP_VERSION")
        or "0.1.0"
    )

BUILD_VERSION = _detect_build_version()

@router.get("/health/version")
def health_version():
    return {"status": "ok", "service": "api", "version": BUILD_VERSION}

@router.get("/db-check")
def db_check():
    return db_health()
