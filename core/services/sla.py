# Nombre de archivo: sla.py
# Ubicación de archivo: core/services/sla.py
# Descripción: Servicios de alto nivel para generación de informes SLA
"""Servicios de alto nivel para informes SLA."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pandas as pd
from core.sla import parser, engine, report, preview
from core.sla.config import (
    DEFAULT_TZ,
    MERGE_GAP_MINUTES,
    REPORTS_DIR,
    SOFFICE_BIN,
    UPLOADS_DIR,
)
from core.services import repetitividad as repetitividad_service

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SLAReportConfig:
    """Parámetros globales para generar el informe."""

    reports_dir: Path
    uploads_dir: Path
    soffice_bin: Optional[str]

    @classmethod
    def from_settings(cls) -> "SLAReportConfig":
        return cls(
            reports_dir=REPORTS_DIR,
            uploads_dir=UPLOADS_DIR,
            soffice_bin=SOFFICE_BIN,
        )


@dataclass(slots=True)
class SLAReportResult:
    """Resultado de la generación de un informe completo."""

    docx: Path
    pdf: Optional[Path]
    computation: engine.SLAComputation
    preview: dict


def compute_from_excel(
    excel_bytes: bytes,
    *,
    mes: int,
    anio: int,
    merge_gap_minutes: Optional[int] = None,
) -> engine.SLAComputation:
    if not excel_bytes:
        raise ValueError("El archivo recibido está vacío")

    stream = io.BytesIO(excel_bytes)
    entrada = parser.cargar_fuente_excel(stream)
    logger.info(
        "action=sla_service stage=parsed filas_reclamos=%s filas_servicios=%s",
        len(entrada.reclamos),
        0 if entrada.servicios is None else len(entrada.servicios),
    )

    merge_gap = merge_gap_minutes if merge_gap_minutes is not None else MERGE_GAP_MINUTES
    return engine.calcular_sla(
        entrada.reclamos,
        mes,
        anio,
        servicios=entrada.servicios,
        merge_gap_minutes=merge_gap,
    )


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
    computation: engine.SLAComputation,
    *,
    eventos: str = "",
    conclusion: str = "",
    propuesta: str = "",
    incluir_pdf: bool = False,
    config: Optional[SLAReportConfig] = None,
) -> SLAReportResult:
    cfg = config or SLAReportConfig.from_settings()

    documento = report.generar_documento(
        computation,
        eventos=eventos,
        conclusion=conclusion,
        propuesta=propuesta,
        incluir_pdf=incluir_pdf,
        reports_dir=cfg.reports_dir,
        soffice_bin=cfg.soffice_bin,
    )

    vista = build_preview_from_computation(computation)

    return SLAReportResult(
        docx=documento.docx,
        pdf=documento.pdf,
        computation=computation,
        preview=vista,
    )


def compute_preview_from_excel(
    excel_bytes: bytes,
    *,
    mes: int,
    anio: int,
    cliente: Optional[str] = None,
    servicio: Optional[str] = None,
    service_id: Optional[str] = None,
) -> dict:
    computation = compute_from_excel(excel_bytes, mes=mes, anio=anio)
    return build_preview_from_computation(
        computation,
        cliente=cliente,
        servicio=servicio,
        service_id=service_id,
    )


def compute_from_db(
    *,
    mes: int,
    anio: int,
) -> engine.SLAComputation:
    merge_gap = MERGE_GAP_MINUTES
    reclamos_raw = repetitividad_service.reclamos_from_db(mes, anio)
    logger.info(
        "action=sla_service stage=db_fetch rows=%s mes=%s anio=%s",
        0 if reclamos_raw is None else len(reclamos_raw),
        mes,
        anio,
    )

    reclamos_normalizados = _normalizar_reclamos_db(reclamos_raw)
    if reclamos_normalizados.empty:
        logger.warning(
            "action=sla_service stage=db_empty mes=%s anio=%s",
            mes,
            anio,
        )

    return engine.calcular_sla(
        reclamos_normalizados,
        mes,
        anio,
        servicios=None,
        merge_gap_minutes=merge_gap,
    )


def build_preview_from_computation(
    computation: engine.SLAComputation,
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


def _normalizar_reclamos_db(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Adapta el esquema proveniente de DB al layout esperado por el motor SLA."""

    columnas_objetivo = list(parser._RECLAMOS_COLUMNS)  # type: ignore[attr-defined]
    if df is None or df.empty:
        return pd.DataFrame(columns=columnas_objetivo)

    mapa_columnas = {
        "numero_reclamo": "ticket_id",
        "numero_linea": "service_id",
        "nombre_cliente": "cliente",
        "tipo_servicio": "tipo_servicio",
        "fecha_inicio": "inicio",
        "fecha_cierre": "fin",
        "horas_netas": "duracion_h",
        "tipo_solucion": "causal",
        "descripcion_solucion": "descripcion",
    }

    trabajo = df.rename(columns=mapa_columnas)
    for columna in columnas_objetivo:
        if columna not in trabajo.columns:
            trabajo[columna] = pd.NA

    trabajo = trabajo[columnas_objetivo].copy()

    trabajo["ticket_id"] = _normalizar_texto(trabajo["ticket_id"])
    trabajo["service_id"] = _normalizar_texto(trabajo["service_id"])
    trabajo["cliente"] = _normalizar_texto(trabajo["cliente"])
    trabajo["tipo_servicio"] = _normalizar_texto(trabajo["tipo_servicio"])
    trabajo["causal"] = _normalizar_texto(trabajo["causal"])
    trabajo["descripcion"] = _normalizar_texto(trabajo["descripcion"], limite=500)
    trabajo["estado"] = pd.NA if "estado" not in trabajo else _normalizar_texto(trabajo["estado"])
    trabajo["criticidad"] = pd.NA if "criticidad" not in trabajo else _normalizar_texto(trabajo["criticidad"])

    trabajo["inicio"] = trabajo["inicio"].apply(_parsear_timestamp)
    trabajo["fin"] = trabajo["fin"].apply(_parsear_timestamp)

    trabajo["duracion_h"] = trabajo.apply(
        lambda fila: _resolver_duracion_horas(fila.get("duracion_h"), fila.get("inicio"), fila.get("fin")),
        axis=1,
    )

    trabajo.sort_values(["service_id", "inicio", "fin"], inplace=True, na_position="last")
    if "ticket_id" in trabajo.columns:
        trabajo.drop_duplicates(subset="ticket_id", keep="last", inplace=True)

    trabajo.reset_index(drop=True, inplace=True)
    return trabajo


def _normalizar_texto(serie: pd.Series, *, limite: Optional[int] = None) -> pd.Series:
    """Normaliza strings eliminando espacios y valores vacíos."""

    limpio = serie.astype("string")
    limpio = limpio.str.strip()
    limpio = limpio.replace({"": pd.NA, "nan": pd.NA, "none": pd.NA, "<na>": pd.NA, "null": pd.NA})
    if limite is not None:
        limpio = limpio.astype("string")
        limpio = limpio.str.slice(0, limite)
    return limpio


def _parsear_timestamp(valor) -> Optional[pd.Timestamp]:
    if valor is None or valor is pd.NA:
        return None
    try:
        ts = pd.to_datetime(valor, errors="coerce")
    except Exception:  # noqa: BLE001
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize(DEFAULT_TZ)
    return ts.tz_convert(DEFAULT_TZ)


def _resolver_duracion_horas(valor, inicio: Optional[pd.Timestamp], fin: Optional[pd.Timestamp]) -> Optional[float]:
    if valor is None or valor is pd.NA:
        if inicio is not None and fin is not None:
            delta = fin - inicio
            return round(delta.total_seconds() / 3600, 4)
        return None

    if isinstance(valor, (int, float, Decimal)):
        try:
            numero = float(valor)
            if pd.isna(numero):  # type: ignore[arg-type]
                raise ValueError
            return round(numero, 4)
        except Exception:  # noqa: BLE001
            pass

    try:
        texto = str(valor).strip().lower().replace(",", ".")
        if not texto or texto in {"nan", "none", "null"}:
            raise ValueError
        delta = pd.to_timedelta(texto)
        if pd.isna(delta):
            raise ValueError
        return round(delta.total_seconds() / 3600, 4)
    except Exception:
        if inicio is not None and fin is not None:
            delta = fin - inicio
            return round(delta.total_seconds() / 3600, 4)
        return None
