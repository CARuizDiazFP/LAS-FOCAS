# Nombre de archivo: cables.py
# Ubicación de archivo: api/app/routes/v1/cables.py
# Descripción: API v1 de Cables para integraciones interáreas: servicios que pasan por un cable y pelos por buffer

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.oauth import SCOPE_CABLES, ClienteAutenticado, require_oauth_token
from core.services.cable_consultas import (
    CableIdentificado,
    pelos_por_buffer,
    resolver_cable,
    servicios_de_cable,
)
from db.session import get_async_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/cables", tags=["v1"])

# El cable va por query string y no en el path: hay nombres reales con espacios y paréntesis
# ("F-VIN-JDG (a instalar)", 436 de 32.810 cables vigentes en dev el 2026-09-29). Se rechazan sólo
# caracteres de control.
_PATRON_CABLE = r"^[^\x00-\x1f\x7f]+$"


def _parametro_cable() -> str:
    return Query(
        ...,
        min_length=1,
        max_length=128,
        pattern=_PATRON_CABLE,
        description="Nombre exacto del cable (sin distinguir mayúsculas) o su n_id de Cromo.",
    )


class CableModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cable_id: int
    nombre: Optional[str]
    capacidad: Optional[str]
    extremo_a: Optional[str]
    extremo_b: Optional[str]


class ServicioEnCableModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    servicio_id: str
    cliente: Optional[str]
    estado_servicio: Optional[str]
    tipo_servicio: Optional[str]
    cantidad_pelos: int
    buffers: list[int]


class CableServiciosResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    cable: CableModel
    total_servicios: int
    servicios: list[ServicioEnCableModel]


class PeloModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numero: Optional[str]
    color: Optional[str]
    estado: Literal["ocupado", "libre"]
    servicio_id: Optional[str]
    cliente: Optional[str]
    estado_servicio: Optional[str]
    descripcion: Optional[str]


class BufferModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numero: Optional[int]
    color: Optional[str]
    total_pelos: int
    pelos_ocupados: int
    pelos: list[PeloModel]


class CablePelosResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    cable: CableModel
    total_buffers: int
    buffers: list[BufferModel]


class CableAmbiguoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["error"] = "error"
    detail: str
    candidatos: list[CableModel]


_RESPUESTAS = {
    404: {"description": "Cable (o buffer) no encontrado"},
    409: {"model": CableAmbiguoResponse, "description": "Más de un cable vigente con ese nombre: repetir con el cable_id"},
}


def _modelo_cable(c: CableIdentificado) -> CableModel:
    return CableModel(cable_id=c.n_id, nombre=c.nombre, capacidad=c.capacidad, extremo_a=c.extremo_a, extremo_b=c.extremo_b)


async def _resolver(db: AsyncSession, cable: str, cliente: ClienteAutenticado, recurso: str) -> CableIdentificado | JSONResponse:
    candidatos = await resolver_cable(db, cable)
    if not candidatos:
        logger.info("action=api_v1_%s client_id=%s cable=%r resultado=no_encontrado", recurso, cliente.client_id, cable)
        return JSONResponse({"detail": "Cable no encontrado"}, status_code=404)
    if len(candidatos) > 1:
        logger.info("action=api_v1_%s client_id=%s cable=%r resultado=ambiguo n=%s", recurso, cliente.client_id, cable, len(candidatos))
        return JSONResponse(
            CableAmbiguoResponse(
                detail="Hay más de un cable vigente con ese nombre; repetir la consulta con el cable_id.",
                candidatos=[_modelo_cable(c) for c in candidatos],
            ).model_dump(),
            status_code=409,
        )
    return candidatos[0]


@router.get("/servicios", response_model=CableServiciosResponse, responses=_RESPUESTAS)
async def servicios_del_cable(
    cable: str = _parametro_cable(),
    cliente: ClienteAutenticado = Depends(require_oauth_token(SCOPE_CABLES)),
    db: AsyncSession = Depends(get_async_db),
):
    """Servicios que pasan por un cable (uno por servicio, aunque ocupe varios pelos)."""

    resuelto = await _resolver(db, cable, cliente, "cable_servicios")
    if isinstance(resuelto, JSONResponse):
        return resuelto
    servicios = await servicios_de_cable(db, resuelto.n_id)
    logger.info(
        "action=api_v1_cable_servicios client_id=%s cable_id=%s total=%s", cliente.client_id, resuelto.n_id, len(servicios)
    )
    return CableServiciosResponse(
        cable=_modelo_cable(resuelto),
        total_servicios=len(servicios),
        servicios=[ServicioEnCableModel(**vars(s)) for s in servicios],
    )


@router.get("/pelos", response_model=CablePelosResponse, responses=_RESPUESTAS)
async def pelos_del_cable(
    cable: str = _parametro_cable(),
    buffer: Optional[int] = Query(None, ge=1, le=999, description="Número de buffer (1 = el primero). Omitir para todos."),
    cliente: ClienteAutenticado = Depends(require_oauth_token(SCOPE_CABLES)),
    db: AsyncSession = Depends(get_async_db),
):
    """Pelos de un cable agrupados por buffer, con el servicio que ocupa cada uno."""

    resuelto = await _resolver(db, cable, cliente, "cable_pelos")
    if isinstance(resuelto, JSONResponse):
        return resuelto
    buffers = await pelos_por_buffer(db, resuelto.n_id, buffer=buffer)
    if buffer is not None and not buffers:
        return JSONResponse({"detail": f"El cable no tiene buffer {buffer}"}, status_code=404)
    logger.info(
        "action=api_v1_cable_pelos client_id=%s cable_id=%s buffer=%s buffers=%s",
        cliente.client_id, resuelto.n_id, buffer, len(buffers),
    )
    return CablePelosResponse(
        cable=_modelo_cable(resuelto),
        total_buffers=len(buffers),
        buffers=[
            BufferModel(
                numero=b.numero,
                color=b.color,
                total_pelos=len(b.pelos),
                pelos_ocupados=sum(p.estado == "ocupado" for p in b.pelos),
                pelos=[PeloModel(**vars(p)) for p in b.pelos],
            )
            for b in buffers
        ],
    )
