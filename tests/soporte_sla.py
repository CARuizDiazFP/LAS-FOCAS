# Nombre de archivo: soporte_sla.py
# Ubicación de archivo: tests/soporte_sla.py
# Descripción: Excel sintéticos de Servicios/Reclamos SLA con los encabezados reales y cálculos vacíos para tests

"""Fixtures compartidos de los tests del informe SLA (P25).

Los encabezados son los del export real (columna P = "Horas Netas Cierre Problema Reclamo", la base del
SLA). Las fechas van como serial de Excel, igual que en los archivos reales.
"""

from __future__ import annotations

import datetime as dt
import io

import openpyxl
from openpyxl.utils.datetime import to_excel

from core.sla.informe import InformeSla, SLAComputation, a_computation

SERVICIOS_HEADERS = ["Número Primer Servicio", "Número Línea", "Tipo Servicio", "Nombre Cliente",
                     "Horas Reclamos Todos", "SLA Prometido", "SLA \nEntregado", "Dirección Servicio"]
RECLAMOS_HEADERS = ["Número Reclamo", "Número Evento", "Número Primer Servicio", "Número Línea", "Tipo Servicio",
                    "Nombre Cliente", "Fecha Inicio Problema Reclamo", "Fecha Cierre Problema Reclamo",
                    "Horas Netas Problema Reclamo", "Horas Netas Cierre Problema Reclamo", "Tipo Solución Reclamo",
                    "Descripción Solución Reclamo"]


def _xlsx(headers: list[str], filas: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for fila in filas:
        ws.append(fila)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def servicio(linea: str, *, cliente: str = "Cliente Test", tipo: str = "Fibra", sla: float = 99.7,
             primer: str | None = None, domicilio: str = "Av. Siempre Viva 742") -> list:
    return [primer or linea, linea, tipo, cliente, dt.time(0, 0), sla, 1.0, domicilio]


def reclamo(numero: str, linea: str, horas_p: dt.time | float, *, inicio: dt.datetime, horas_n: float = 99.0,
            evento: str | None = None, primer: str | None = None, tipo_solucion: str = "Corte de FO",
            cliente: str = "Cliente Test", duracion: dt.timedelta = dt.timedelta(hours=3)) -> list:
    return [numero, evento or "-", primer or linea, linea, "Fibra", cliente, to_excel(inicio),
            to_excel(inicio + duracion), horas_n, horas_p, tipo_solucion, f"Solución {numero}"]


def servicios_excel(filas: list[list] | None = None) -> bytes:
    return _xlsx(SERVICIOS_HEADERS, filas if filas is not None else [servicio("SRV-001"), servicio("SRV-002")])


def reclamos_excel(filas: list[list] | None = None) -> bytes:
    if filas is None:
        filas = [
            reclamo("R-001", "SRV-001", dt.time(1, 30), inicio=dt.datetime(2025, 10, 10, 8, 0)),
            reclamo("R-002", "SRV-001", dt.time(1, 0), inicio=dt.datetime(2025, 10, 15, 14, 30)),
            reclamo("R-003", "SRV-002", dt.time(0, 45), inicio=dt.datetime(2025, 10, 20, 9, 15)),
        ]
    return _xlsx(RECLAMOS_HEADERS, filas)


def computation_vacia(mes: int, anio: int) -> SLAComputation:
    return a_computation(InformeSla(mes, anio, dt.date(anio, mes, 28), "db", []))
