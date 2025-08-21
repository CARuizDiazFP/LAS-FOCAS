# Nombre de archivo: runner.py
# Ubicación de archivo: modules/informes_sla/runner.py
# Descripción: Orquestador del flujo de cálculo y generación de reportes de SLA

import logging
import os
from typing import Dict, Optional

from . import processor, report
from .config import BASE_REPORTS
from .schemas import Params, ResultadoSLA

logger = logging.getLogger(__name__)


def run(file_path: str, mes: int, anio: int, soffice_bin: Optional[str]) -> Dict[str, object]:
    """Ejecuta el flujo completo de análisis de SLA.

    También gestiona la conversión a PDF y reporta errores de LibreOffice.
    """
    df = processor.load_excel(file_path)

    work_hours = os.getenv("WORK_HOURS", "false").lower() == "true"
    df = processor.normalize(df, work_hours=work_hours)
    df = processor.filter_period(df, mes, anio)
    df = processor.apply_sla_target(df)
    resultado: ResultadoSLA = processor.compute_kpis(df)

    params = Params(periodo_mes=mes, periodo_anio=anio)
    docx_path = report.export_docx(resultado, params, str(BASE_REPORTS))

    pdf_path: Optional[str] = None
    error_pdf: Optional[str] = None
    if soffice_bin:
        try:
            pdf_path = report.maybe_export_pdf(docx_path, soffice_bin)
            if not pdf_path:
                error_pdf = "No se pudo convertir a PDF"
        except Exception:
            logger.exception("action=run error_pdf")
            error_pdf = "No se pudo convertir a PDF"

    logger.info(
        "action=run mes=%s anio=%s docx=%s pdf=%s total=%s incumplidos=%s pct_cumplimiento=%.2f excluidos=%s",
        mes,
        anio,
        docx_path,
        pdf_path,
        resultado.kpi.total,
        resultado.kpi.incumplidos,
        resultado.kpi.pct_cumplimiento,
        resultado.sin_cierre,
    )

    paths: Dict[str, object] = {"docx": docx_path, "resultado": resultado}
    if pdf_path:
        paths["pdf"] = pdf_path
    if error_pdf:
        paths["error"] = error_pdf
    return paths
