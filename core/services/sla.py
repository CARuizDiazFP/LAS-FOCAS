# Nombre de archivo: sla.py
# Ubicación de archivo: core/services/sla.py
# Descripción: Servicios de alto nivel para el informe SLA mensual (modo Excel y modo base) sobre el motor de SLA consumido
"""Servicios de alto nivel para informes SLA.

Desde P25 hay un solo cálculo de SLA, el de ``core/sla_consumo`` (columna P, SLA entregado a 12 meses).
Acá sólo se arma el informe (``core/sla/informe.py``) y se lo renderiza (``core/sla/legacy_report.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.sla import informe as informe_sla
from core.sla import legacy_report, preview
from core.sla.config import REPORTS_DIR, UPLOADS_DIR
from core.sla.informe import SLAComputation
from core.sla.legacy_report import DocumentoSLA


@dataclass(slots=True)
class SLAReportConfig:
    """Parámetros globales para generar el informe."""

    reports_dir: Path
    uploads_dir: Path

    @classmethod
    def from_settings(cls) -> "SLAReportConfig":
        return cls(
            reports_dir=REPORTS_DIR,
            uploads_dir=UPLOADS_DIR,
        )


@dataclass(slots=True)
class SLAReportResult:
    """Resultado de la generación de un informe completo."""

    docx: Path
    pdf: Optional[Path]
    computation: SLAComputation
    preview: dict
    pdf_error: Optional[str] = None


def identify_excel_kind(content: bytes) -> str:
    """Identifica si el Excel corresponde a servicios o a reclamos."""

    return legacy_report.identificar_excel(content)


def generate_report_from_excel_pair(
    servicios_excel: bytes,
    reclamos_excel: bytes,
    *,
    mes: int,
    anio: int,
    eventos: str = "",
    conclusion: str = "",
    propuesta: str = "",
    incluir_pdf: bool = False,
    config: Optional[SLAReportConfig] = None,
) -> DocumentoSLA:
    """Modo Excel del panel: un servicio por fila del Excel de servicios."""
    cfg = config or SLAReportConfig.from_settings()
    informe = informe_sla.desde_excel(servicios_excel, reclamos_excel, mes=mes, anio=anio)
    return legacy_report.generar_documento(
        informe,
        incluir_pdf=incluir_pdf,
        reports_dir=cfg.reports_dir,
        eventos=eventos,
        conclusion=conclusion,
        propuesta=propuesta,
    )


def compute_from_excel(excel_bytes: bytes, *, mes: int, anio: int) -> SLAComputation:
    """Un solo Excel de reclamos contra la última foto de servicios de la base."""
    if not excel_bytes:
        raise ValueError("El archivo recibido está vacío")
    return informe_sla.a_computation(informe_sla.desde_excel_reclamos(excel_bytes, mes=mes, anio=anio))


def generate_report_from_excel(
    excel_bytes: bytes,
    *,
    mes: int,
    anio: int,
    eventos: str = "",
    conclusion: str = "",
    propuesta: str = "",
    incluir_pdf: bool = False,
    config: Optional[SLAReportConfig] = None,
) -> SLAReportResult:
    computation = compute_from_excel(excel_bytes, mes=mes, anio=anio)
    return generate_report_from_computation(
        computation,
        eventos=eventos,
        conclusion=conclusion,
        propuesta=propuesta,
        incluir_pdf=incluir_pdf,
        config=config,
    )


def generate_report_from_computation(
    computation: SLAComputation,
    *,
    eventos: str = "",
    conclusion: str = "",
    propuesta: str = "",
    incluir_pdf: bool = False,
    config: Optional[SLAReportConfig] = None,
) -> SLAReportResult:
    if computation.informe is None:
        raise ValueError("El cálculo no trae los datos del informe")
    cfg = config or SLAReportConfig.from_settings()

    documento = legacy_report.generar_documento(
        computation.informe,
        incluir_pdf=incluir_pdf,
        reports_dir=cfg.reports_dir,
        eventos=eventos,
        conclusion=conclusion,
        propuesta=propuesta,
    )

    return SLAReportResult(
        docx=documento.docx,
        pdf=documento.pdf,
        computation=computation,
        preview=build_preview_from_computation(computation),
        pdf_error=documento.pdf_error,
    )


def compute_from_db(*, mes: int, anio: int) -> SLAComputation:
    """Modo base: corte al fin de mes, 365 días de reclamos y los servicios con reclamos en el mes."""
    return informe_sla.a_computation(informe_sla.desde_db(mes=mes, anio=anio))


def build_preview_from_computation(
    computation: SLAComputation,
    *,
    cliente: Optional[str] = None,
    servicio: Optional[str] = None,
    service_id: Optional[str] = None,
) -> dict:
    return preview.construir_preview(
        computation,
        cliente=cliente,
        servicio=servicio,
        service_id=service_id,
    )
