"""
# Nombre de archivo: ingest.py
# Ubicación de archivo: api/app/routes/ingest.py
# Descripción: Endpoints de ingesta de reclamos (XLSX/CSV) con normalización robusta
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any, Dict

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from core.parsers.reclamos_excel import IngestSummary, parse_reclamos_df
from core.services.repetitividad import upsert_reclamos
from core.services.camara_ingest_service import procesar_ingesta_camaras


router = APIRouter(prefix="/ingest", tags=["ingest"])
logger = logging.getLogger(__name__)


@router.post("/reclamos")
async def ingest_reclamos(
    file: UploadFile = File(..., description="Archivo XLSX o CSV con reclamos"),
    flujo: str | None = Form(None, description="Nombre del flujo que consume (opcional)"),
) -> JSONResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Falta nombre de archivo")
    name = file.filename.lower()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Archivo vacío")

    try:
        if name.endswith(".xlsx") or name.endswith(".xlsm"):
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl", dtype=str, keep_default_na=False)
        elif name.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
        else:
            raise HTTPException(status_code=415, detail="Formato no soportado (use .xlsx o .csv)")
    except Exception as exc:  # noqa: BLE001
        logger.exception("action=ingest_read error=%s", exc)
        raise HTTPException(status_code=400, detail="No se pudo leer el archivo") from exc

    df_ok, summary = parse_reclamos_df(df)
    inserted, updated = await asyncio.to_thread(upsert_reclamos, df_ok)

    payload: Dict[str, Any] = {
        "status": "ok",
        "rows_ok": summary.rows_ok,
        "rows_bad": summary.rows_bad,
        "inserted": inserted,
        "updated": updated,
        "date_min": None if summary.date_min is None else summary.date_min.isoformat(),
        "date_max": None if summary.date_max is None else summary.date_max.isoformat(),
        "geo_pct": round(summary.geo_pct, 2),
        "geo_available": summary.geo_pct > 0.0,
    }
    return JSONResponse(payload)

@router.post("/camaras")
async def ingest_camaras(
    file: UploadFile = File(..., description="Archivo XLSX con cámaras (alias en columna B, sin cabecera)"),
    motivo_baneo: str = Form(..., description="Motivo del baneo masivo (obligatorio)"),
    usuario: str = Form(..., description="Usuario admin que ejecuta la operación"),
) -> JSONResponse:
    """Ingesta masiva de cámaras desde Excel y baneo administrativo.

    Lee la segunda columna (índice 1) del archivo sin cabeceras, da de alta
    las cámaras que no existen en la base de datos y aplica estado BANEADA
    a todas las cámaras leídas mediante override manual.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Falta nombre de archivo")
    name = file.filename.lower()
    if not (name.endswith(".xlsx") or name.endswith(".xlsm")):
        raise HTTPException(status_code=415, detail="Formato no soportado (use .xlsx o .xlsm)")

    motivo_baneo = motivo_baneo.strip()
    if not motivo_baneo:
        raise HTTPException(status_code=400, detail="El motivo de baneo no puede estar vacío")

    usuario = usuario.strip()
    if not usuario:
        raise HTTPException(status_code=400, detail="El usuario es obligatorio")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Archivo vacío")

    try:
        df = pd.read_excel(
            io.BytesIO(content),
            header=None,
            usecols=[1],
            engine="openpyxl",
            dtype=str,
            keep_default_na=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("action=ingest_camaras_read_error error=%s", exc)
        raise HTTPException(status_code=400, detail="No se pudo leer el archivo Excel") from exc

    aliases: list[str] = (
        df.iloc[:, 0]
        .dropna()
        .str.strip()
        .replace("", None)
        .dropna()
        .unique()
        .tolist()
    )

    if not aliases:
        raise HTTPException(status_code=422, detail="No se encontraron aliases válidos en la columna B")

    resultado = await asyncio.to_thread(procesar_ingesta_camaras, aliases, motivo_baneo, usuario)

    return JSONResponse({
        "status": "ok",
        "creadas": resultado.creadas,
        "preexistentes": resultado.preexistentes,
        "baneadas": resultado.baneadas,
        "errores": resultado.errores,
    })


# Alias solicitado: /import/reclamos → mismo handler
alias_router = APIRouter(prefix="/import", tags=["ingest"])

@alias_router.post("/reclamos")
async def import_reclamos(
    file: UploadFile = File(..., description="Archivo XLSX o CSV con reclamos"),
    flujo: str | None = Form(None, description="Nombre del flujo que consume (opcional)"),
) -> JSONResponse:
    return await ingest_reclamos(file=file, flujo=flujo)
