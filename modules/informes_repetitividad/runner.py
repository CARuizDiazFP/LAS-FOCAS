# Nombre de archivo: runner.py
# Ubicación de archivo: modules/informes_repetitividad/runner.py
# Descripción: Orquestador del flujo de cálculo y generación de reportes

import logging
from typing import Dict, Optional

from . import processor, report
from .config import BASE_REPORTS
from .schemas import Params

logger = logging.getLogger(__name__)


def run(file_path: str, mes: int, anio: int, soffice_bin: Optional[str]) -> Dict[str, str]:
    """Ejecuta el flujo completo de cálculo y exportación del informe."""
    df = processor.load_excel(file_path)
    df = processor.normalize(df)
    df = processor.filter_period(df, mes, anio)
    resultado = processor.compute_repetitividad(df)

    params = Params(periodo_mes=mes, periodo_anio=anio)
    docx_path = report.export_docx(resultado, params, str(BASE_REPORTS))
    pdf_path = report.maybe_export_pdf(docx_path, str(BASE_REPORTS), soffice_bin)

    logger.info(
        "action=run mes=%s anio=%s docx=%s pdf=%s total=%s repetitivos=%s",
        mes,
        anio,
        docx_path,
        pdf_path,
        resultado.total_servicios,
        resultado.total_repetitivos,
    )

    paths = {"docx": docx_path}
    if pdf_path:
        paths["pdf"] = pdf_path
    return paths
