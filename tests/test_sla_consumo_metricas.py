# Nombre de archivo: test_sla_consumo_metricas.py
# Ubicación de archivo: tests/test_sla_consumo_metricas.py
# Descripción: Reglas atómicas del informe SLA consumido — causa, indicador, semáforo, estado y porcentajes

from __future__ import annotations

import math

import pytest

from core.sla_consumo import metricas as m
from core.sla_consumo.clasificador import GRUPO_CARRIER, GRUPO_CLIENTE, GRUPO_FO, GRUPO_FO_COD3, GRUPO_OTROS

SLA_26 = 100 * (1 - 26 / 8760)  # presupuesto exacto de 26 h, sólo para fixtures


def test_presupuesto_y_validez():
    assert m.presupuesto_horas(99.7) == pytest.approx(26.28)
    assert m.presupuesto_horas(SLA_26) == pytest.approx(26.0)
    assert m.presupuesto_horas(None) is None
    assert m.presupuesto_valido(26.0) is True
    for invalido in (None, 0.0, float("nan"), float("inf"), -1.0):
        assert m.presupuesto_valido(invalido) is False


@pytest.mark.parametrize("grupo, causa", [
    (GRUPO_FO, m.CAUSA_FO_GENERAL), (GRUPO_FO_COD3, m.CAUSA_FO_COD3), (GRUPO_CARRIER, m.CAUSA_CARRIER),
    (GRUPO_OTROS, m.CAUSA_OTROS), (GRUPO_CLIENTE, None), (None, None),
])
def test_causa_de_grupo(grupo, causa):
    assert m.causa_de_grupo(grupo) == causa


def test_indicador_reclamo_nunca_amarillo():
    assert m.indicador_reclamo(m.CAUSA_FO_GENERAL, 4.0) == m.ROJO
    assert m.indicador_reclamo(m.CAUSA_FO_COD3, 0.5) == m.ROJO
    assert m.indicador_reclamo(m.CAUSA_CARRIER, 1.0) == m.VERDE
    assert m.indicador_reclamo(m.CAUSA_OTROS, 1.0) == m.VERDE
    assert m.indicador_reclamo(m.CAUSA_FO_GENERAL, 0.0) == m.SIN_COLOR
    assert m.indicador_reclamo(None, 5.0) == m.SIN_COLOR


@pytest.mark.parametrize("fo, no_fo, esperado", [
    (4, 0, m.ROJO), (4, 1, m.AMARILLO), (0, 4, m.VERDE), (0, 0, m.SIN_COLOR), (27, 1, m.AMARILLO),
    (2 / 60, 27, m.AMARILLO),
])
def test_semaforo_servicio(fo, no_fo, esperado):
    assert m.semaforo_servicio(fo, no_fo) == esperado


@pytest.mark.parametrize("consumo, presupuesto, esperado", [
    (0.0, 26.0, m.ESTADO_SIN_CONSUMO),
    (4.0, 26.0, m.ESTADO_DENTRO),
    (26.0, 26.0, m.ESTADO_AGOTADO),
    (26.0 + 1e-9, 26.0, m.ESTADO_AGOTADO),       # dentro de la tolerancia
    (28.0, 26.0, m.ESTADO_EXCEDIDO),
    (25.999, 26.0, m.ESTADO_DENTRO),             # no se redondea
    (5.0, None, m.ESTADO_NO_EVALUABLE),
    (0.0, None, m.ESTADO_NO_EVALUABLE),
    (5.0, 0.0, m.ESTADO_NO_EVALUABLE),
])
def test_estado_presupuesto(consumo, presupuesto, esperado):
    assert m.estado_presupuesto(consumo, presupuesto) == esperado


def test_porcentajes():
    assert m.pct_real(28.0, 26.0) == pytest.approx(107.6923, abs=1e-4)
    assert m.pct_visible(107.69) == 100.0
    assert m.pct_visible(50.0) == 50.0
    assert m.pct_real(5.0, None) is None
    assert m.pct_real(5.0, 0.0) is None
    assert m.pct_visible(None) is None
    assert not math.isinf(m.pct_real(5.0, 26.0))
