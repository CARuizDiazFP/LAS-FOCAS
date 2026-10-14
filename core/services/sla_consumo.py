# Nombre de archivo: sla_consumo.py
# Ubicación de archivo: core/services/sla_consumo.py
# Descripción: Orquesta el informe SLA consumido — parsea, persiste el histórico y genera XLSX/DOCX/PDF

from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from core.sla_consumo.docx_builder import construir_docx_ejecutivo, construir_docx_exhaustivo
from core.sla_consumo.engine import calcular
from core.sla_consumo.parser import parse_reclamos, parse_servicios
from core.sla_consumo.persistencia import ResultadoIngesta, cargar_ventana, ingerir, sha256
from core.sla_consumo.xlsx_builder import construir_xlsx

logger = logging.getLogger(__name__)

PDF_EXHAUSTIVO_OMITIDO = ("PDF del informe exhaustivo no se genera en línea por su tamaño "
                          "(convertir el DOCX si hace falta)")


@dataclass
class InformeSlaConsumo:
    xlsx: Path
    docx_ejecutivo: Path
    docx_exhaustivo: Path
    pdf_ejecutivo: Path | None
    pdf_exhaustivo: Path | None
    ingesta: ResultadoIngesta
    totales: dict
    pdf_omitido: str | None = None   # motivo por el que se pidió PDF y no se generó


def _json_safe(valor: object) -> object:
    """Convierte numpy/fechas a tipos nativos para JSONResponse y JSONB."""
    if isinstance(valor, dict):
        return {str(k): _json_safe(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_json_safe(v) for v in valor]
    if isinstance(valor, (dt.date, dt.datetime)):
        return valor.isoformat()
    if hasattr(valor, "item"):
        return valor.item()
    return valor


def generar_informe_sla_consumo(servicios_bytes: bytes, reclamos_bytes: bytes, *, usuario: str | None,
                                incluir_pdf: bool, reports_dir: Path,
                                report_history_id: int | None = None) -> InformeSlaConsumo:
    servicios = parse_servicios(servicios_bytes)
    reclamos = parse_reclamos(reclamos_bytes)
    if reclamos.empty:
        raise ValueError("El Excel de reclamos no tiene filas válidas")
    ingesta = ingerir(servicios, reclamos, hash_servicios=sha256(servicios_bytes),
                      hash_reclamos=sha256(reclamos_bytes), usuario=usuario,
                      report_history_id=report_history_id)
    logger.info("action=sla_consumo stage=ingesta id=%s corte=%s ya=%s ins=%s upd=%s", ingesta.ingesta_id,
                ingesta.fecha_corte, ingesta.ya_ingestado, ingesta.reclamos_insertados, ingesta.reclamos_actualizados)
    reclamos_db, servicios_db = cargar_ventana(ingesta.fecha_corte)
    resultado = calcular(reclamos_db, servicios_db, ingesta.fecha_corte)

    sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta = Path(reports_dir) / "sla_consumo" / ingesta.fecha_corte.strftime("%Y%m")
    base = f"SLA_consumido_{ingesta.fecha_corte}_{sello}"
    xlsx = construir_xlsx(resultado, carpeta / f"{base}.xlsx")
    docx_ejecutivo = construir_docx_ejecutivo(resultado, carpeta / f"{base}_ejecutivo.docx")
    docx_exhaustivo = construir_docx_exhaustivo(resultado, carpeta / f"{base}_exhaustivo.docx")
    pdf_ejecutivo = None
    pdf_omitido = None
    soffice = os.getenv("SOFFICE_BIN")
    if incluir_pdf and soffice:
        from modules.common.libreoffice_export import convert_to_pdf

        # El exhaustivo tarda ~6,5 min en LibreOffice: nunca se convierte dentro del request.
        pdf_omitido = PDF_EXHAUSTIVO_OMITIDO
        try:
            pdf_ejecutivo = Path(convert_to_pdf(str(docx_ejecutivo), soffice))
        except Exception:  # noqa: BLE001 - la ingesta ya se persistió: nunca 500 por el PDF
            logger.exception("action=sla_consumo stage=pdf_ejecutivo")
            pdf_omitido = f"No se pudo generar el PDF ejecutivo; {PDF_EXHAUSTIVO_OMITIDO}"
    elif incluir_pdf:
        pdf_omitido = "LibreOffice no configurado"
    return InformeSlaConsumo(xlsx, docx_ejecutivo, docx_exhaustivo, pdf_ejecutivo, None, ingesta,
                             _json_safe(resultado.totales), pdf_omitido)
