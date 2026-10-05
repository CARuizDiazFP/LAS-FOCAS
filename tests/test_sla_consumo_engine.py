# Nombre de archivo: test_sla_consumo_engine.py
# Ubicación de archivo: tests/test_sla_consumo_engine.py
# Descripción: Casos de aceptación del informe SLA consumido sobre el servicio unificado

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from core.sla_consumo import metricas as m
from core.sla_consumo.engine import calcular, presupuesto_horas
from core.sla_consumo.parser import RECLAMOS_COLS, SERVICIOS_COLS
from core.utils.excel_duraciones import TZ_AR

SLA_26 = 100 * (1 - 26 / 8760)
FO, COD3, CARRIER, OTROS = "PE-I-FO Corte/Aten Troncal Can/Subt (7)", "PE-E-FO Corte en Bandeja (3)", "Carrier", "IN - Falla Equipo CPE"


def _s(linea, sla=SLA_26, primer=None, cliente="CLIENTE"):
    fila = {c: None for c in SERVICIOS_COLS}
    fila.update(numero_linea=linea, numero_primer_servicio=primer or linea, sla_prometido=sla, nombre_cliente=cliente)
    return fila


def _r(numero, linea, horas, tipo=FO, evento=None, dia=1, primer=None):
    fila = {c: None for c in RECLAMOS_COLS}
    fila.update(numero_reclamo=numero, numero_linea=linea, numero_primer_servicio=primer or linea,
                horas_netas=horas, tipo_solucion=tipo, numero_evento=evento, nombre_cliente="CLIENTE",
                fecha_inicio=pd.Timestamp(f"2026-09-{dia:02d} 10:00", tz=TZ_AR),
                fecha_cierre=pd.Timestamp(f"2026-09-{dia:02d} 20:00", tz=TZ_AR))
    return fila


def _calc(servicios, reclamos, monkeypatch=None):
    return calcular(pd.DataFrame(reclamos, columns=RECLAMOS_COLS), pd.DataFrame(servicios, columns=SERVICIOS_COLS),
                    dt.date(2026, 10, 1))


def _svc(res, sid):
    return res.servicios.set_index("servicio_id").loc[sid]


def test_reexporta_presupuesto():
    assert presupuesto_horas(99.7) == pytest.approx(26.28)


@pytest.mark.parametrize("reclamos, semaforo, estado", [
    ([("1", 4, FO)], m.ROJO, m.ESTADO_DENTRO),
    ([("1", 4, FO), ("2", 1, CARRIER)], m.AMARILLO, m.ESTADO_DENTRO),
    ([("1", 4, OTROS)], m.VERDE, m.ESTADO_DENTRO),
    ([("1", 0, FO)], m.SIN_COLOR, m.ESTADO_SIN_CONSUMO),
    ([("1", 26, FO)], m.ROJO, m.ESTADO_AGOTADO),
    ([("1", 27, FO), ("2", 1, CARRIER)], m.AMARILLO, m.ESTADO_EXCEDIDO),
])
def test_semaforo_y_estado(reclamos, semaforo, estado):
    res = _calc([_s("100")], [_r(n, "100", h, t, dia=i + 1) for i, (n, h, t) in enumerate(reclamos)])
    fila = _svc(res, "100")
    assert (fila["semaforo"], fila["estado"]) == (semaforo, estado)


def test_27_fo_mas_1_carrier_visible_100_y_2h_excedidas():
    fila = _svc(_calc([_s("100")], [_r("1", "100", 27, FO), _r("2", "100", 1, CARRIER, dia=2)]), "100")
    assert fila["pct_real"] == pytest.approx(28 / 26 * 100)
    assert fila["pct_visible"] == 100.0 and fila["horas_excedidas"] == pytest.approx(2.0)
    assert fila["horas_restantes"] == 0.0
    assert fila["horas_fo"] == 27 and fila["horas_carrier"] == 1
    assert fila["aporte_fo_pct"] == pytest.approx(27 / 26 * 100)
    assert fila["participacion_fo_pct"] == pytest.approx(27 / 28 * 100)


def test_fo_cod3_cuenta_como_fo_y_se_separa():
    fila = _svc(_calc([_s("100")], [_r("1", "100", 2, COD3), _r("2", "100", 3, FO, dia=2)]), "100")
    assert (fila["horas_fo_cod3"], fila["horas_fo_general"], fila["horas_fo"]) == (2, 3, 5)
    assert fila["semaforo"] == m.ROJO


def test_reclamo_fo_sin_evento_rojo_y_no_suma_eventos():
    res = _calc([_s("100")], [_r("1", "100", 4, FO)])
    rec = res.servicio_reclamo.iloc[0]
    assert rec["indicador"] == m.ROJO and bool(rec["sin_evento"])
    assert res.totales["eventos"] == 0 and res.totales["reclamos_sin_evento"] == 1
    assert _svc(res, "100")["horas_fo"] == 4


def test_reclamo_excluido_o_cero_no_altera_semaforo(monkeypatch):
    monkeypatch.setenv("SLA_CIERRE_CLIENTE_VALORES", "Cierre por cliente")
    res = _calc([_s("100")], [_r("1", "100", 4, CARRIER), _r("2", "100", 9, "Cierre por cliente", dia=2),
                              _r("3", "100", 0, FO, dia=3)])
    fila = _svc(res, "100")
    assert fila["semaforo"] == m.VERDE and fila["horas_excluidas"] == 9 and fila["horas_computables"] == 4
    ind = dict(zip(res.servicio_reclamo["numero_reclamo"], res.servicio_reclamo["indicador"]))
    assert ind == {"1": m.VERDE, "2": m.SIN_COLOR, "3": m.SIN_COLOR}


def test_primer_servicio_con_lineas_9_y_10_una_ficha():
    res = _calc([_s("9", 99.0, primer="A"), _s("10", SLA_26, primer="A")],
                [_r("1", "9", 3, FO, primer="A"), _r("2", "10", 4, CARRIER, dia=2, primer="A")])
    assert list(res.servicios["servicio_id"]) == ["10"]
    fila = _svc(res, "10")
    assert fila["reclamos"] == 2 and fila["presupuesto_h"] == pytest.approx(26.0)
    assert fila["lineas_asociadas"] == "9, 10" and fila["semaforo"] == m.AMARILLO
    assert set(res.servicio_reclamo["servicio_id"]) == {"10"}


def test_servicio_sin_reclamos_incluido_y_no_evaluable_sin_porcentajes():
    res = _calc([_s("100"), _s("200"), _s("300", sla=None)], [_r("1", "300", 5, FO)])
    assert set(res.servicios["servicio_id"]) == {"100", "200", "300"}
    assert _svc(res, "200")["estado"] == m.ESTADO_SIN_CONSUMO and _svc(res, "200")["semaforo"] == m.SIN_COLOR
    ne = _svc(res, "300")
    assert ne["estado"] == m.ESTADO_NO_EVALUABLE and pd.isna(ne["pct_real"]) and pd.isna(ne["horas_excedidas"])
    assert res.totales["servicios_universo"] == 3 and res.totales["servicios_no_evaluables"] == 1


def test_reclamo_no_vinculado_aparte():
    res = _calc([_s("100")], [_r("1", "100", 2, FO), _r("2", "999", 5, FO)])
    assert list(res.no_vinculados["numero_reclamo"]) == ["2"]
    assert res.totales["reclamos_no_vinculados"] == 1 and res.totales["horas_no_vinculadas"] == 5
    assert res.composicion.set_index("causa").loc[m.CAUSA_FO_GENERAL, "horas"] == 2
    assert "2" not in set(res.servicio_reclamo["numero_reclamo"])


def test_evento_en_dos_lineas_mismo_servicio_y_indicadores():
    res = _calc([_s("9", primer="A"), _s("10", primer="A")],
                [_r("1", "9", 25, FO, primer="A"), _r("2", "10", 2, FO, evento="E", dia=2, primer="A"),
                 _r("3", "9", 0.5, FO, evento="E", dia=3, primer="A")])
    ev = res.eventos.set_index("numero_evento").loc["E"]
    assert ev["servicios_afectados"] == 1 and ev["n_cruza_umbral"] == 1 and ev["n_determinante"] == 1
    es = res.evento_servicio.iloc[0]
    assert es["servicio_id"] == "10" and es["horas_computables"] == pytest.approx(2.5)


def test_composicion_global():
    res = _calc([_s("100"), _s("200")], [_r("1", "100", 3, FO), _r("2", "100", 1, COD3, dia=2),
                                          _r("3", "200", 4, CARRIER), _r("4", "200", 2, OTROS, dia=2)])
    comp = res.composicion.set_index("causa")
    assert comp["horas"].sum() == pytest.approx(10) and comp["pct"].sum() == pytest.approx(100)
    assert comp.loc[m.CAUSA_FO_COD3, "pct"] == pytest.approx(10)


def test_totales_json_safe():
    res = _calc([_s("100")], [_r("1", "100", 4, FO)])
    for valor in res.totales.values():
        assert type(valor) in (int, float)
