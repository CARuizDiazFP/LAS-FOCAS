# Nombre de archivo: test_sla_consumo_parser.py
# Ubicación de archivo: tests/test_sla_consumo_parser.py
# Descripción: Parser de los Excel Servicios/Reclamos del informe SLA consumido (celdas como las reales)

from __future__ import annotations

import datetime as dt
import io

import openpyxl
import pytest

from core.sla_consumo.parser import fecha_corte, parse_reclamos, parse_servicios

RECLAMOS_HEADERS = [
    "Número Reclamo", "Número Evento", "Número Línea Reclamo", "Número Primer Servicio", "Número Línea",
    "Tipo Servicio", "Nombre Cliente", "Fecha Inicio Problema Reclamo", "Fecha Cierre Problema Reclamo",
    "Horas Totales Problema Reclamo", "Horas Indisponibilidad Problema Reclamo",
    "Horas Netas Problema Reclamo", "Horas Netas Escalamientos Carriers", "Sector Responsable Reclamo",
    "Descripción Problema Reclamo", "Tipo Solución Reclamo", "Descripción Solución Reclamo",
    "Carrier Reclamo", "Número Reclamo Carrier",
]
SERVICIOS_HEADERS = [
    "Número Primer Servicio", "Número Línea", "Tipo Servicio", "Nombre Cliente",
    "Horas Carriers Mes", "Horas Reclamos Mes", "Cantidad Reclamos Todos", "Horas Carriers Todos",
    "Horas Reclamos Todos", "Horas Restantes Límite SLA", "SLA Prometido", "SLA \nEntregado", "Abono \nUSD",
]


def _xlsx(headers, filas) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for fila in filas:
        ws.append(fila)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _reclamo(numero, evento="-", linea=76232, netas=dt.datetime(1900, 1, 6, 3, 21, 2), tipo="Carrier",
             inicio=45957.42457175926, cierre=45964.72430555556):
    return [numero, evento, linea, linea, linea, "RPV", "BANCO X", inicio, cierre,
            dt.datetime(1900, 1, 7, 7, 11, 37), dt.datetime(1900, 1, 1, 3, 50, 35), netas,
            dt.time(1, 53, 31), "NOC", "Enlace caído", tipo, "Se normalizó", "TELESPAZIO ARG SA", "jD"]


def test_parse_reclamos_convierte_horas_largas_eventos_y_descarta_totales():
    contenido = _xlsx(RECLAMOS_HEADERS, [
        ["Totales"] + [""] * (len(RECLAMOS_HEADERS) - 1),
        _reclamo(1226756),
        _reclamo(1227405, evento=1229336, linea=94058, netas=dt.time(11, 41, 6),
                 tipo="PE-E-FO Corte en Bandeja (3)"),
        _reclamo(1227405, evento=1229336, linea=94058, netas=dt.time(12, 0, 0),
                 tipo="PE-E-FO Corte en Bandeja (3)"),  # duplicado: gana la última
    ])
    df = parse_reclamos(contenido)
    assert list(df["numero_reclamo"]) == ["1226756", "1227405"]
    fila = df.set_index("numero_reclamo")
    assert fila.loc["1226756", "horas_netas"] == pytest.approx(6 * 24 + 3 + 21 / 60 + 2 / 3600)
    assert fila.loc["1226756", "numero_evento"] is None
    assert fila.loc["1227405", "numero_evento"] == "1229336"
    assert fila.loc["1227405", "horas_netas"] == pytest.approx(12.0)
    assert fila.loc["1227405", "grupo_cierre"] == "FO Cod 3 (Corte en Bandeja)"
    assert fila.loc["1227405", "codigo_cierre"] == 3
    assert fila.loc["1226756", "numero_linea"] == "76232"
    assert fila.loc["1226756", "fecha_inicio"].month == 10  # serial 45957 = 27/10/2025, sin inversión
    assert fecha_corte(df) == dt.date(2025, 11, 3)


def test_parse_reclamos_falta_columna():
    with pytest.raises(ValueError, match="Faltan columnas en reclamos"):
        parse_reclamos(_xlsx(["Número Reclamo"], [[1]]))


def test_parse_servicios_convierte_sla_y_horas():
    contenido = _xlsx(SERVICIOS_HEADERS, [[
        88102, 88102, "RPV", "BANCO MACRO SA", dt.time(0, 0), dt.time(0, 0), 6,
        dt.datetime(1900, 1, 15, 22, 34, 6), dt.datetime(1900, 1, 16, 6, 3, 32), dt.time(0, 0),
        99.7, 0.9554737442922374, 670,
    ]])
    df = parse_servicios(contenido)
    fila = df.iloc[0]
    assert fila["numero_linea"] == "88102"
    assert fila["sla_prometido"] == pytest.approx(99.7)
    assert fila["sla_entregado"] == pytest.approx(0.95547, abs=1e-5)
    assert fila["horas_reclamos_todos"] == pytest.approx(390.0589, abs=1e-3)
    assert 1 - fila["horas_reclamos_todos"] / 8760 == pytest.approx(fila["sla_entregado"], abs=1e-5)
