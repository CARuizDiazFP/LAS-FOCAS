# Nombre de archivo: runner.py
# Ubicación de archivo: modules/informes_sla/runner.py
# Descripción: Orquestador del flujo de cálculo y generación de reportes de SLA

import logging
from typing import Dict, Optional

from . import processor, report
from .config import BASE_REPORTS
from .schemas import Params, ResultadoSLA

logger = logging.getLogger(__name__)


def run(file_path: str, mes: int, anio: int, soffice_bin: Optional[str]) -> Dict[str, object]:
    """Ejecuta el flujo completo de análisis de SLA."""
    df = processor.load_excel(file_path)
    df = processor.normalize(df)
    df = processor.filter_period(df, mes, anio)
    df = processor.apply_sla_target(df)
    resultado: ResultadoSLA = processor.compute_kpis(df)

    params = Params(periodo_mes=mes, periodo_anio=anio)
    docx_path = report.export_docx(resultado, params, str(BASE_REPORTS))
    pdf_path = report.maybe_export_pdf(docx_path, soffice_bin)

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
    return paths
