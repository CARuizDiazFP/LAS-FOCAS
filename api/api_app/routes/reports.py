# Nombre de archivo: reports.py
# Ubicación de archivo: api/api_app/routes/reports.py
# Descripción: Endpoints para generación de informes (repetitividad, etc.)

from __future__ import annotations

import io
import os
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from starlette.responses import Response

from modules.informes_repetitividad import processor, report
from modules.informes_repetitividad.config import REPORTS_DIR, SOFFICE_BIN
from modules.informes_repetitividad.schemas import Params

router = APIRouter(prefix="/reports", tags=["reports"])


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

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp_in:
        tmp_in.write(await file.read())
        tmp_path = tmp_in.name

    try:
        df = processor.load_excel(tmp_path)
        df = processor.normalize(df)
        resultado = processor.compute_repetitividad(df)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        os.remove(tmp_path)

    params = Params(periodo_mes=periodo_mes, periodo_anio=periodo_anio)
    map_path = report.generate_geo_map(resultado, params, str(REPORTS_DIR))
    docx_path = report.export_docx(resultado, params, str(REPORTS_DIR), df_raw=df, map_path=map_path)

    pdf_requested = incluir_pdf
    pdf_path = None
    if incluir_pdf:
        pdf_path = report.maybe_export_pdf(docx_path, SOFFICE_BIN)

    response_headers = {
        "X-PDF-Requested": str(pdf_requested).lower(),
        "X-PDF-Generated": "true" if pdf_path else "false",
        "X-Map-Generated": str(bool(map_path)).lower(),
    }
    if map_path:
        response_headers["X-Map-Filename"] = Path(map_path).name

    if pdf_path or map_path:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(docx_path, Path(docx_path).name)
            if pdf_path:
                archive.write(pdf_path, Path(pdf_path).name)
            if map_path:
                archive.write(map_path, Path(map_path).name)
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
        path=docx_path,
        filename=Path(docx_path).name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=response_headers,
    )
