# Nombre de archivo: infra.py
# Ubicación de archivo: api/api_app/routes/infra.py
# Descripción: Endpoint para sincronizar cámaras desde Google Sheets

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.services.infra_sync import sync_camaras_from_sheet

router = APIRouter(tags=["infra"])
logger = logging.getLogger(__name__)


class InfraSyncRequest(BaseModel):
    sheet_id: Optional[str] = None
    worksheet_name: Optional[str] = None


class InfraSyncResponse(BaseModel):
    status: str
    processed: int
    updated: int
    created: int


@router.post("/sync/camaras", response_model=InfraSyncResponse)
async def trigger_infra_sync(payload: InfraSyncRequest | None = None) -> InfraSyncResponse:
    sheet_id = payload.sheet_id if payload else None
    worksheet_name = payload.worksheet_name if payload else None
    try:
        result = sync_camaras_from_sheet(sheet_id=sheet_id, worksheet_name=worksheet_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("action=infra_sync endpoint_error=%s", exc)
        raise HTTPException(status_code=500, detail="Falló la sincronización de infraestructura") from exc

    return InfraSyncResponse(
        status="ok",
        processed=result.processed,
        updated=result.updated,
        created=result.created,
    )
