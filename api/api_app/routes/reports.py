# Nombre de archivo: reports.py
# Ubicación de archivo: api/api_app/routes/reports.py
# Descripción: Endpoints para generación de informes (repetitividad, etc.)

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from starlette.responses import Response

from modules.informes_repetitividad.service import (
    ReportConfig,
    ReportResult,
    generar_informe_desde_excel,
)

router = APIRouter(prefix="/reports", tags=["reports"])

logger = logging.getLogger(__name__)
REPORT_SERVICE_CONFIG = ReportConfig.from_settings()


@router.post("/repetitividad")
async def generar_informe_repetitividad(
    file: UploadFile = File(..., description="Archivo Excel con casos"),
    periodo_mes: int = Form(..., ge=1, le=12, description="Mes (1-12)"),
    periodo_anio: int = Form(..., ge=2000, le=2100, description="Año"),
    incluir_pdf: bool = Form(False, description="Si es true se devuelve DOCX+PDF en un ZIP"),
) -> Response:
    """Genera el informe de repetitividad y devuelve el archivo resultante."""

    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="El archivo debe tener extensión .xlsx")

    excel_bytes = await file.read()
    if not excel_bytes:
        raise HTTPException(status_code=400, detail="El archivo está vacío")

    periodo_titulo = f"{periodo_mes:02d}/{periodo_anio}"
    try:
        result: ReportResult = generar_informe_desde_excel(
            excel_bytes,
            periodo_titulo,
            incluir_pdf,
            REPORT_SERVICE_CONFIG,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "action=reports.repetitividad stage=unexpected periodo=%s error=%s",
            periodo_titulo,
            exc,
        )
        raise HTTPException(status_code=500, detail="No se pudo generar el informe") from exc

    response_headers = {
        "X-PDF-Requested": str(incluir_pdf).lower(),
        "X-PDF-Generated": str(bool(result.pdf)).lower(),
        "X-Map-Generated": str(bool(result.map_html)).lower(),
        "X-Total-Filas": str(result.total_filas),
        "X-Total-Repetitivos": str(result.total_repetitivos),
    }
    if result.map_html:
        response_headers["X-Map-Filename"] = result.map_html.name

    if result.pdf or result.map_html:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(result.docx, result.docx.name)
            if result.pdf:
                archive.write(result.pdf, result.pdf.name)
            if result.map_html:
                archive.write(result.map_html, result.map_html.name)
        zip_buffer.seek(0)
        filename = f"repetitividad_{periodo_anio}{periodo_mes:02d}.zip"
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                **response_headers,
            },
        )

    return FileResponse(
        path=result.docx,
        filename=result.docx.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=response_headers,
    )
