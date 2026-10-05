# Nombre de archivo: test_sla_consumo_impacto.py
# Ubicación de archivo: tests/test_sla_consumo_impacto.py
# Descripción: Acumulados por servicio e indicadores de impacto Evento × Servicio (casos de aceptación)

from __future__ import annotations

import pandas as pd
import pytest

from core.sla_consumo import metricas as m
from core.sla_consumo.impacto import (INCONS_CARRIER_CON_EVENTO, INCONS_EVENTO_MIXTO, INCONS_NO_EVALUABLE,
                                      INCONS_NO_VINCULADO, acumulados, impacto, inconsistencias, resumen_eventos)
from core.utils.excel_duraciones import TZ_AR

P26 = 26.0


def _c(numero, horas, causa=m.CAUSA_FO_GENERAL, evento=None, clave="A", dia=1, presupuesto=P26):
    return {"clave_servicio": clave, "servicio_id": clave, "presupuesto_h": presupuesto,
            "numero_reclamo": numero, "numero_evento": evento, "causa": causa,
            "horas_computables": horas if causa is not None else 0.0,
            "fecha_inicio": pd.Timestamp(f"2026-09-{dia:02d} 10:00", tz=TZ_AR),
            "fecha_cierre": pd.Timestamp(f"2026-09-{dia:02d} 20:00", tz=TZ_AR)}


def _servicios(acum):
    tot = acum.groupby("clave_servicio").agg(horas_computables=("horas_computables", "sum"),
                                             presupuesto_h=("presupuesto_h", "first")).reset_index()
    tot["servicio_id"] = tot["clave_servicio"]
    tot["nombre_cliente"] = "C"
    tot["estado"] = [m.estado_presupuesto(c, p) for c, p in zip(tot["horas_computables"], tot["presupuesto_h"])]
    return tot


def _ev(filas):
    acum = acumulados(pd.DataFrame(filas))
    return acum, impacto(acum, _servicios(acum), "numero_evento").set_index(["numero_evento", "clave_servicio"])


def test_orden_desempata_por_numero_de_reclamo_numerico():
    acum = acumulados(pd.DataFrame([_c("10", 1), _c("9", 1)]))
    assert list(acum["numero_reclamo"]) == ["9", "10"]
    assert list(acum["consumo_acum_despues"]) == [1.0, 2.0]


def test_acumulado_y_primera_vez():
    acum = acumulados(pd.DataFrame([_c("1", 25, dia=1), _c("2", 2, dia=2), _c("3", 1, dia=3)]))
    f = acum.set_index("numero_reclamo")
    assert f.loc["2", "consumo_acum_antes"] == 25 and f.loc["2", "consumo_acum_despues"] == 27
    assert bool(f.loc["2", "alcanza_primera_vez"]) and bool(f.loc["2", "supera_primera_vez"])
    assert not f.loc["3", "alcanza_primera_vez"] and not f.loc["3", "supera_primera_vez"]
    assert f.loc["3", "excedidas_acum"] == pytest.approx(2.0) and f.loc["3", "restantes_acum"] == 0.0
    assert f.loc["2", "pct_aporte_real"] == pytest.approx(2 / 26 * 100)


def test_evento_27h_suficiente_por_si_solo():
    _, ev = _ev([_c("1", 27, evento="E")])
    fila = ev.loc[("E", "A")]
    assert fila["suficiente_solo"] == "Excede" and bool(fila["cruza_umbral"]) and bool(fila["determinante_al_excluir"])


def test_evento_que_agota_exacto():
    _, ev = _ev([_c("1", 26, evento="E")])
    assert ev.loc[("E", "A"), "suficiente_solo"] == "Agota"


def test_previo_25_mas_evento_2_cruza_y_es_determinante():
    _, ev = _ev([_c("1", 25, dia=1), _c("2", 2, evento="E", dia=2)])
    fila = ev.loc[("E", "A")]
    assert fila["suficiente_solo"] == "No"
    assert bool(fila["cruza_umbral"]) and bool(fila["determinante_al_excluir"])
    assert bool(fila["participa_en_agotado_o_excedido"])


def test_previo_27_mas_evento_2_solo_participa():
    _, ev = _ev([_c("1", 27, dia=1), _c("2", 2, evento="E", dia=2)])
    fila = ev.loc[("E", "A")]
    assert not fila["cruza_umbral"] and not fila["determinante_al_excluir"]
    assert fila["suficiente_solo"] == "No" and bool(fila["participa_en_agotado_o_excedido"])


def test_27_no_fo_mas_evento_fo_de_2_minutos_no_explica_el_agotamiento():
    _, ev = _ev([_c("1", 27, causa=m.CAUSA_CARRIER, dia=1), _c("2", 2 / 60, evento="E", dia=2)])
    fila = ev.loc[("E", "A")]
    assert not fila["cruza_umbral"] and not fila["determinante_al_excluir"] and fila["suficiente_solo"] == "No"


def test_evento_con_horas_cero_o_excluidas_no_tiene_indicadores():
    _, ev = _ev([_c("1", 26, dia=1), _c("2", 5, causa=None, evento="E", dia=2)])
    fila = ev.loc[("E", "A")]
    assert fila["horas_computables"] == 0 and not fila["cruza_umbral"] and not fila["determinante_al_excluir"]


def test_servicio_no_evaluable_sin_indicadores_ni_porcentajes():
    _, ev = _ev([_c("1", 30, evento="E", presupuesto=None)])
    fila = ev.loc[("E", "A")]
    assert fila["suficiente_solo"] == "No evaluable" and pd.isna(fila["pct_aporte_real"])
    assert not fila["cruza_umbral"] and not fila["determinante_al_excluir"]


def test_mismo_evento_en_varias_lineas_del_mismo_servicio_cuenta_un_servicio():
    filas = [_c("1", 10, evento="E", dia=1), _c("2", 10, evento="E", dia=2)]
    filas[1]["servicio_id"] = "A"  # otra línea, mismo servicio unificado (clave A)
    acum, ev = _ev(filas)
    resumen = resumen_eventos(acum, ev.reset_index()).set_index("numero_evento")
    assert resumen.loc["E", "servicios_afectados"] == 1 and resumen.loc["E", "reclamos"] == 2
    assert resumen.loc["E", "horas_servicio"] == pytest.approx(20.0)


def test_reclamos_sin_evento_en_vista_aparte_y_no_son_eventos():
    acum = acumulados(pd.DataFrame([_c("7", 27), _c("8", 1, evento="E", dia=2)]))
    ais = impacto(acum, _servicios(acum), "numero_reclamo")
    assert list(ais["numero_reclamo"]) == ["7"]
    assert ais.iloc[0]["suficiente_solo"] == "Excede"
    assert list(resumen_eventos(acum, impacto(acum, _servicios(acum), "numero_evento"))["numero_evento"]) == ["E"]


def test_inconsistencias():
    acum = acumulados(pd.DataFrame([
        _c("1", 3, causa=m.CAUSA_CARRIER, evento="E1"),
        _c("2", 3, causa=m.CAUSA_FO_GENERAL, evento="E2", clave="B"),
        _c("3", 3, causa=m.CAUSA_OTROS, evento="E2", clave="B", dia=2),
    ]))
    servicios = _servicios(acum)
    servicios.loc[servicios["clave_servicio"] == "B", "estado"] = m.ESTADO_NO_EVALUABLE
    no_vinc = pd.DataFrame([{"numero_reclamo": "9", "numero_evento": None, "numero_linea": "555"}])
    inc = inconsistencias(acum, no_vinc, servicios)
    tipos = inc.groupby("tipo").size().to_dict()
    assert tipos == {INCONS_CARRIER_CON_EVENTO: 1, INCONS_EVENTO_MIXTO: 1, INCONS_NO_VINCULADO: 1,
                     INCONS_NO_EVALUABLE: 1}


def test_previos_agotan_y_el_evento_suma_una_hora():
    """Fallo documentado: P agota solo y es determinante; E cruza el umbral pero no es determinante."""
    _, df = _ev([_c("1", 26, evento="P", dia=1), _c("2", 1, evento="E", dia=2)])
    e, p = df.loc[("E", "A")], df.loc[("P", "A")]
    assert bool(e["cruza_umbral"]) is True and bool(e["determinante_al_excluir"]) is False
    assert p["suficiente_solo"] == "Agota" and bool(p["determinante_al_excluir"]) is True
