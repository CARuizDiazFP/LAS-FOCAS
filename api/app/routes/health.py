# Nombre de archivo: health.py
# Ubicación de archivo: api/app/routes/health.py
# Descripción: Define la ruta de verificación del servicio

import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", summary="Verifica el estado del servicio")
def health_check() -> dict[str, str]:
    """Devuelve el estado básico del servicio."""
    logger.debug("Chequeo de salud solicitado")
    return {"status": "ok"}
