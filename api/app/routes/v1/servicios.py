# Nombre de archivo: servicios.py
# Ubicación de archivo: api/app/routes/v1/servicios.py
# Descripción: API v1 de Servicios para integraciones interáreas: Botellas de FO por las que pasa un servicio

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.oauth import SCOPE_SERVICIOS_BOTELLAS, ClienteAutenticado, require_oauth_token
from core.services.servicio_botellas import botellas_de_servicio, resolver_servicio_por_identificador
from db.session import get_async_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/servicios", tags=["v1"])


class ServicioBotellasResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    servicio_consultado: str
    servicio_id_vigente: str
    es_id_vigente: bool
    total_botellas: int
    botellas: list[str]
    orden_fuente: Literal["traza_cromo", "traza_legada", "inventario", "sin_datos"]


@router.get(
    "/{servicio_id}/botellas",
    response_model=ServicioBotellasResponse,
    responses={404: {"description": "Servicio no encontrado"}},
)
async def botellas_del_servicio(
    servicio_id: str = Path(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"),
    cliente: ClienteAutenticado = Depends(require_oauth_token(SCOPE_SERVICIOS_BOTELLAS)),
    db: AsyncSession = Depends(get_async_db),
) -> ServicioBotellasResponse:
    """Botellas de fibra óptica por las que tributa un servicio, consultado por ID vigente o histórico."""

    resuelto = await resolver_servicio_por_identificador(db, servicio_id)
    if resuelto is None:
        logger.info("action=api_v1_botellas client_id=%s servicio=%s resultado=no_encontrado", cliente.client_id, servicio_id)
        raise HTTPException(status_code=404, detail="Servicio no encontrado")

    resultado = await botellas_de_servicio(db, resuelto.servicio.id)
    logger.info(
        "action=api_v1_botellas client_id=%s servicio=%s vigente=%s fuente=%s total=%s",
        cliente.client_id,
        servicio_id,
        resuelto.servicio.servicio_id,
        resultado.orden_fuente,
        len(resultado.nombres),
    )
    return ServicioBotellasResponse(
        servicio_consultado=servicio_id,
        servicio_id_vigente=resuelto.servicio.servicio_id,
        es_id_vigente=resuelto.es_id_vigente,
        total_botellas=len(resultado.nombres),
        botellas=resultado.nombres,
        orden_fuente=resultado.orden_fuente,
    )
