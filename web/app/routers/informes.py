# Nombre de archivo: informes.py
# Ubicación de archivo: web/app/routers/informes.py
# Descripción: Rutas de informes de la app web: SLA, SLA consumido, repetitividad, comparador FO, alarmas Ciena y VLANs

from __future__ import annotations

import asyncio
import io
import os
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from core.services import sla as sla_service
from core.services import sla_consumo as sla_consumo_service
from core.services.repetitividad import db_to_processor_frame, reclamos_from_db
from modules.informes_repetitividad.service import (
    ReportConfig,
    ReportResult,
    generar_informe_desde_dataframe,
    generar_informe_desde_excel,
)
from web.tools.vlan_comparator import compare_vlan_sets, parse_cisco_vlans

from ..comun import (
    REPORT_HISTORY,
    REPORTS_DIR,
    UPLOADS_DIR,
    _require_auth,
    get_current_user,
    logger,
)

router = APIRouter()

REPORT_SERVICE_CONFIG = ReportConfig.from_settings()

# Elegir la carpeta de reportes a montar: preferir la de configuración si existe; si no, fallback local
_cfg_reports = Path(REPORT_SERVICE_CONFIG.reports_dir)
_mount_reports = _cfg_reports if _cfg_reports.exists() else REPORTS_DIR
_mount_reports.mkdir(parents=True, exist_ok=True)


class VLANCompareRequest(BaseModel):
    text_a: str = Field(..., description="Configuración de la primera interfaz")
    text_b: str = Field(..., description="Configuración de la segunda interfaz")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.get("/reports/index")
async def reports_index_redirect() -> RedirectResponse:
    return RedirectResponse(url="/reports-history", status_code=status.HTTP_302_FOUND)


@router.api_route("/reports/{ruta:path}", methods=["GET", "HEAD"])
async def descargar_informe(ruta: str, request: Request) -> FileResponse:
    """Sirve un informe generado (antes era un mount estático sin sesión). Exige sesión y no sale de la base."""
    _require_auth(request)
    base = Path(_mount_reports).resolve()
    try:
        destino = (base / ruta).resolve()
    except (OSError, ValueError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found") from None
    if not destino.is_relative_to(base) or not destino.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return FileResponse(destino)


@router.get("/api/reports/history")
async def api_reports_history(
    request: Request,
    type: str | None = None,  # noqa: A002 - nombre público del filtro
    status: str | None = None,
    username: str | None = None,
    month: int | None = None,
    year: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> JSONResponse:
    """Devuelve el histórico persistente de reportes generados."""

    _require_auth(request)
    clean_limit = max(1, min(limit, 200))
    clean_offset = max(0, offset)
    records = REPORT_HISTORY.list_records(
        report_type=type or None,
        status=status or None,
        username=username or None,
        month=month,
        year=year,
        limit=clean_limit,
        offset=clean_offset,
    )
    files = _legacy_files_from_report_history(records)
    return JSONResponse(
        {
            "items": records,
            "files": files,
            "limit": clean_limit,
            "offset": clean_offset,
        }
    )


def _legacy_files_from_report_history(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Construye una vista compatible con el viejo listado de archivos."""

    files: List[Dict[str, Any]] = []
    for record in records:
        output_metadata = record.get("output_metadata") or {}
        outputs = output_metadata.get("outputs") or {}
        if not isinstance(outputs, dict):
            continue
        for label, raw_href in outputs.items():
            hrefs = raw_href if isinstance(raw_href, list) else [raw_href]
            for href in hrefs:
                if not href or not isinstance(href, str):
                    continue
                files.append(
                    {
                        "name": Path(href).name,
                        "size": 0,
                        "mtime": 0,
                        "href": href,
                        "report_id": record.get("id"),
                        "label": label,
                    }
                )
    return files


def _merge_excel_sources(sources: List[tuple[str, bytes]]) -> bytes:
    if not sources:
        raise ValueError("No hay archivos para combinar")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:  # type: ignore[arg-type]
        sheet_index = 1
        for name, content in sources:
            try:
                workbook = pd.ExcelFile(io.BytesIO(content))
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"El archivo {name} no parece un Excel válido") from exc
            for sheet in workbook.sheet_names:
                dataframe = workbook.parse(sheet)
                prefix = Path(name).stem[:18] or "Hoja"
                sheet_label = f"{prefix}_{sheet_index}"[:31]
                dataframe.to_excel(writer, sheet_name=sheet_label, index=False)
                sheet_index += 1
    buffer.seek(0)
    return buffer.getvalue()


def _report_href(path: Path) -> str:
    """Construye la ruta HTTP para un archivo montado en /reports."""

    archivo = Path(path)
    candidatos = [Path(_mount_reports)]
    try:
        candidatos.append(Path(REPORT_SERVICE_CONFIG.reports_dir))
    except Exception:  # noqa: BLE001 - fallback defensivo
        pass
    candidatos.append(REPORTS_DIR)

    for base in candidatos:
        try:
            rel = archivo.relative_to(base)
        except ValueError:
            continue
        return f"/reports/{rel.as_posix()}"
    return f"/reports/{archivo.name}"


async def _cerrar_uploads_sla(upload_list: List[UploadFile]) -> None:
    for upload in upload_list:
        try:
            await upload.close()
        except Exception:  # noqa: BLE001
            logger.debug("action=sla_web_report stage=close_upload warning", exc_info=True)


async def _validar_csrf_sla(request: Request, csrf_token: str | None, files: List[UploadFile]) -> JSONResponse | None:
    """Devuelve la respuesta 403 si el CSRF no coincide (se omite con TESTING=true)."""

    expected_csrf = request.session.get("csrf")
    if expected_csrf and os.getenv("TESTING", "false").lower() != "true":
        if csrf_token != expected_csrf:
            await _cerrar_uploads_sla(files)
            return JSONResponse({"ok": False, "error": "CSRF inválido"}, status_code=403)
    return None


def _validar_periodo_sla(raw_mes: str | None, raw_anio: str | None) -> tuple[int, int] | JSONResponse:
    """Convierte mes/año a enteros o devuelve la respuesta 422 correspondiente."""

    try:
        mes_num = int(str(raw_mes).strip())
        anio_num = int(str(raw_anio).strip())
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "Mes y año deben ser numéricos"}, status_code=422)
    if not 1 <= mes_num <= 12 or not 2000 <= anio_num <= 2100:
        return JSONResponse({"ok": False, "error": "Mes y año fuera de rango permitido"}, status_code=422)
    return mes_num, anio_num


def _iniciar_historial_sla(
    username: str, source: str, mes_num: int, anio_num: int, archivos: List[UploadFile], pdf_enabled: bool, use_db: bool
) -> str:
    return REPORT_HISTORY.start(
        report_type="sla",
        username=username,
        source=source,
        period_month=mes_num,
        period_year=anio_num,
        input_metadata={
            "archivo_count": len(archivos),
            "archivos": [Path(archivo.filename or "").name for archivo in archivos],
            "pdf_enabled": bool(pdf_enabled),
            "use_db": bool(use_db),
        },
    )


def _registrar_error_sla(history_id: str, source: str, error_code: str, message: str) -> None:
    REPORT_HISTORY.finish_error(
        history_id,
        error_code=error_code,
        error_message=message,
        output_metadata={"source": source},
    )


def _rechazo_sla(on_error: Any, status_code: int, message: str) -> JSONResponse:
    """Registra el error en el historial y arma la respuesta JSON de rechazo."""

    on_error(f"HTTP_{status_code}", message)
    return JSONResponse({"ok": False, "error": message}, status_code=status_code)


async def _leer_excels_sla(archivos: List[UploadFile], on_error: Any) -> tuple[bytes, bytes] | JSONResponse:
    """Valida y lee el par servicios/reclamos del modo Excel."""

    servicios_bytes: Optional[bytes] = None
    reclamos_bytes: Optional[bytes] = None
    for archivo in archivos:
        nombre = Path(archivo.filename).name
        logger.debug("action=sla_web_report stage=processing file=%s", nombre)
        if not nombre.lower().endswith(".xlsx"):
            await archivo.close()
            logger.warning("action=sla_web_report stage=validation error=extension file=%s", nombre)
            return _rechazo_sla(on_error, 415, f"{nombre} debe tener extensión .xlsx")
        contenido = await archivo.read()
        await archivo.close()
        if not contenido:
            logger.warning("action=sla_web_report stage=validation error=empty file=%s", nombre)
            return _rechazo_sla(on_error, 400, f"{nombre} está vacío")
        try:
            tipo = sla_service.identify_excel_kind(contenido)
            logger.info("action=sla_web_report stage=identify file=%s tipo=%s", nombre, tipo)
        except ValueError as exc:
            logger.warning("action=sla_web_report stage=identify error=%s file=%s", exc, nombre)
            return _rechazo_sla(on_error, 422, str(exc))

        if tipo == "servicios":
            if servicios_bytes is not None:
                return _rechazo_sla(on_error, 422, "Se recibió más de un Excel de servicios")
            servicios_bytes = contenido
        else:
            if reclamos_bytes is not None:
                return _rechazo_sla(on_error, 422, "Se recibió más de un Excel de reclamos")
            reclamos_bytes = contenido

    if servicios_bytes is None or reclamos_bytes is None:
        logger.warning(
            "action=sla_web_report stage=validation error=missing_files servicios=%s reclamos=%s",
            servicios_bytes is not None,
            reclamos_bytes is not None,
        )
        return _rechazo_sla(on_error, 400, "Adjuntá los archivos de servicios y reclamos")
    return servicios_bytes, reclamos_bytes


async def _generar_sla_excel(
    archivos: List[UploadFile], username: str, mes_num: int, anio_num: int, pdf_enabled: bool, on_error: Any
) -> tuple[Path, Optional[Path]] | JSONResponse:
    """Modo Excel: valida los dos archivos y genera el informe legacy."""

    logger.info("action=sla_web_report stage=start user=%s archivos=%s", username, len(archivos))
    if len(archivos) != 2:
        await _cerrar_uploads_sla(archivos)
        logger.warning("action=sla_web_report stage=validation error=archivos_incorrectos count=%s", len(archivos))
        return _rechazo_sla(on_error, 400, "Debés adjuntar dos archivos: servicios y reclamos")

    leidos = await _leer_excels_sla(archivos, on_error)
    if isinstance(leidos, JSONResponse):
        return leidos
    servicios_bytes, reclamos_bytes = leidos

    logger.info("action=sla_web_report stage=generate_legacy mes=%s anio=%s pdf=%s", mes_num, anio_num, pdf_enabled)
    documento = sla_service.generate_report_from_excel_pair(
        servicios_bytes,
        reclamos_bytes,
        mes=mes_num,
        anio=anio_num,
        incluir_pdf=pdf_enabled,
    )
    logger.info("action=sla_web_report stage=legacy_ok docx=%s pdf=%s", documento.docx, documento.pdf)
    return documento.docx, documento.pdf


def _generar_sla_db(mes_num: int, anio_num: int, pdf_enabled: bool) -> tuple[Path, Optional[Path]]:
    """Modo DB: calcula desde la base y genera el informe."""

    computation = sla_service.compute_from_db(mes=mes_num, anio=anio_num)
    resultado = sla_service.generate_report_from_computation(computation, incluir_pdf=pdf_enabled)
    return resultado.docx, resultado.pdf


def _respuesta_sla_exitosa(
    history_id: str,
    username: str,
    source: str,
    mes_num: int,
    anio_num: int,
    docx: Path,
    pdf: Optional[Path],
    archivo_count: int,
) -> JSONResponse:
    report_paths = {"docx": _report_href(docx)}
    if pdf:
        report_paths["pdf"] = _report_href(pdf)

    logger.info(
        "action=sla_web_report stage=success user=%s source=%s mes=%s anio=%s pdf=%s archivos=%s",
        username,
        source,
        mes_num,
        anio_num,
        bool(pdf),
        archivo_count,
    )
    REPORT_HISTORY.finish_success(
        history_id,
        output_metadata={
            "source": source,
            "outputs": report_paths,
            "archivo_count": archivo_count,
        },
    )
    return JSONResponse(
        {
            "ok": True,
            "message": "Informe SLA generado correctamente",
            "report_paths": report_paths,
            "source": source,
        }
    )


@router.post("/api/reports/sla")
async def generar_informe_sla_web(
    request: Request,
    mes: str | None = Form(None),
    anio: str | None = Form(None),
    periodo_mes: str | None = Form(None),
    periodo_anio: str | None = Form(None),
    pdf_enabled: bool = Form(False),
    use_db: bool = Form(False),
    csrf_token: str | None = Form(None),
    files: List[UploadFile] = File(default=[]),
):
    username, _ = _require_auth(request)
    error_csrf = await _validar_csrf_sla(request, csrf_token, files)
    if error_csrf is not None:
        return error_csrf

    periodo = _validar_periodo_sla(mes or periodo_mes, anio or periodo_anio)
    if isinstance(periodo, JSONResponse):
        await _cerrar_uploads_sla(files)
        return periodo
    mes_num, anio_num = periodo

    # Normalizar files: filtrar solo los que tienen nombre de archivo
    archivos = [archivo for archivo in files if archivo and archivo.filename]
    archivo_count = len(archivos)
    source = "db" if use_db else "excel-legacy"
    history_id = _iniciar_historial_sla(username, source, mes_num, anio_num, archivos, pdf_enabled, use_db)

    def _history_error(error_code: str, message: str) -> None:
        _registrar_error_sla(history_id, source, error_code, message)

    if use_db and archivos:
        for archivo in archivos:
            await archivo.close()
        archivos = []

    try:
        if use_db:
            salida = _generar_sla_db(mes_num, anio_num, pdf_enabled)
        else:
            salida = await _generar_sla_excel(archivos, username, mes_num, anio_num, pdf_enabled, _history_error)
    except ValueError as exc:
        logger.warning(
            "action=sla_web_report stage=validation user=%s source=%s mes=%s anio=%s error=%s",
            username,
            source,
            mes_num,
            anio_num,
            exc,
        )
        return _rechazo_sla(_history_error, 422, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "action=sla_web_report stage=unexpected user=%s source=%s mes=%s anio=%s error=%s",
            username,
            source,
            mes_num,
            anio_num,
            exc,
        )
        detalle = str(exc) or exc.__class__.__name__
        return _rechazo_sla(_history_error, 500, f"No se pudo generar el informe SLA: {detalle}")

    if isinstance(salida, JSONResponse):
        return salida
    docx, pdf = salida
    return _respuesta_sla_exitosa(history_id, username, source, mes_num, anio_num, docx, pdf, archivo_count)


@router.post("/api/reports/sla-consumo")
async def generar_informe_sla_consumo_web(
    request: Request,
    pdf_enabled: bool = Form(False),
    csrf_token: str | None = Form(None),
    files: List[UploadFile] = File(default=[]),
):
    username, _ = _require_auth(request)
    expected_csrf = request.session.get("csrf")
    if expected_csrf and os.getenv("TESTING", "false").lower() != "true" and csrf_token != expected_csrf:
        for a_ in files:
            await a_.close()
        return JSONResponse({"ok": False, "error": "CSRF inválido"}, status_code=403)

    archivos = [a for a in files if a and a.filename]
    # period_month/year son NOT NULL en report_history: se usa el mes actual; la fecha de corte real
    # (derivada de los Excel) se registra en output_metadata.
    hoy = datetime.now()
    history_id = REPORT_HISTORY.start(
        report_type="sla_consumo", username=username, source="excel", period_month=hoy.month, period_year=hoy.year,
        input_metadata={"archivos": [Path(a.filename or "").name for a in archivos], "pdf_enabled": bool(pdf_enabled)},
    )

    def _error(status: int, mensaje: str) -> JSONResponse:
        REPORT_HISTORY.finish_error(history_id, error_code=f"HTTP_{status}", error_message=mensaje,
                                    output_metadata={"source": "excel"})
        return JSONResponse({"ok": False, "error": mensaje}, status_code=status)

    if len(archivos) != 2:
        for a_ in files:
            await a_.close()
        return _error(400, "Debés adjuntar dos archivos: servicios y reclamos")

    contenidos: dict[str, bytes] = {}
    for archivo in archivos:
        nombre = Path(archivo.filename).name
        contenido = await archivo.read()
        await archivo.close()
        if not nombre.lower().endswith(".xlsx") or not contenido:
            return _error(415, f"{nombre} debe ser un .xlsx no vacío")
        try:
            tipo = sla_service.identify_excel_kind(contenido)
        except ValueError as exc:
            return _error(422, str(exc))
        if tipo in contenidos:
            return _error(422, f"Se recibió más de un Excel de {tipo}")
        contenidos[tipo] = contenido
    if set(contenidos) != {"servicios", "reclamos"}:
        return _error(400, "Adjuntá los archivos de servicios y reclamos")

    try:
        informe = await asyncio.to_thread(
            sla_consumo_service.generar_informe_sla_consumo, contenidos["servicios"], contenidos["reclamos"],
            usuario=username, incluir_pdf=pdf_enabled, reports_dir=REPORTS_DIR, report_history_id=history_id,
        )
    except ValueError as exc:
        return _error(422, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("action=sla_consumo_web stage=unexpected user=%s", username)
        return _error(500, f"No se pudo generar el informe de SLA consumido: {str(exc) or exc.__class__.__name__}")

    report_paths = {"xlsx": _report_href(informe.xlsx), "docx_ejecutivo": _report_href(informe.docx_ejecutivo),
                    "docx_exhaustivo": _report_href(informe.docx_exhaustivo)}
    if informe.pdf_ejecutivo:
        report_paths["pdf_ejecutivo"] = _report_href(informe.pdf_ejecutivo)
    if informe.pdf_exhaustivo:
        report_paths["pdf_exhaustivo"] = _report_href(informe.pdf_exhaustivo)
    ingesta = informe.ingesta
    salida = {
        "fecha_corte": ingesta.fecha_corte.isoformat(), "ya_ingestado": ingesta.ya_ingestado,
        "reclamos_insertados": ingesta.reclamos_insertados, "reclamos_actualizados": ingesta.reclamos_actualizados,
        "reclamos_sin_cambios": ingesta.reclamos_sin_cambios,
        "totales": informe.totales, "report_paths": report_paths,
    }
    if informe.pdf_omitido:
        salida["pdf_omitido"] = informe.pdf_omitido
    REPORT_HISTORY.finish_success(history_id, output_metadata={"source": "excel", **salida})
    return JSONResponse({"ok": True, "message": "Informe de SLA consumido generado", **salida})


def _save_upload(file: UploadFile) -> Path:
    filename = Path(file.filename or "upload.bin").name  # sanea nombre
    dest = UPLOADS_DIR / filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    file.file.close()
    return dest


@router.post("/api/flows/sla")
async def flow_sla(
    request: Request,
    file: UploadFile | None = File(None),
    mes: int = Form(..., ge=1, le=12),
    anio: int = Form(..., ge=2000, le=2100),
    include_pdf: bool = Form(False),
    use_db: bool = Form(False),
    eventos: str = Form(""),
    conclusion: str = Form(""),
    propuesta: str = Form(""),
    csrf_token: str = Form(...),
):
    # Autenticación + CSRF
    _require_auth(request)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    use_db = use_db or not (file and file.filename)
    source = "db" if use_db else "excel"

    if use_db and file is not None:
        await file.close()

    try:
        if not use_db:
            assert file is not None
            if not file.filename or not file.filename.lower().endswith(".xlsx"):
                return JSONResponse({"error": "El archivo debe ser .xlsx"}, status_code=400)
            excel_bytes = await file.read()
            await file.close()
            if not excel_bytes:
                return JSONResponse({"error": "El archivo está vacío"}, status_code=400)

            resultado = sla_service.generate_report_from_excel(
                excel_bytes,
                mes=mes,
                anio=anio,
                eventos=eventos,
                conclusion=conclusion,
                propuesta=propuesta,
                incluir_pdf=include_pdf,
            )
        else:
            computation = sla_service.compute_from_db(mes=mes, anio=anio)
            resultado = sla_service.generate_report_from_computation(
                computation,
                eventos=eventos,
                conclusion=conclusion,
                propuesta=propuesta,
                incluir_pdf=include_pdf,
            )
    except ValueError as exc:
        logger.warning(
            "action=sla_flow stage=validation source=%s mes=%s anio=%s error=%s",
            source,
            mes,
            anio,
            exc,
        )
        return JSONResponse({"error": str(exc)}, status_code=422)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "action=sla_flow stage=unexpected source=%s mes=%s anio=%s error=%s",
            source,
            mes,
            anio,
            exc,
        )
        return JSONResponse({"error": "No se pudo generar el informe SLA"}, status_code=500)

    report_links = {"docx": _report_href(resultado.docx)}
    if resultado.pdf:
        report_links["pdf"] = _report_href(resultado.pdf)

    resumen = resultado.computation.resumen
    payload: Dict[str, Any] = {
        "status": "ok",
        "message": "Informe SLA generado",
        "source": source,
        "docx": report_links["docx"],
        "pdf": report_links.get("pdf"),
        "report_paths": report_links,
        "metrics": {
            "periodo": resumen.periodo,
            "disponibilidad_pct": resumen.disponibilidad_pct,
            "downtime_total_h": resumen.downtime_total_h,
            "servicios": resumen.servicios,
            "incidentes": resumen.incidentes,
            "tickets": resumen.tickets,
            "mttr_h": resumen.mttr_h,
            "mtbf_h": resumen.mtbf_h,
        },
    }

    logger.info(
        "action=sla_flow stage=success source=%s mes=%s anio=%s servicios=%s downtime=%s pdf=%s",
        source,
        mes,
        anio,
        resumen.servicios,
        resumen.downtime_total_h,
        bool(resultado.pdf),
    )

    return JSONResponse(payload)


@router.post("/api/flows/repetitividad")
async def flow_repetitividad(
    request: Request,
    file: UploadFile | None = File(None),
    mes: int = Form(...),
    anio: int = Form(...),
    include_pdf: bool = Form(True),
    csrf_token: str = Form(...),
    with_geo: bool = Form(False),
    use_db: bool = Form(False),
):
    """Genera el informe de Repetitividad desde Excel o DB según los parámetros."""

    username, _ = _require_auth(request)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    periodo_titulo = f"{mes:02d}/{anio}"
    use_db = use_db or file is None
    source = "db" if use_db else "excel"
    history_id = REPORT_HISTORY.start(
        report_type="repetitividad",
        username=username,
        source=source,
        period_month=mes,
        period_year=anio,
        input_metadata={
            "archivo": Path(file.filename).name if file and file.filename else None,
            "archivo_count": 0 if use_db else 1,
            "include_pdf": bool(include_pdf),
            "with_geo": bool(with_geo),
            "use_db": bool(use_db),
        },
    )

    def _history_error(error_code: str, message: str) -> None:
        REPORT_HISTORY.finish_error(
            history_id,
            error_code=error_code,
            error_message=message,
            output_metadata={"source": source},
        )

    start = time.time()

    try:
        if not use_db:
            if not file or not file.filename or not file.filename.lower().endswith(".xlsx"):
                _history_error("HTTP_400", "El archivo debe ser .xlsx")
                return JSONResponse({"error": "El archivo debe ser .xlsx"}, status_code=400)

            upload_path = _save_upload(file)
            try:
                size_bytes = upload_path.stat().st_size
                if size_bytes > 10 * 1024 * 1024:
                    upload_path.unlink(missing_ok=True)
                    _history_error("HTTP_413", "Archivo demasiado grande (límite 10MB)")
                    return JSONResponse({"error": "Archivo demasiado grande (límite 10MB)"}, status_code=413)
                if not zipfile.is_zipfile(upload_path):
                    upload_path.unlink(missing_ok=True)
                    _history_error("HTTP_400", "El archivo subido no es un Excel .xlsx válido")
                    return JSONResponse({"error": "El archivo subido no es un Excel .xlsx válido"}, status_code=400)
                logger.info(
                    "action=flow_repetitividad stage=start source=excel periodo=%s include_pdf=%s with_geo=%s size_bytes=%s",
                    periodo_titulo,
                    include_pdf,
                    with_geo,
                    size_bytes,
                )
                try:
                    df_head = pd.read_excel(upload_path, nrows=1, engine="openpyxl")
                    logger.info(
                        "action=flow_repetitividad stage=inspect columns_raw=%s",
                        list(df_head.columns),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("action=flow_repetitividad stage=inspect error=%s", exc)

                excel_bytes = upload_path.read_bytes()
                result: ReportResult = await asyncio.to_thread(
                    generar_informe_desde_excel,
                    excel_bytes,
                    periodo_titulo,
                    include_pdf,
                    REPORT_SERVICE_CONFIG,
                    with_geo,
                )
            finally:
                upload_path.unlink(missing_ok=True)
        else:
            df_db = reclamos_from_db(mes, anio)
            df_proc = db_to_processor_frame(df_db)
            if df_proc.empty:
                _history_error("HTTP_404", "No hay reclamos registrados para el período")
                return JSONResponse({"error": "No hay reclamos registrados para el período"}, status_code=404)
            logger.info(
                "action=flow_repetitividad stage=start source=db periodo=%s include_pdf=%s with_geo=%s filas=%s",
                periodo_titulo,
                include_pdf,
                with_geo,
                len(df_proc),
            )
            result = await asyncio.to_thread(
                generar_informe_desde_dataframe,
                df_proc,
                periodo_titulo,
                include_pdf,
                REPORT_SERVICE_CONFIG,
                with_geo,
                "db",
            )
    except ValueError as exc:
        logger.warning(
            "action=flow_repetitividad stage=validation error=%s periodo=%s", exc, periodo_titulo
        )
        _history_error("HTTP_422", str(exc))
        return JSONResponse({"error": str(exc)}, status_code=422)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "action=flow_repetitividad stage=unexpected periodo=%s error=%s",
            periodo_titulo,
            exc,
        )
        _history_error("HTTP_500", "No se pudo generar el informe")
        return JSONResponse({"error": "No se pudo generar el informe"}, status_code=500)

    # Los PNG viven en subcarpetas (maps_YYYYMM/): la URL debe incluirlas.
    image_maps = [_report_href(m) for m in result.map_images]
    payload: Dict[str, Any] = {
        "status": "ok",
        "pdf_requested": include_pdf,
        "with_geo": bool(with_geo),
        "source": "db" if use_db else "excel",
        "stats": {
            "filas": result.total_filas,
            "repetitivos": result.total_repetitivos,
            "periodos": result.periodos_detectados or [],
        },
        "maps": [],
        "map_images": image_maps,
        "assets": image_maps,
    }
    if result.docx:
        payload["docx"] = f"/reports/{result.docx.name}"
    if result.pdf:
        payload["pdf"] = f"/reports/{result.pdf.name}"
    elif include_pdf:
        payload["pdf_generated"] = False
    if image_maps:
        payload["map_image"] = image_maps[0]

    elapsed = round((time.time() - start) * 1000)
    outputs = {key: payload[key] for key in ("docx", "pdf", "map_image") if payload.get(key)}
    if image_maps:
        outputs["map_images"] = image_maps
    REPORT_HISTORY.finish_success(
        history_id,
        output_metadata={
            "source": payload["source"],
            "outputs": outputs,
            "stats": payload["stats"],
            "pdf_requested": include_pdf,
            "with_geo": bool(with_geo),
        },
    )
    logger.info(
        "action=flow_repetitividad stage=success periodo=%s source=%s docx=%s pdf=%s map_images=%s filas=%s repetitivos=%s ms=%s",
        periodo_titulo,
        payload["source"],
        bool(result.docx),
        bool(result.pdf),
        len(image_maps),
        result.total_filas,
        result.total_repetitivos,
        elapsed,
    )
    return JSONResponse(payload)


@router.post("/api/flows/comparador-fo")
async def flow_comparador_fo(request: Request):
    _require_auth(request)
    return JSONResponse({"error": "Comparador FO no implementado aún"}, status_code=501)


@router.post("/api/tools/alarmas-ciena")
async def tool_alarmas_ciena(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
):
    """
    Endpoint para procesar archivos CSV de alarmas Ciena (SiteManager o MCP).
    
    Detecta automáticamente el formato, parsea el CSV y retorna un archivo Excel.
    
    Args:
        request: Request de FastAPI
        file: Archivo CSV subido
        csrf_token: Token CSRF para validación
        
    Returns:
        Response con el archivo Excel para descarga
    """
    from core.parsers.alarmas_ciena import parsear_alarmas_ciena, dataframe_to_excel
    
    # Autenticación y CSRF
    _require_auth(request)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    
    # Validar nombre y extensión
    if not file.filename or not file.filename.lower().endswith(".csv"):
        logger.warning(
            "action=alarmas_ciena_upload_invalid user=%s filename=%s",
            get_current_user(request),
            file.filename
        )
        return JSONResponse(
            {"error": "Por favor subí un archivo .CSV válido"},
            status_code=400
        )
    
    # Leer contenido
    try:
        content = await file.read()
        await file.close()
    except Exception as e:
        logger.error("action=alarmas_ciena_read_error error=%s", e, exc_info=True)
        return JSONResponse(
            {"error": "Error al leer el archivo"},
            status_code=500
        )
    
    if not content:
        return JSONResponse(
            {"error": "El archivo está vacío"},
            status_code=400
        )
    
    # Validar tamaño (límite de 10MB para CSV)
    MAX_CSV_SIZE = 10 * 1024 * 1024  # 10MB
    if len(content) > MAX_CSV_SIZE:
        logger.warning(
            "action=alarmas_ciena_size_exceeded user=%s size=%d",
            get_current_user(request),
            len(content)
        )
        return JSONResponse(
            {"error": "El archivo supera el límite de 10MB"},
            status_code=413
        )
    
    # Procesar archivo
    username = get_current_user(request)
    start_time = time.time()
    
    try:
        logger.info(
            "action=alarmas_ciena_start user=%s filename=%s size=%d",
            username,
            file.filename,
            len(content)
        )
        
        # Detectar formato y parsear
        df, formato = parsear_alarmas_ciena(content)
        
        logger.info(
            "action=alarmas_ciena_parsed user=%s formato=%s rows=%d cols=%d",
            username,
            formato.value,
            len(df),
            len(df.columns)
        )
        
        # Generar Excel
        excel_content = dataframe_to_excel(df)
        
        elapsed = time.time() - start_time
        logger.info(
            "action=alarmas_ciena_complete user=%s formato=%s rows=%d size_out=%d elapsed=%.2fs",
            username,
            formato.value,
            len(df),
            len(excel_content),
            elapsed
        )
        
        # Preparar nombre de salida
        base_name = file.filename.rsplit('.', 1)[0]
        output_filename = f"{base_name}_procesado.xlsx"
        
        # Retornar Excel para descarga
        from fastapi.responses import Response
        return Response(
            content=excel_content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                'Content-Disposition': f'attachment; filename="{output_filename}"',
                'X-Formato-Detectado': formato.value,
                'X-Filas-Procesadas': str(len(df)),
                'X-Columnas': str(len(df.columns)),
            }
        )
        
    except ValueError as e:
        # Errores de validación o formato no soportado
        logger.warning(
            "action=alarmas_ciena_validation_error user=%s error=%s",
            username,
            str(e)
        )
        return JSONResponse(
            {"error": str(e)},
            status_code=415  # Unsupported Media Type
        )
        
    except Exception as e:
        # Errores inesperados
        logger.error(
            "action=alarmas_ciena_error user=%s error=%s",
            username,
            str(e),
            exc_info=True
        )
        return JSONResponse(
            {"error": f"Error al procesar el archivo: {str(e)}"},
            status_code=500
        )


@router.post("/api/tools/compare-vlans")
async def tool_compare_vlans(request: Request, payload: VLANCompareRequest) -> JSONResponse:
    """Compara las VLANs permitidas entre dos interfaces Cisco."""

    username, _ = _require_auth(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not payload.csrf_token or payload.csrf_token != expected_csrf):
        logger.warning("action=vlan_compare result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    vlans_a = parse_cisco_vlans(payload.text_a)
    vlans_b = parse_cisco_vlans(payload.text_b)
    missing_sections: list[str] = []
    if not vlans_a:
        missing_sections.append("Interfaz A")
    if not vlans_b:
        missing_sections.append("Interfaz B")
    if missing_sections:
        detail = " y ".join(missing_sections)
        logger.warning(
            "action=vlan_compare result=fail reason=empty user=%s missing=%s",
            username,
            ",".join(missing_sections),
        )
        return JSONResponse(
            {
                "error": f"No se detectaron VLANs en {detail}. Asegurate de incluir líneas 'switchport trunk allowed vlan'.",
            },
            status_code=400,
        )

    diff = compare_vlan_sets(vlans_a, vlans_b)
    response = {
        "vlans_a": diff.vlans_a,
        "vlans_b": diff.vlans_b,
        "only_a": diff.only_a,
        "only_b": diff.only_b,
        "common": diff.common,
        "total_a": len(diff.vlans_a),
        "total_b": len(diff.vlans_b),
    }
    logger.info(
        "action=vlan_compare result=success user=%s total_a=%s total_b=%s only_a=%s only_b=%s common=%s",
        username,
        response["total_a"],
        response["total_b"],
        len(response["only_a"]),
        len(response["only_b"]),
        len(response["common"]),
    )
    return JSONResponse(response)
