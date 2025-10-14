# Nombre de archivo: health.py
# Ubicación de archivo: api/api_app/routes/health.py
# Descripción: Endpoints de health y verificación de DB
from fastapi import APIRouter
from datetime import datetime, timezone

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

@router.get("/db-check")
def db_check():
    return db_health()
