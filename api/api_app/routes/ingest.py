"""
# Nombre de archivo: ingest.py
# Ubicación de archivo: api/api_app/routes/ingest.py
# Descripción: Endpoints de ingesta de reclamos (XLSX/CSV) con normalización robusta
"""

from __future__ import annotations

import io
import logging
from typing import Any, Dict

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from core.parsers.reclamos_xlsx import IngestSummary, parse_reclamos_df


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

    payload: Dict[str, Any] = {
        "status": "ok",
        "rows_ok": summary.rows_ok,
        "rows_bad": summary.rows_bad,
        "date_min": None if summary.date_min is None else summary.date_min.isoformat(),
        "date_max": None if summary.date_max is None else summary.date_max.isoformat(),
        "geo_pct": round(summary.geo_pct, 2),
        "geo_available": summary.geo_pct > 0.0,
        "columns": list(df_ok.columns),
    }
    return JSONResponse(payload)
