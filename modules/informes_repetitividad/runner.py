# Nombre de archivo: runner.py
# Ubicación de archivo: modules/informes_repetitividad/runner.py
# Descripción: Orquestador del flujo de cálculo y generación de reportes

import logging
from pathlib import Path
from typing import Dict, Optional

from .config import BASE_REPORTS, SOFFICE_BIN
from .service import ReportConfig, ReportResult, generar_informe_desde_excel

logger = logging.getLogger(__name__)


def run(file_path: str, mes: int, anio: int, soffice_bin: Optional[str]) -> Dict[str, str]:
    """Ejecuta el flujo completo de cálculo y exportación del informe."""

    config_base = ReportConfig.from_settings()
    reports_dir = BASE_REPORTS
    reports_dir.mkdir(parents=True, exist_ok=True)

    soffice_effective = soffice_bin or config_base.soffice_bin or SOFFICE_BIN
    config = ReportConfig(
        reports_dir=reports_dir,
        soffice_bin=soffice_effective,
        maps_enabled=config_base.maps_enabled,
    )

    excel_bytes = Path(file_path).read_bytes()
    periodo_titulo = f"{mes:02d}/{anio}"
    result: ReportResult = generar_informe_desde_excel(
        excel_bytes,
        periodo_titulo,
        export_pdf=bool(soffice_effective),
        config=config,
    )

    logger.info(
        "action=run mes=%s anio=%s docx=%s pdf=%s mapa=%s filas=%s repetitivos=%s",
        mes,
        anio,
        result.docx,
        result.pdf,
        result.map_html,
        result.total_filas,
        result.total_repetitivos,
    )

    paths = {"docx": str(result.docx)}
    if result.pdf:
        paths["pdf"] = str(result.pdf)
    if result.map_html:
        paths["map"] = str(result.map_html)
    return paths
