# Nombre de archivo: health.py
# Ubicación de archivo: api/app/routes/health.py
# Descripción: Endpoints de health y verificación de DB
from datetime import datetime, timezone
import logging

from fastapi import APIRouter

from app.db import db_health

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health():
    """Devuelve el estado básico del servicio."""
    logger.info("Verificación de estado solicitada")
    return {
        "status": "ok",
        "service": "api",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/db-check")
def db_check():
    """Verifica conectividad con la base de datos."""
    logger.info("Verificación de base de datos solicitada")
    return db_health()
