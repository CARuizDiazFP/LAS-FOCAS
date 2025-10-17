# Nombre de archivo: reports.py
# Ubicación de archivo: api/api_app/routes/reports.py
# Descripción: Endpoints para generación de informes (repetitividad, etc.)

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from starlette.responses import Response

from modules.informes_repetitividad.service import (
    ReportConfig,
    ReportResult,
    generar_informe_desde_excel,
    generar_informe_desde_dataframe,
)
# Compatibilidad con tests legacy: exponer módulos para monkeypatch
from modules.informes_repetitividad import report as report  # type: ignore
from modules.informes_repetitividad import processor as processor  # type: ignore
from core.services.repetitividad import db_to_processor_frame, reclamos_from_db

router = APIRouter(prefix="/reports", tags=["reports"])

logger = logging.getLogger(__name__)


def _df_from_db_for_period(mes: int, anio: int):
    """Obtiene los reclamos del período y los adapta a la ingesta estándar."""

    raw_df = reclamos_from_db(mes, anio)
    return db_to_processor_frame(raw_df)


@router.post("/repetitividad")
async def generar_informe_repetitividad(
    file: UploadFile | None = File(None, description="Archivo Excel con casos (opcional)"),
    periodo_mes: int = Form(..., ge=1, le=12, description="Mes (1-12)"),
    periodo_anio: int = Form(..., ge=2000, le=2100, description="Año"),
    incluir_pdf: bool = Form(False, description="Si es true se devuelve DOCX+PDF en un ZIP"),
    with_geo: bool = Form(False, description="Generar mapas por servicio"),
    usar_db: bool = Form(False, description="Ignora el archivo y usa los datos de la base"),
) -> Response:
    """Genera el informe de repetitividad y devuelve el archivo resultante.

    - Si se adjunta un archivo, se usa ese dataset (modo Excel).
    - Si no hay archivo, se genera el informe desde DB filtrando por período (modo DB, JSON rápido por ahora).
    """

    periodo_titulo = f"{periodo_mes:02d}/{periodo_anio}"
    use_db = usar_db or file is None
    config = ReportConfig.from_settings()

    if not use_db:
        if not file or not file.filename or not file.filename.lower().endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="El archivo debe tener extensión .xlsx")
        excel_bytes = await file.read()
        if not excel_bytes:
            raise HTTPException(status_code=400, detail="El archivo está vacío")

        try:
            result: ReportResult = generar_informe_desde_excel(
                excel_bytes,
                periodo_titulo,
                incluir_pdf,
                config,
                with_geo=with_geo,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "action=reports.repetitividad stage=excel_error periodo=%s error=%s",
                periodo_titulo,
                exc,
            )
            raise HTTPException(status_code=500, detail="No se pudo generar el informe") from exc

        map_images = result.map_images
        response_headers = {
            "X-Source": "excel",
            "X-With-Geo": str(bool(with_geo)).lower(),
            "X-PDF-Requested": str(incluir_pdf).lower(),
            "X-PDF-Generated": str(bool(result.pdf)).lower(),
            "X-Map-Generated": str(bool(map_images)).lower(),
            "X-Maps-Count": str(len(map_images)),
            "X-Total-Filas": str(result.total_filas),
            "X-Total-Repetitivos": str(result.total_repetitivos),
        }
        if map_images:
            response_headers["X-Map-Filenames"] = ",".join(Path(m).name if isinstance(m, Path) else Path(str(m)).name for m in map_images)

        if result.pdf or map_images:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(str(result.docx), Path(result.docx).name)
                if result.pdf:
                    archive.write(str(result.pdf), Path(result.pdf).name)
                for map_path in map_images:
                    map_obj = Path(map_path)
                    archive.write(str(map_obj), map_obj.name)
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
            path=str(result.docx),
            filename=Path(result.docx).name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=response_headers,
        )

    try:
        df_db = _df_from_db_for_period(periodo_mes, periodo_anio)
        if df_db is None or df_db.empty:
            raise HTTPException(status_code=404, detail="No se encontraron reclamos para el período solicitado")

        result = generar_informe_desde_dataframe(
            df_db,
            periodo_titulo,
            incluir_pdf,
            config,
            with_geo=with_geo,
            source_label="db",
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "action=reports.repetitividad stage=db_error periodo=%s error=%s",
            periodo_titulo,
            exc,
        )
        raise HTTPException(status_code=500, detail="No se pudo generar el informe desde DB") from exc

    map_images = result.map_images
    headers = {
        "X-Source": "db",
        "X-With-Geo": str(bool(with_geo)).lower(),
        "X-PDF-Requested": str(incluir_pdf).lower(),
        "X-PDF-Generated": str(bool(result.pdf)).lower(),
        "X-Map-Generated": str(bool(map_images)).lower(),
        "X-Maps-Count": str(len(map_images)),
        "X-Total-Filas": str(result.total_filas),
        "X-Total-Repetitivos": str(result.total_repetitivos),
    }
    if map_images:
        headers["X-Map-Filenames"] = ",".join(Path(m).name if isinstance(m, Path) else Path(str(m)).name for m in map_images)

    if result.pdf or map_images:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(str(result.docx), Path(result.docx).name)
            if result.pdf:
                archive.write(str(result.pdf), Path(result.pdf).name)
            for map_path in map_images:
                map_obj = Path(map_path)
                archive.write(str(map_obj), map_obj.name)
        zip_buffer.seek(0)
        filename = f"repetitividad_{periodo_anio}{periodo_mes:02d}.zip"
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                **headers,
            },
        )

    return FileResponse(
        path=str(result.docx),
        filename=Path(result.docx).name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@router.get("/repetitividad")
async def repetitividad_metrics(periodo_mes: int = Query(..., ge=1, le=12), periodo_anio: int = Query(..., ge=2000, le=2100)) -> JSONResponse:
    from core.services.repetitividad import repetitividad_metrics_from_db
    metrics = repetitividad_metrics_from_db(periodo_mes, periodo_anio)
    return JSONResponse(
        {
            "periodo": metrics.periodo,
            "total_servicios": metrics.total_servicios,
            "servicios_repetitivos": metrics.servicios_repetitivos,
        }
    )
