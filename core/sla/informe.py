# Nombre de archivo: informe.py
# Ubicación de archivo: core/sla/informe.py
# Descripción: Datos del informe SLA mensual (modo Excel y modo base) armados sobre el motor de SLA consumido

"""Informe SLA mensual sobre la pila de SLA consumido (P25).

No calcula: toma de ``core.sla_consumo.engine.calcular`` las horas por servicio (columna P, cierres
Cliente excluidos) y el SLA entregado (1 − horas / 8760 en los 365 días al corte), que coincide con el
"SLA Entregado" oficial. Arma dos cosas:

- ``InformeSla``: los servicios a renderizar en la plantilla (``core/sla/legacy_report.py``).
- ``SLAComputation``: el contrato JSON de ``/api/flows/sla``, ``POST /reports/sla`` y
  ``GET /reports/sla/preview`` (mismas claves que antes de P25; desde P25 ``disponibilidad_pct`` es el
  SLA entregado a 12 meses y ``downtime_h`` son las horas P de esos 12 meses).
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from core.sla_consumo.engine import ResultadoSlaConsumo, calcular
from core.sla_consumo.metricas import HORAS_ANIO
from core.sla_consumo.parser import fecha_corte, leer_domicilios, parse_reclamos, parse_servicios
from core.sla_consumo.persistencia import cargar_ventana_ultima_foto

TZ = "America/Argentina/Buenos_Aires"
COLUMNAS_RECLAMO = ["numero_linea", "numero_reclamo", "numero_evento", "horas_computables", "tipo_solucion",
                    "grupo_cierre", "fecha_inicio", "fecha_cierre", "descripcion_solucion"]


@dataclass
class ServicioInforme:
    servicio_id: str
    linea_visible: str            # línea del primer reclamo vinculado (la que figura en el Excel de reclamos)
    tipo_servicio: Optional[str]
    nombre_cliente: Optional[str]
    domicilio: Optional[str]
    sla_entregado: float          # fracción 0-1 (1 − horas / 8760)
    horas: float                  # horas P computables de la ventana
    reclamos: pd.DataFrame        # COLUMNAS_RECLAMO, por fecha de inicio


@dataclass
class InformeSla:
    mes: int
    anio: int
    fecha_corte: dt.date
    origen: str                   # "excel" o "db"
    servicios: List[ServicioInforme]


@dataclass(slots=True)
class ServiceMetrics:
    service_id: Optional[str]
    cliente: Optional[str]
    tipo_servicio: Optional[str]
    downtime_h: float
    disponibilidad_pct: float
    incidentes_agrupados: int
    tickets_unicos: int
    mttr_h: Optional[float]
    mtbf_h: Optional[float]


@dataclass(slots=True)
class SLASummary:
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
    mes: int
    anio: int
    resumen: SLASummary
    servicios: List[ServiceMetrics]
    anexos: List[dict]
    informe: Optional[InformeSla] = field(default=None)


def _validar_periodo(mes: int, anio: int) -> None:
    if not 1 <= mes <= 12:
        raise ValueError("El mes debe estar entre 1 y 12")
    if anio < 2000:
        raise ValueError("El año debe ser mayor o igual a 2000")


def _servicios(resultado: ResultadoSlaConsumo, claves: Optional[set[str]],
               domicilios: dict[str, str]) -> List[ServicioInforme]:
    svc = resultado.servicios
    if claves is not None:
        svc = svc[svc["clave_servicio"].isin(claves)]
    # Mismo orden que el informe heredado: mayor SLA primero (estable ante empates).
    svc = svc.sort_values("sla_entregado", ascending=False, kind="mergesort", na_position="last")
    por_clave = {clave: g for clave, g in resultado.servicio_reclamo.groupby("clave_servicio", sort=False)}
    salida: List[ServicioInforme] = []
    for fila in svc.itertuples(index=False):
        reclamos = por_clave.get(fila.clave_servicio)
        if reclamos is None:
            reclamos = pd.DataFrame(columns=COLUMNAS_RECLAMO)
        else:
            reclamos = reclamos.sort_values(["fecha_inicio", "numero_reclamo"], kind="mergesort")[COLUMNAS_RECLAMO]
        linea = reclamos["numero_linea"].dropna().iloc[0] if not reclamos.empty else fila.servicio_id
        salida.append(ServicioInforme(
            servicio_id=fila.servicio_id, linea_visible=str(linea), tipo_servicio=fila.tipo_servicio,
            nombre_cliente=fila.nombre_cliente, domicilio=domicilios.get(fila.servicio_id),
            sla_entregado=float(fila.sla_entregado),
            horas=float(fila.horas_computables), reclamos=reclamos.reset_index(drop=True)))
    return salida


def desde_excel(servicios_excel: bytes, reclamos_excel: bytes, *, mes: int, anio: int) -> InformeSla:
    """Par de Excel (Servicios + Reclamos): un servicio por fila del Excel de servicios."""
    _validar_periodo(mes, anio)
    servicios = parse_servicios(servicios_excel)
    reclamos = parse_reclamos(reclamos_excel)
    if reclamos.empty:
        raise ValueError("El Excel de reclamos no tiene filas válidas")
    corte = fecha_corte(reclamos)
    resultado = calcular(reclamos, servicios, corte)
    return InformeSla(mes, anio, corte, "excel", _servicios(resultado, None, leer_domicilios(servicios_excel)))


def _fin_de_mes(mes: int, anio: int) -> dt.date:
    return dt.date(anio, mes, calendar.monthrange(anio, mes)[1])


def _del_mes(reclamos: pd.DataFrame, mes: int, anio: int) -> pd.Series:
    """Mismo criterio que Repetitividad: cierre en el mes, o inicio en el mes si no tiene cierre."""
    inicio = pd.Timestamp(dt.datetime(anio, mes, 1), tz=TZ)
    fin = pd.Timestamp(_fin_de_mes(mes, anio) + dt.timedelta(days=1), tz=TZ)
    cierre, apertura = reclamos["fecha_cierre"], reclamos["fecha_inicio"]
    return ((cierre >= inicio) & (cierre < fin)) | (cierre.isna() & (apertura >= inicio) & (apertura < fin))


def _informe_db(reclamos: pd.DataFrame, servicios: pd.DataFrame, *, mes: int, anio: int) -> InformeSla:
    corte = _fin_de_mes(mes, anio)
    resultado = calcular(reclamos, servicios, corte)
    vinculados = resultado.servicio_reclamo
    claves = set(vinculados.loc[_del_mes(vinculados, mes, anio), "clave_servicio"]) if not vinculados.empty else set()
    return InformeSla(mes, anio, corte, "db", _servicios(resultado, claves, {}))


def desde_db(*, mes: int, anio: int) -> InformeSla:
    """Base: corte al último día del mes, 365 días de reclamos y los servicios con reclamos en el mes."""
    _validar_periodo(mes, anio)
    reclamos, servicios = cargar_ventana_ultima_foto(_fin_de_mes(mes, anio))
    return _informe_db(reclamos, servicios, mes=mes, anio=anio)


def desde_excel_reclamos(reclamos_excel: bytes, *, mes: int, anio: int) -> InformeSla:
    """Un solo Excel (reclamos) contra la última foto de servicios de la base, con el criterio del modo base."""
    _validar_periodo(mes, anio)
    reclamos = parse_reclamos(reclamos_excel)
    if reclamos.empty:
        raise ValueError("El Excel de reclamos no tiene filas válidas")
    _, servicios = cargar_ventana_ultima_foto(_fin_de_mes(mes, anio))
    if servicios.empty:
        raise ValueError("No hay fotos de servicios en la base: subí el par Servicios + Reclamos")
    return _informe_db(reclamos, servicios, mes=mes, anio=anio)


def _incidentes(reclamos: pd.DataFrame) -> int:
    eventos = reclamos["numero_evento"].dropna().nunique()
    return int(eventos + reclamos["numero_evento"].isna().sum())


def _gaps(reclamos: pd.DataFrame) -> List[float]:
    """Horas entre el cierre de un reclamo y el inicio del siguiente del mismo servicio (MTBF)."""
    ordenados = reclamos.sort_values("fecha_inicio", kind="mergesort")
    deltas = (ordenados["fecha_inicio"] - ordenados["fecha_cierre"].shift()).dt.total_seconds() / 3600
    return [round(float(d), 4) for d in deltas.dropna() if d >= 0]


def a_computation(informe: InformeSla) -> SLAComputation:
    metricas: List[ServiceMetrics] = []
    anexos: List[dict] = []
    todos_gaps: List[float] = []
    for s in informe.servicios:
        incidentes = _incidentes(s.reclamos)
        gaps = _gaps(s.reclamos)
        todos_gaps.extend(gaps)
        metricas.append(ServiceMetrics(
            service_id=s.servicio_id, cliente=s.nombre_cliente, tipo_servicio=s.tipo_servicio,
            downtime_h=round(s.horas, 4),
            disponibilidad_pct=round(s.sla_entregado * 100, 4),
            incidentes_agrupados=incidentes, tickets_unicos=int(s.reclamos["numero_reclamo"].nunique()),
            mttr_h=round(s.horas / incidentes, 4) if incidentes else None,
            mtbf_h=round(sum(gaps) / len(gaps), 4) if gaps else None))
        for r in s.reclamos.itertuples(index=False):
            anexos.append({
                "service_id": s.servicio_id, "cliente": s.nombre_cliente, "tipo_servicio": s.tipo_servicio,
                "inicio": None if pd.isna(r.fecha_inicio) else r.fecha_inicio.isoformat(),
                "fin": None if pd.isna(r.fecha_cierre) else r.fecha_cierre.isoformat(),
                "duracion_h": round(float(r.horas_computables), 4), "tickets": [r.numero_reclamo],
                "dentro_sla": None, "causas": [] if r.grupo_cierre is None else [r.grupo_cierre], "criticidades": [],
            })
    n = len(metricas)
    total = round(sum(m.downtime_h for m in metricas), 4)
    incidentes = sum(m.incidentes_agrupados for m in metricas)
    resumen = SLASummary(
        periodo=f"{informe.anio:04d}-{informe.mes:02d}",
        disponibilidad_pct=round(max(0.0, 100.0 * (1 - total / (HORAS_ANIO * n))), 4) if n else 0.0,
        downtime_total_h=total, servicios=n, incidentes=incidentes,
        tickets=sum(m.tickets_unicos for m in metricas),
        mttr_h=round(total / incidentes, 4) if incidentes else None,
        mtbf_h=round(sum(todos_gaps) / len(todos_gaps), 4) if todos_gaps else None)
    return SLAComputation(informe.mes, informe.anio, resumen, metricas, anexos, informe)
