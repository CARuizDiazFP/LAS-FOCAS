# Nombre de archivo: test_cromo_arbitro_senales.py
# Ubicación de archivo: tests/test_cromo_arbitro_senales.py
# Descripción: Tests del núcleo puro del árbitro de Cromo (puntaje, hash de evidencia, alcance)

from __future__ import annotations

import pytest

from core.services.cromo.arbitro.senales import (
    Alcance,
    Evaluacion,
    Senal,
    evidencia_hash,
    puntaje,
)


def _s(*pesos: int) -> list[Senal]:
    return [Senal(f"S{i}", p) for i, p in enumerate(pesos)]


def test_puntaje_suma_y_recorta():
    assert puntaje(_s(45, 25, 10, 15, 5)) == 100
    assert puntaje(_s(45, 25, 10, 15, 5, 20)) == 100


def test_puntaje_respeta_tope():
    assert puntaje(_s(45, 10, 10), tope=60) == 60


def test_puntaje_veto_da_cero():
    assert puntaje([Senal("A", 45), Senal("X", 0, veto=True)]) == 0


def test_puntaje_negativo_no_baja_de_cero():
    assert puntaje(_s(10, -30)) == 0


def _ev(odf: int, senales: list[Senal]) -> Evaluacion:
    return Evaluacion(
        regla="R",
        objeto_tipo="SERVICIO",
        objeto_id=7,
        accion="ASOCIAR_ODF",
        parametros={"odf_id": odf},
        senales=tuple(senales),
    )


def test_hash_estable_ante_orden_de_senales():
    a = Senal("A", 10, {"x": 1})
    b = Senal("B", 20)
    assert evidencia_hash(_ev(1, [a, b])) == evidencia_hash(_ev(1, [b, a]))


def test_hash_cambia_con_parametros():
    s = [Senal("A", 10)]
    assert evidencia_hash(_ev(1, s)) != evidencia_hash(_ev(2, s))


def test_alcance_cubre():
    assert Alcance("TODO").cubre("BOTELLA", 99)
    a = Alcance("SERVICIOS", (5,))
    assert a.cubre("SERVICIO", 5)
    assert not a.cubre("BOTELLA", 5)
    assert not a.cubre("SERVICIO", 6)


def test_alcance_round_trip():
    a = Alcance("ODFS", (1, 2))
    d = a.a_dict()
    assert d == {"tipo": "ODFS", "ids": [1, 2]}
    assert Alcance.desde_dict(d) == a
    assert Alcance.desde_dict(Alcance("TODO").a_dict()) == Alcance("TODO")


def test_alcance_desde_dict_invalido():
    with pytest.raises(ValueError):
        Alcance.desde_dict({"tipo": "X"})
    with pytest.raises(ValueError):
        Alcance.desde_dict({"tipo": "ODFS", "ids": ["a"]})
