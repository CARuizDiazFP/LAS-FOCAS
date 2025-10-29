# Nombre de archivo: engine.py
# Ubicación de archivo: core/sla/engine.py
# Descripción: Motor de cálculo de métricas y disponibilidad SLA
"""Motor de cálculo de métricas SLA."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
from pandas import DataFrame

from .config import DEFAULT_TZ, MERGE_GAP_MINUTES, MIN_DOWNTIME_MINUTES

ServiceKey = Tuple[str, str, str]
SeriesLike = pd.Series


@dataclass(slots=True)
class SLAIncident:
    """Incidente individual, recortado al período analizado."""

    ticket_id: Optional[str]
    service_id: Optional[str]
    cliente: Optional[str]
    tipo_servicio: Optional[str]
    inicio: pd.Timestamp
    fin: pd.Timestamp
    duracion_h: float
    downtime_h: float
    sla_objetivo_h: Optional[float]
    causal: Optional[str]
    descripcion: Optional[str]
    criticidad: Optional[str]
    estado: Optional[str]


@dataclass(slots=True)
class SLAInterval:
    """Intervalo consolidado por servicio tras unir incidentes cercanos."""

    key: ServiceKey
    service_id: Optional[str]
    cliente: Optional[str]
    tipo_servicio: Optional[str]
    inicio: pd.Timestamp
    fin: pd.Timestamp
    incidentes: List[SLAIncident] = field(default_factory=list)

    def add(self, incidente: SLAIncident) -> None:
        self.inicio = min(self.inicio, incidente.inicio)
        self.fin = max(self.fin, incidente.fin)
        self.incidentes.append(incidente)

    @property
    def downtime_h(self) -> float:
        delta = self.fin - self.inicio
        return round(delta.total_seconds() / 3600, 4)

    @property
    def incident_ids(self) -> List[str]:
        valores: List[str] = []
        for incident in self.incidentes:
            if incident.ticket_id and incident.ticket_id not in valores:
                valores.append(incident.ticket_id)
        return valores

    @property
    def sla_objetivo_h(self) -> Optional[float]:
        candidatos = [i.sla_objetivo_h for i in self.incidentes if i.sla_objetivo_h is not None]
        if not candidatos:
            return None
        return float(min(candidatos))

    @property
    def dentro_de_objetivo(self) -> Optional[bool]:
        objetivo = self.sla_objetivo_h
        if objetivo is None:
            return None
        return self.downtime_h <= objetivo

    @property
    def causas(self) -> List[str]:
        valores: List[str] = []
        for incident in self.incidentes:
            if incident.causal:
                texto = incident.causal.strip()
                if texto and texto not in valores:
                    valores.append(texto)
        return valores

    @property
    def criticidades(self) -> List[str]:
        valores: List[str] = []
        for incident in self.incidentes:
            if incident.criticidad:
                texto = incident.criticidad.strip()
                if texto and texto not in valores:
                    valores.append(texto)
        return valores


@dataclass(slots=True)
class ServiceMetrics:
    """KPIs calculados para un servicio/cliente en el período."""

    key: ServiceKey
    service_id: Optional[str]
    cliente: Optional[str]
    tipo_servicio: Optional[str]
    downtime_h: float
    disponibilidad_pct: float
    incidentes_agrupados: int
    tickets_unicos: int
    mttr_h: Optional[float]
    mtbf_h: Optional[float]
    intervals: List[SLAInterval]


@dataclass(slots=True)
class SLASummary:
    """Resumen global del período."""

    periodo: str
    disponibilidad_pct: float
    downtime_total_h: float
    servicios: int
    incidentes: int
    tickets: int
    mttr_h: Optional[float]
    mtbf_h: Optional[float]


@dataclass(slots=True)
class SLAComputation:
    """Resultado completo del motor de SLA."""

    mes: int
    anio: int
    resumen: SLASummary
    servicios: List[ServiceMetrics]
    anexos: List[dict]
    servicios_meta: Dict[str, dict]


def calcular_sla(
    reclamos: DataFrame,
    mes: int,
    anio: int,
    *,
    servicios: Optional[DataFrame] = None,
    merge_gap_minutes: int = MERGE_GAP_MINUTES,
) -> SLAComputation:
    """Calcula métricas de disponibilidad, MTTR y MTBF."""

    if not 1 <= mes <= 12:
        raise ValueError("El mes debe estar entre 1 y 12")
    if anio < 2000:
        raise ValueError("El año debe ser mayor o igual a 2000")

    periodo_inicio, periodo_fin = _limites_periodo(mes, anio)
    total_horas_periodo = round((periodo_fin - periodo_inicio).total_seconds() / 3600, 4)

    servicios_meta = _construir_meta(servicios)
    incidentes_por_servicio = _construir_incidentes_por_servicio(
        reclamos,
        periodo_inicio,
        periodo_fin,
    )

    resultados: List[ServiceMetrics] = []
    anexos: List[dict] = []

    for key, incidentes in incidentes_por_servicio.items():
        intervalos = _merge_intervalos(incidentes, merge_gap_minutes)
        if not intervalos:
            continue
        metricas = _calcular_metricas_servicio(
            key,
            intervalos,
            total_horas_periodo,
        )
        resultados.append(metricas)
        anexos.extend(_build_annex_rows(metricas))

    resumen = _calcular_resumen_global(resultados, total_horas_periodo, mes, anio)

    return SLAComputation(
        mes=mes,
        anio=anio,
        resumen=resumen,
        servicios=sorted(resultados, key=lambda m: (m.service_id or "", m.cliente or "")),
        anexos=anexos,
        servicios_meta=servicios_meta,
    )


def _limites_periodo(mes: int, anio: int) -> Tuple[pd.Timestamp, pd.Timestamp]:
    inicio = datetime(anio, mes, 1, tzinfo=DEFAULT_TZ)
    if mes == 12:
        fin = datetime(anio + 1, 1, 1, tzinfo=DEFAULT_TZ)
    else:
        fin = datetime(anio, mes + 1, 1, tzinfo=DEFAULT_TZ)
    return pd.Timestamp(inicio), pd.Timestamp(fin)


def _construir_meta(servicios: Optional[DataFrame]) -> Dict[str, dict]:
    if servicios is None or servicios.empty:
        return {}
    meta: Dict[str, dict] = {}
    for _, row in servicios.iterrows():
        service_id = _safe_str(row.get("service_id"))
        if not service_id:
            continue
        meta[service_id] = {
            "cliente": _safe_str(row.get("cliente")),
            "tipo_servicio": _safe_str(row.get("tipo_servicio")),
            "sla_pct": row.get("sla_pct"),
            "downtime_reportado_h": row.get("downtime_reportado_h"),
        }
    return meta


def _construir_incidentes_por_servicio(
    reclamos: DataFrame,
    inicio: pd.Timestamp,
    fin: pd.Timestamp,
) -> Dict[ServiceKey, List[SLAIncident]]:
    if reclamos is None or reclamos.empty:
        return {}

    incidentes: Dict[ServiceKey, List[SLAIncident]] = {}

    for _, row in reclamos.iterrows():
        incidente = _construir_incidente(row, inicio, fin)
        if incidente is None:
            continue
        key = _service_key(incidente)
        incidentes.setdefault(key, []).append(incidente)

    return incidentes


def _construir_incidente(
    row: SeriesLike,
    inicio_periodo: pd.Timestamp,
    fin_periodo: pd.Timestamp,
) -> Optional[SLAIncident]:
    inicio = row.get("inicio")
    fin = row.get("fin")
    if pd.isna(inicio) or pd.isna(fin):
        return None
    inicio = pd.Timestamp(inicio)
    fin = pd.Timestamp(fin)
    if fin <= inicio:
        return None

    clip_inicio = max(inicio, inicio_periodo)
    clip_fin = min(fin, fin_periodo)
    if clip_fin <= clip_inicio:
        return None

    downtime_h = round((clip_fin - clip_inicio).total_seconds() / 3600, 4)
    if downtime_h * 60 < MIN_DOWNTIME_MINUTES:
        return None

    duracion_h = row.get("duracion_h")
    if pd.isna(duracion_h) or duracion_h is None:
        duracion_h = round((fin - inicio).total_seconds() / 3600, 4)

    return SLAIncident(
        ticket_id=_safe_str(row.get("ticket_id")),
        service_id=_safe_str(row.get("service_id")),
        cliente=_safe_str(row.get("cliente")),
        tipo_servicio=_safe_str(row.get("tipo_servicio")),
        inicio=clip_inicio,
        fin=clip_fin,
        duracion_h=float(duracion_h),
        downtime_h=float(downtime_h),
        sla_objetivo_h=_safe_float(row.get("sla_objetivo_h")),
        causal=_safe_str(row.get("causal")),
        descripcion=_safe_str(row.get("descripcion")),
        criticidad=_safe_str(row.get("criticidad")),
        estado=_safe_str(row.get("estado")),
    )



def _safe_str(value) -> Optional[str]:
    if value is None or value is pd.NA:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    return text


def _safe_float(value) -> Optional[float]:
    if value is None or value is pd.NA:
        return None
    try:
        if isinstance(value, str):
            clean = value.strip().lower().replace(",", ".")
            if not clean or clean in {"nan", "none"}:
                return None
            return float(clean)
        if isinstance(value, (int, float)):
            if pd.isna(value):
                return None
            return float(value)
    except Exception:
        return None
    return None


def _service_key(incidente: SLAIncident) -> ServiceKey:
    return (
        incidente.service_id or "",
        incidente.cliente or "",
        incidente.tipo_servicio or "",
    )


def _merge_intervalos(
    incidentes: Sequence[SLAIncident],
    merge_gap_minutes: int,
) -> List[SLAInterval]:
    if not incidentes:
        return []

    incidentes_ordenados = sorted(incidentes, key=lambda inc: inc.inicio)
    intervalos: List[SLAInterval] = []
    gap = pd.Timedelta(minutes=merge_gap_minutes)

    actual: Optional[SLAInterval] = None
    for inc in incidentes_ordenados:
        if actual is None:
            actual = SLAInterval(
                key=_service_key(inc),
                service_id=inc.service_id,
                cliente=inc.cliente,
                tipo_servicio=inc.tipo_servicio,
                inicio=inc.inicio,
                fin=inc.fin,
                incidentes=[inc],
            )
            continue

        if inc.inicio <= actual.fin + gap:
            actual.add(inc)
            continue

        intervalos.append(actual)
        actual = SLAInterval(
            key=_service_key(inc),
            service_id=inc.service_id,
            cliente=inc.cliente,
            tipo_servicio=inc.tipo_servicio,
            inicio=inc.inicio,
            fin=inc.fin,
            incidentes=[inc],
        )

    if actual is not None:
        intervalos.append(actual)

    return intervalos


def _calcular_metricas_servicio(
    key: ServiceKey,
    intervalos: Sequence[SLAInterval],
    horas_periodo: float,
) -> ServiceMetrics:
    downtime = round(sum(intervalo.downtime_h for intervalo in intervalos), 4)
    disponibilidad = 0.0
    if horas_periodo > 0:
        disponibilidad = max(0.0, 100.0 * (1.0 - downtime / horas_periodo))

    incidentes_agrupados = len(intervalos)
    tickets = len({ticket for intervalo in intervalos for ticket in intervalo.incident_ids})

    mttr = None
    if incidentes_agrupados:
        mttr = round(downtime / incidentes_agrupados, 4)

    diffs: List[float] = []
    for anterior, actual in zip(intervalos, intervalos[1:]):
        delta = (actual.inicio - anterior.fin).total_seconds() / 3600
        if delta >= 0:
            diffs.append(round(delta, 4))
    mtbf = round(sum(diffs) / len(diffs), 4) if diffs else None

    servicio_id, cliente, tipo_servicio = key
    servicio_id = servicio_id or intervalos[0].service_id
    cliente = cliente or intervalos[0].cliente
    tipo_servicio = tipo_servicio or intervalos[0].tipo_servicio

    return ServiceMetrics(
        key=key,
        service_id=servicio_id,
        cliente=cliente,
        tipo_servicio=tipo_servicio,
        downtime_h=downtime,
        disponibilidad_pct=round(disponibilidad, 4),
        incidentes_agrupados=incidentes_agrupados,
        tickets_unicos=tickets,
        mttr_h=mttr,
        mtbf_h=mtbf,
        intervals=list(intervalos),
    )


def _calcular_resumen_global(
    servicios: Sequence[ServiceMetrics],
    horas_periodo: float,
    mes: int,
    anio: int,
) -> SLASummary:
    total_servicios = len(servicios)
    total_downtime = round(sum(s.downtime_h for s in servicios), 4)
    total_intervalos = sum(s.incidentes_agrupados for s in servicios)
    total_tickets = sum(s.tickets_unicos for s in servicios)

    disponibilidad = 0.0
    if horas_periodo > 0 and total_servicios:
        horas_disponibles = horas_periodo * total_servicios
        disponibilidad = max(0.0, 100.0 * (1.0 - total_downtime / horas_disponibles))

    intervalos_flat = [intervalo for servicio in servicios for intervalo in servicio.intervals]
    mttr = None
    if intervalos_flat:
        mttr = round(sum(intervalo.downtime_h for intervalo in intervalos_flat) / len(intervalos_flat), 4)

    diffs: List[float] = []
    for servicio in servicios:
        intervalos = servicio.intervals
        for anterior, actual in zip(intervalos, intervalos[1:]):
            delta = (actual.inicio - anterior.fin).total_seconds() / 3600
            if delta >= 0:
                diffs.append(round(delta, 4))
    mtbf = round(sum(diffs) / len(diffs), 4) if diffs else None

    periodo = f"{anio:04d}-{mes:02d}"
    return SLASummary(
        periodo=periodo,
        disponibilidad_pct=round(disponibilidad, 4),
        downtime_total_h=total_downtime,
        servicios=total_servicios,
        incidentes=total_intervalos,
        tickets=total_tickets,
        mttr_h=mttr,
        mtbf_h=mtbf,
    )


def _build_annex_rows(metricas: ServiceMetrics) -> List[dict]:
    filas: List[dict] = []
    for intervalo in metricas.intervals:
        filas.append(
            {
                "service_id": metricas.service_id,
                "cliente": metricas.cliente,
                "tipo_servicio": metricas.tipo_servicio,
                "inicio": intervalo.inicio.isoformat(),
                "fin": intervalo.fin.isoformat(),
                "duracion_h": intervalo.downtime_h,
                "tickets": intervalo.incident_ids,
                "dentro_sla": intervalo.dentro_de_objetivo,
                "causas": intervalo.causas,
                "criticidades": intervalo.criticidades,
            }
        )
    return filas
