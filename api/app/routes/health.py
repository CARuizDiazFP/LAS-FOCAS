# Nombre de archivo: health.py
# Ubicación de archivo: api/app/routes/health.py
# Descripción: Endpoints de health y verificación de DB
from fastapi import APIRouter
from datetime import datetime, timezone

from app.db import db_health

router = APIRouter()

@router.get("/health")
def health():
    return {
        "status": "ok",
        "service": "api",
        "time": datetime.now(timezone.utc).isoformat()
    }

@router.get("/db-check")
def db_check():
    return db_health()

