# Nombre de archivo: preview.py
# Ubicación de archivo: core/sla/preview.py
# Descripción: Construcción de payloads JSON para UI SLA
"""Construcción de payloads JSON para SLA."""

from __future__ import annotations

from typing import Iterable, Optional

from .engine import SLAComputation, ServiceMetrics


def construir_preview(
    resultado: SLAComputation,
    *,
    cliente: Optional[str] = None,
    servicio: Optional[str] = None,
    service_id: Optional[str] = None,
) -> dict:
    """Arma la respuesta JSON para la UI de preview."""

    servicios = _filtrar_servicios(resultado.servicios, cliente, servicio, service_id)
    anexos = _filtrar_anexos(resultado.anexos, servicios)

    return {
        "periodo": resultado.resumen.periodo,
        "resumen": {
            "disponibilidad_pct": resultado.resumen.disponibilidad_pct,
            "downtime_total_h": resultado.resumen.downtime_total_h,
            "downtime_total_hhmm": _hours_to_hhmm(resultado.resumen.downtime_total_h),
            "servicios": resultado.resumen.servicios,
            "incidentes": resultado.resumen.incidentes,
            "tickets": resultado.resumen.tickets,
            "mttr_h": resultado.resumen.mttr_h,
            "mtbf_h": resultado.resumen.mtbf_h,
        },
        "servicios": [
            {
                "service_id": metr.service_id,
                "cliente": metr.cliente,
                "tipo_servicio": metr.tipo_servicio,
                "disponibilidad_pct": metr.disponibilidad_pct,
                "downtime_h": metr.downtime_h,
                "downtime_hhmm": _hours_to_hhmm(metr.downtime_h),
                "incidentes_agrupados": metr.incidentes_agrupados,
                "tickets_unicos": metr.tickets_unicos,
                "mttr_h": metr.mttr_h,
                "mtbf_h": metr.mtbf_h,
            }
            for metr in servicios
        ],
        "anexo": anexos,
    }


def _filtrar_servicios(
    servicios: Iterable[ServiceMetrics],
    cliente: Optional[str],
    servicio: Optional[str],
    service_id: Optional[str],
) -> list[ServiceMetrics]:
    cliente_norm = cliente.lower() if cliente else None
    servicio_norm = servicio.lower() if servicio else None
    service_id_norm = service_id.lower() if service_id else None

    filtrados: list[ServiceMetrics] = []
    for metr in servicios:
        if cliente_norm and (metr.cliente or "").lower() != cliente_norm:
            continue
        if service_id_norm and (metr.service_id or "").lower() != service_id_norm:
            continue
        if servicio_norm:
            tipo = (metr.tipo_servicio or metr.service_id or "").lower()
            if servicio_norm not in tipo:
                continue
        filtrados.append(metr)
    return filtrados


def _filtrar_anexos(anexos: list[dict], servicios_filtrados: Iterable[ServiceMetrics]) -> list[dict]:
    if not anexos:
        return []
    claves = {
        (metr.service_id or "", metr.cliente or "", metr.tipo_servicio or "")
        for metr in servicios_filtrados
    }
    if not claves:
        return list(anexos)

    filtrados = []
    for fila in anexos:
        clave = (
            (fila.get("service_id") or ""),
            (fila.get("cliente") or ""),
            (fila.get("tipo_servicio") or ""),
        )
        if clave in claves:
            filtrados.append(fila)
    return filtrados


def _hours_to_hhmm(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    total_minutos = int(round(value * 60))
    horas, minutos = divmod(total_minutos, 60)
    return f"{horas:02d}:{minutos:02d}"
