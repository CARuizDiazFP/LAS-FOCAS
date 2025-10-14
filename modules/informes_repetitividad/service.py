# Nombre de archivo: service.py
# Ubicación de archivo: modules/informes_repetitividad/service.py
# Descripción: Servicio central para generar informes de repetitividad a partir de Excel en memoria

"""Servicios compartidos para el informe de repetitividad."""

from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from . import processor, report
from .config import (
    MAPS_ENABLED,
    REPORTS_DIR,
    SOFFICE_BIN,
)
from .schemas import Params, ResultadoRepetitividad

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReportConfig:
    """Parámetros de configuración para la generación del informe."""

    reports_dir: Path
    soffice_bin: str | None = None
    maps_enabled: bool = MAPS_ENABLED

    @classmethod
    def from_settings(cls) -> "ReportConfig":
        """Construye la configuración a partir de las variables globales del módulo."""

        return cls(
            reports_dir=Path(REPORTS_DIR),
            soffice_bin=SOFFICE_BIN,
            maps_enabled=MAPS_ENABLED,
        )


@dataclass(slots=True)
class ReportResult:
    """Resultado de la generación del informe."""

    docx: Path
    pdf: Path | None = None
    map_html: Path | None = None
    total_filas: int = 0
    total_repetitivos: int = 0
    periodos_detectados: List[str] | None = None


def _infer_periodo(periodo_titulo: str, periodos_detectados: List[str]) -> tuple[int, int]:
    """Obtiene un período (mes, año) razonable para usar en el informe."""

    match = re.search(r"(?P<mes>0?[1-9]|1[0-2])\D+(?P<anio>\d{4})", periodo_titulo)
    if match:
        mes = int(match.group("mes"))
        anio = int(match.group("anio"))
        return mes, anio

    for periodo in reversed(periodos_detectados or []):
        detected = re.match(r"(?P<anio>\d{4})-(?P<mes>\d{2})", periodo)
        if detected:
            mes = max(1, min(12, int(detected.group("mes"))))
            return mes, int(detected.group("anio"))

    logger.warning(
        "action=repetitividad_service stage=periodo_fallback reason=unparsable titulo=%s",
        periodo_titulo,
    )
    return 1, 1970


def generar_informe_desde_excel(
    excel_bytes: bytes,
    periodo_titulo: str,
    export_pdf: bool,
    config: ReportConfig,
) -> ReportResult:
    """Genera el informe de repetitividad a partir de un Excel en memoria.

    La función centraliza el flujo de carga → normalización → cálculo de repetitividad →
    exportación (DOCX/PDF/mapa). Es utilizada por CLI, API y UI para asegurar
    consistencia en los resultados.
    """

    if not excel_bytes:
        raise ValueError("El archivo recibido está vacío")

    reports_dir = config.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "action=repetitividad_service stage=start bytes=%s periodo_titulo=%s export_pdf=%s",
        len(excel_bytes),
        periodo_titulo,
        export_pdf,
    )

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp_in:
        tmp_in.write(excel_bytes)
        tmp_path = Path(tmp_in.name)

    try:
        df = processor.load_excel(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)

    total_filas = len(df)
    logger.info(
        "action=repetitividad_service stage=load_ok filas=%s columnas=%s",
        total_filas,
        list(df.columns),
    )

    df_normalizado = processor.normalize(df)
    logger.info(
        "action=repetitividad_service stage=normalize_ok filas=%s",
        len(df_normalizado),
    )

    resultado: ResultadoRepetitividad = processor.compute_repetitividad(df_normalizado)
    logger.info(
        "action=repetitividad_service stage=compute_ok total_servicios=%s repetitivos=%s",
        resultado.total_servicios,
        resultado.total_repetitivos,
    )

    mes, anio = _infer_periodo(periodo_titulo, resultado.periodos)
    params = Params(periodo_mes=mes, periodo_anio=anio)

    map_path: Path | None = None
    if config.maps_enabled:
        map_result = report.generate_geo_map(resultado, params, str(reports_dir))
        if map_result:
            map_path = Path(map_result)

    docx_path = Path(
        report.export_docx(
            resultado,
            params,
            str(reports_dir),
            df_raw=df_normalizado,
            map_path=str(map_path) if map_path else None,
        )
    )

    pdf_path: Path | None = None
    if export_pdf and config.soffice_bin:
        pdf_result = report.maybe_export_pdf(str(docx_path), config.soffice_bin)
        if pdf_result:
            pdf_path = Path(pdf_result)

    logger.info(
        "action=repetitividad_service stage=success docx=%s pdf=%s map=%s",
        docx_path,
        pdf_path,
        map_path,
    )

    return ReportResult(
        docx=docx_path,
        pdf=pdf_path,
        map_html=map_path,
        total_filas=total_filas,
        total_repetitivos=resultado.total_repetitivos,
        periodos_detectados=resultado.periodos,
    )


__all__: Iterable[str] = [
    "ReportConfig",
    "ReportResult",
    "generar_informe_desde_excel",
]
