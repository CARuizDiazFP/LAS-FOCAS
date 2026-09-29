# Nombre de archivo: servicios.py
# Ubicación de archivo: api/app/routes/v1/servicios.py
# Descripción: API v1 de Servicios para integraciones interáreas: Botellas, Cables y ODF por las que pasa un servicio

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.oauth import SCOPE_SERVICIOS, ClienteAutenticado, require_oauth_token
from core.services.servicio_traza import (
    ServicioResuelto,
    botellas_de_servicio,
    cables_de_servicio,
    odfs_de_servicio,
    resolver_servicio_por_identificador,
)
from db.session import get_async_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/servicios", tags=["v1"])

OrdenFuente = Literal["traza_cromo", "traza_legada", "inventario", "sin_datos"]
_RESPUESTAS_404 = {404: {"description": "Servicio no encontrado"}}
_PATRON_ID = r"^[A-Za-z0-9._-]+$"


class _ServicioConsultado(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    servicio_consultado: str
    servicio_id_vigente: str
    es_id_vigente: bool


class ServicioBotellasResponse(_ServicioConsultado):
    total_botellas: int
    botellas: list[str]
    orden_fuente: OrdenFuente


class ServicioCablesResponse(_ServicioConsultado):
    total_cables: int
    cables: list[str]
    orden_fuente: OrdenFuente


class PosicionOdfModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bandeja: Optional[str]
    conector: Optional[str]
    pelo: Optional[str]


class OdfModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    odf_id: int
    nombre: Optional[str]
    direccion: Optional[str]
    localidad: Optional[str]
    posiciones: list[PosicionOdfModel]


class ServicioOdfsResponse(_ServicioConsultado):
    fuente: Literal["cromo"] = "cromo"
    total_odfs: int
    odfs: list[OdfModel]


def _identificador() -> str:
    return Path(..., alias="servicio_id", min_length=1, max_length=64, pattern=_PATRON_ID)


async def _resolver_o_404(db: AsyncSession, servicio_id: str, cliente: ClienteAutenticado, recurso: str) -> ServicioResuelto:
    resuelto = await resolver_servicio_por_identificador(db, servicio_id)
    if resuelto is None:
        logger.info(
            "action=api_v1_%s client_id=%s servicio=%s resultado=no_encontrado", recurso, cliente.client_id, servicio_id
        )
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    return resuelto


def _cabecera(servicio_id: str, resuelto: ServicioResuelto) -> dict:
    return {
        "servicio_consultado": servicio_id,
        "servicio_id_vigente": resuelto.servicio.servicio_id,
        "es_id_vigente": resuelto.es_id_vigente,
    }


@router.get("/{servicio_id}/botellas", response_model=ServicioBotellasResponse, responses=_RESPUESTAS_404)
async def botellas_del_servicio(
    servicio_id: str = _identificador(),
    cliente: ClienteAutenticado = Depends(require_oauth_token(SCOPE_SERVICIOS)),
    db: AsyncSession = Depends(get_async_db),
) -> ServicioBotellasResponse:
    """Botellas de fibra óptica por las que tributa un servicio, consultado por ID vigente o histórico."""

    resuelto = await _resolver_o_404(db, servicio_id, cliente, "botellas")
    resultado = await botellas_de_servicio(db, resuelto.servicio.id)
    logger.info(
        "action=api_v1_botellas client_id=%s servicio=%s vigente=%s fuente=%s total=%s",
        cliente.client_id, servicio_id, resuelto.servicio.servicio_id, resultado.orden_fuente, len(resultado.nombres),
    )
    return ServicioBotellasResponse(
        **_cabecera(servicio_id, resuelto),
        total_botellas=len(resultado.nombres),
        botellas=resultado.nombres,
        orden_fuente=resultado.orden_fuente,
    )


@router.get("/{servicio_id}/cables", response_model=ServicioCablesResponse, responses=_RESPUESTAS_404)
async def cables_del_servicio(
    servicio_id: str = _identificador(),
    cliente: ClienteAutenticado = Depends(require_oauth_token(SCOPE_SERVICIOS)),
    db: AsyncSession = Depends(get_async_db),
) -> ServicioCablesResponse:
    """Cables de fibra óptica por los que tributa un servicio, en orden de traza cuando se conoce."""

    resuelto = await _resolver_o_404(db, servicio_id, cliente, "cables")
    resultado = await cables_de_servicio(db, resuelto.servicio.id)
    logger.info(
        "action=api_v1_cables client_id=%s servicio=%s vigente=%s fuente=%s total=%s",
        cliente.client_id, servicio_id, resuelto.servicio.servicio_id, resultado.orden_fuente, len(resultado.nombres),
    )
    return ServicioCablesResponse(
        **_cabecera(servicio_id, resuelto),
        total_cables=len(resultado.nombres),
        cables=resultado.nombres,
        orden_fuente=resultado.orden_fuente,
    )


@router.get("/{servicio_id}/odfs", response_model=ServicioOdfsResponse, responses=_RESPUESTAS_404)
async def odfs_del_servicio(
    servicio_id: str = _identificador(),
    cliente: ClienteAutenticado = Depends(require_oauth_token(SCOPE_SERVICIOS)),
    db: AsyncSession = Depends(get_async_db),
) -> ServicioOdfsResponse:
    """ODF de Cromo del servicio, con la bandeja y el conector que ocupa en cada una."""

    resuelto = await _resolver_o_404(db, servicio_id, cliente, "odfs")
    odfs = await odfs_de_servicio(db, resuelto.servicio)
    logger.info(
        "action=api_v1_odfs client_id=%s servicio=%s vigente=%s total=%s",
        cliente.client_id, servicio_id, resuelto.servicio.servicio_id, len(odfs),
    )
    return ServicioOdfsResponse(
        **_cabecera(servicio_id, resuelto),
        total_odfs=len(odfs),
        odfs=[
            OdfModel(
                odf_id=o.odf_n_id,
                nombre=o.nombre,
                direccion=o.direccion,
                localidad=o.localidad,
                posiciones=[PosicionOdfModel(bandeja=p.bandeja, conector=p.conector, pelo=p.pelo) for p in o.posiciones],
            )
            for o in odfs
        ],
    )
