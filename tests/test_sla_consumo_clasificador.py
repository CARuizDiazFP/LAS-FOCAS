# Nombre de archivo: test_sla_consumo_clasificador.py
# Ubicación de archivo: tests/test_sla_consumo_clasificador.py
# Descripción: Agrupación de Tipo Solución Reclamo en los grupos del informe SLA consumido

from __future__ import annotations

import pytest

from core.sla_consumo.clasificador import (
    GRUPO_CARRIER, GRUPO_CLIENTE, GRUPO_FO, GRUPO_FO_COD3, GRUPO_OTROS,
    clasificar_cierre, valores_cliente_config,
)

# Valores reales observados en Reclamos_Nuevo SLA.xlsx (2026-10-05), incluidos los truncados.
CASOS = [
    ("PE-I-FO Corte/Aten Troncal Can/Subt (7)", GRUPO_FO, 7),
    ("PE-I-FO Corte/Atenuacion Troncal Aereo (vand.) (91", GRUPO_FO, 91),
    ("PE-E-FO Corte en Bandeja (3)", GRUPO_FO_COD3, 3),
    ("PE-E-FO Corte Empalme (2)", GRUPO_FO, 2),
    ("PE-I Error Manipulacion de Instaladores (12)", GRUPO_FO, 12),
    ("PE-E-Error de documentacion en red On Net (18)", GRUPO_FO, 18),
    ("Carrier", GRUPO_CARRIER, None),
    ("  carrier ", GRUPO_CARRIER, None),
    ("IN - Falla Equipo CPE", GRUPO_OTROS, None),
    ("OP-conf-asegured", GRUPO_OTROS, None),
    ("TE - Falla Carrier", GRUPO_OTROS, None),
    ("DC - Reset/Configuración VM", GRUPO_OTROS, None),
    ("Problema Masivo  - Contingencia Metrotel", GRUPO_OTROS, None),
    (None, GRUPO_OTROS, None),
    ("-", GRUPO_OTROS, None),
]


@pytest.mark.parametrize("tipo, grupo, codigo", CASOS)
def test_clasificar_cierre(tipo, grupo, codigo):
    cierre = clasificar_cierre(tipo, frozenset())
    assert (cierre.grupo, cierre.codigo, cierre.cuenta_sla) == (grupo, codigo, True)


def test_cierre_cliente_configurable_no_cuenta_sla(monkeypatch):
    monkeypatch.setenv("SLA_CIERRE_CLIENTE_VALORES", "Cliente; CL - Falla en sitio del cliente")
    valores = valores_cliente_config()
    cierre = clasificar_cierre("cl - falla en sitio del CLIENTE", valores)
    assert cierre.grupo == GRUPO_CLIENTE
    assert cierre.cuenta_sla is False
    assert clasificar_cierre("Carrier", valores).grupo == GRUPO_CARRIER


def test_sin_config_cliente_vacio(monkeypatch):
    monkeypatch.delenv("SLA_CIERRE_CLIENTE_VALORES", raising=False)
    assert valores_cliente_config() == frozenset()
