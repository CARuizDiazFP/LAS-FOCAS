# Nombre de archivo: test_sla_consumo_identidad.py
# Ubicación de archivo: tests/test_sla_consumo_identidad.py
# Descripción: Unificación de servicios por primer servicio y vinculación de reclamos

from __future__ import annotations

import pandas as pd
import pytest

from core.sla_consumo.identidad import unificar_servicios, vincular_reclamos
from core.sla_consumo.parser import RECLAMOS_COLS, SERVICIOS_COLS


def _s(primer, linea, sla, oficial_h=0.0, cliente="C"):
    fila = {c: None for c in SERVICIOS_COLS}
    fila.update(numero_primer_servicio=primer, numero_linea=linea, sla_prometido=sla, nombre_cliente=cliente,
                horas_reclamos_todos=oficial_h, sla_entregado=1 - oficial_h / 8760)
    return fila


def _r(numero, linea, primer):
    fila = {c: None for c in RECLAMOS_COLS}
    fila.update(numero_reclamo=numero, numero_linea=linea, numero_primer_servicio=primer, horas_netas=1.0)
    return fila


def test_mismo_primer_servicio_una_ficha_con_linea_numericamente_mayor():
    servicios = pd.DataFrame([_s("A", "9", 99.0, 5.0), _s("A", "10", 99.7, 7.0), _s(None, "77", 99.5)],
                             columns=SERVICIOS_COLS)
    uni = unificar_servicios(servicios)
    s = uni.servicios.set_index("clave_servicio")
    assert len(s) == 2
    assert s.loc["A", "servicio_id"] == "10"            # "10" > "9" numéricamente
    assert s.loc["A", "lineas_asociadas"] == "9, 10"
    assert s.loc["A", "sla_prometido"] == pytest.approx(99.7)
    assert s.loc["A", "presupuesto_h"] == pytest.approx(26.28)   # un único presupuesto, no sumado
    assert s.loc["A", "horas_reclamos_todos_oficial"] == pytest.approx(7.0)
    assert s.loc["77", "servicio_id"] == "77"            # fallback numero_linea
    assert uni.linea_a_clave == {"9": "A", "10": "A", "77": "77"}


def test_linea_no_numerica_pierde_contra_numerica():
    uni = unificar_servicios(pd.DataFrame([_s("A", "X-1", 99.7), _s("A", "5", 99.0)], columns=SERVICIOS_COLS))
    assert uni.servicios.iloc[0]["servicio_id"] == "5"


def test_vincular_por_primer_servicio_y_fallback_por_linea():
    uni = unificar_servicios(pd.DataFrame([_s("A", "9", 99.7), _s("A", "10", 99.7), _s(None, "77", 99.5)],
                                          columns=SERVICIOS_COLS))
    reclamos = pd.DataFrame([_r("1", "9", "A"), _r("2", "10", "A"), _r("3", "77", None),
                             _r("4", "9", None), _r("5", "555", "ZZ")], columns=RECLAMOS_COLS)
    vinc, no_vinc = vincular_reclamos(reclamos, uni)
    assert dict(zip(vinc["numero_reclamo"], vinc["servicio_id"])) == {"1": "10", "2": "10", "3": "77", "4": "10"}
    assert list(no_vinc["numero_reclamo"]) == ["5"]
    assert "presupuesto_h" in vinc.columns and "presupuesto_h" not in no_vinc.columns
