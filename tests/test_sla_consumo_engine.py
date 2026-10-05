# Nombre de archivo: test_sla_consumo_engine.py
# Ubicación de archivo: tests/test_sla_consumo_engine.py
# Descripción: Cálculo de SLA consumido por evento, servicio, reclamo y código de cierre

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from core.sla_consumo.clasificador import GRUPO_CARRIER, GRUPO_CLIENTE, GRUPO_FO, GRUPO_FO_COD3
from core.sla_consumo.engine import calcular, presupuesto_horas
from core.sla_consumo.parser import RECLAMOS_COLS, SERVICIOS_COLS
from core.utils.excel_duraciones import TZ_AR


def _r(numero, linea, horas, grupo, evento=None, cliente="C1"):
    fila = {c: None for c in RECLAMOS_COLS}
    fila.update(numero_reclamo=numero, numero_linea=linea, horas_netas=horas, grupo_cierre=grupo,
                numero_evento=evento, nombre_cliente=cliente, tipo_solucion=grupo,
                fecha_inicio=pd.Timestamp("2026-09-01", tz=TZ_AR), fecha_cierre=pd.Timestamp("2026-09-02", tz=TZ_AR))
    return fila


def _s(linea, prometido, oficial_h):
    fila = {c: None for c in SERVICIOS_COLS}
    fila.update(numero_linea=linea, nombre_cliente="C1", sla_prometido=prometido,
                sla_entregado=1 - oficial_h / 8760, horas_reclamos_todos=oficial_h)
    return fila


@pytest.fixture
def resultado():
    reclamos = pd.DataFrame([
        _r("1", "L1", 13.14, GRUPO_FO, evento="E1"),
        _r("2", "L2", 20.0, GRUPO_FO, evento="E1"),
        _r("3", "L1", 5.0, GRUPO_CARRIER, cliente="BANCO"),
        _r("4", "L1", 4.0, GRUPO_FO_COD3),
        _r("5", "L1", 100.0, GRUPO_CLIENTE),
        _r("6", "L9", 2.0, GRUPO_FO),  # línea sin foto de servicios
    ], columns=RECLAMOS_COLS)
    servicios = pd.DataFrame([_s("L1", 99.7, 22.0), _s("L2", 99.9, 20.0)], columns=SERVICIOS_COLS)
    return calcular(reclamos, servicios, dt.date(2026, 10, 1))


def test_presupuesto():
    assert presupuesto_horas(99.7) == pytest.approx(26.28)
    assert presupuesto_horas(None) is None


def test_hechos_metricas(resultado):
    h = resultado.hechos.set_index("numero_reclamo")
    assert h.loc["1", "pct_presupuesto"] == pytest.approx(50.0)
    assert h.loc["1", "pp_disponibilidad"] == pytest.approx(13.14 / 8760 * 100)
    assert h.loc["5", "horas_sla"] == 0.0 and bool(h.loc["5", "cuenta_sla"]) is False
    assert bool(h.loc["6", "sin_sla_prometido"]) is True and pd.isna(h.loc["6", "pct_presupuesto"])


def test_por_servicio(resultado):
    s = resultado.servicios.set_index("numero_linea")
    assert s.loc["L1", "horas_sla"] == pytest.approx(22.14)
    assert s.loc["L1", "pct_presupuesto"] == pytest.approx(22.14 / 26.28 * 100)
    assert s.loc["L1", "sla_calculado"] == pytest.approx(1 - 22.14 / 8760)
    assert s.loc["L1", "diferencia_horas_oficial"] == pytest.approx(22.14 - 22.0)
    assert bool(s.loc["L2", "excedido"]) is True   # 20 h > 8.76 h de presupuesto
    assert "L9" in s.index


def test_por_evento(resultado):
    e = resultado.eventos.set_index("evento_clave")
    assert e.loc["E1", "servicios_afectados"] == 2
    assert e.loc["E1", "servicios_excedidos"] == 1
    assert e.loc["E1", "horas_sla"] == pytest.approx(33.14)
    assert e.loc["E1", "grupo_predominante"] == GRUPO_FO
    assert bool(e.loc["R-3", "es_aislado"]) is True   # reclamo sin evento = evento propio


def test_codigo_cierre_y_carrier(resultado):
    c = resultado.codigo_cierre.set_index("grupo")
    assert c.loc[GRUPO_FO, "reclamos"] == 3 and c.loc[GRUPO_FO, "eventos"] == 2
    assert c.loc[GRUPO_CLIENTE, "horas_sla"] == 0.0
    assert c["horas"].sum() == pytest.approx(resultado.hechos["horas_netas"].sum())
    assert resultado.carrier_cliente.iloc[0]["nombre_cliente"] == "BANCO"
    assert resultado.totales["reclamos"] == 6


def test_servicios_vacio():
    reclamos = pd.DataFrame([_r("1", "L1", 5.0, GRUPO_FO), _r("2", "L1", 3.0, GRUPO_CARRIER, evento="E1")],
                            columns=RECLAMOS_COLS)
    vacio = pd.DataFrame(columns=SERVICIOS_COLS)
    r = calcular(reclamos, vacio, dt.date(2026, 10, 1))
    assert r.hechos["sin_sla_prometido"].all()
    assert r.hechos["pct_presupuesto"].isna().all()
    s = r.servicios.set_index("numero_linea")
    assert s.loc["L1", "horas_sla"] == pytest.approx(8.0)
    assert pd.isna(s.loc["L1", "pct_presupuesto"]) and bool(s.loc["L1", "excedido"]) is False
    assert r.totales["servicios_excedidos"] == 0
    assert (r.eventos["servicios_excedidos"] == 0).all()
