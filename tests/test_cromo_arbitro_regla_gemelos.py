# Nombre de archivo: test_cromo_arbitro_regla_gemelos.py
# Ubicación de archivo: tests/test_cromo_arbitro_regla_gemelos.py
# Descripción: Tests puros del puntaje de las reglas de gemelos del árbitro (GEMELO_VACIO, GEMELO_OPERATIVO, ODF_GEMELA_ISLA)

from __future__ import annotations

from typing import Optional

import pytest

from core.services.cromo.arbitro.reglas import REGLAS
from core.services.cromo.arbitro.reglas.gemelos import (
    CABLES_DISJUNTOS,
    COMPARTEN_CABLES,
    REGLA_GEMELO_OPERATIVO,
    REGLA_GEMELO_VACIO,
    REGLA_ODF_GEMELA_ISLA,
    MiembroGemelo,
    ReglaGemeloOperativo,
    ReglaGemeloVacio,
    ReglaOdfGemelaIsla,
    distancia_m,
    puntuar_grupo_botellas,
    puntuar_odf_isla,
    senales_de_cercania,
)
from core.services.cromo.arbitro.senales import Alcance, puntaje

# ~0,000009° de latitud ≈ 1 m.
_LAT = -34.6
_LON = -58.4


def _m(
    n_id: int,
    *,
    cables: frozenset[int] = frozenset(),
    fusiones: bool = False,
    lat: Optional[float] = _LAT,
    lon: Optional[float] = _LON,
    localidad: Optional[str] = "CABA",
    camara: Optional[int] = 7,
    isla: bool = False,
    separada: bool = False,
    alias: bool = False,
) -> MiembroGemelo:
    return MiembroGemelo(
        n_id=n_id,
        nombre=f"Bot {n_id}",
        localidad=localidad,
        lat=lat,
        lon=lon,
        camara_id=camara,
        con_cables=bool(cables),
        con_fusiones=fusiones,
        es_isla=isla,
        separada_manualmente=separada,
        alias_previo=alias,
        cables=cables,
    )


def _codigos(ev) -> set[str]:
    return {s.codigo for s in ev.senales}


def test_reglas_registradas_despues_de_las_de_odf():
    codigos = [r.codigo for r in REGLAS]
    assert codigos[2:] == [REGLA_GEMELO_VACIO, REGLA_GEMELO_OPERATIVO, REGLA_ODF_GEMELA_ISLA]
    assert isinstance(REGLAS[2], ReglaGemeloVacio)
    assert isinstance(REGLAS[3], ReglaGemeloOperativo)
    assert isinstance(REGLAS[4], ReglaOdfGemelaIsla)


def test_distancia_haversine_aproximada():
    a = _m(1)
    b = _m(2, lat=_LAT + 0.001)  # ~111 m
    assert distancia_m(a, b) == pytest.approx(111.2, abs=0.5)
    assert distancia_m(a, _m(3, lat=None)) is None


def test_vacia_con_operativa_cerca_misma_localidad_y_camara_da_95():
    op = _m(10, cables=frozenset({100}))
    vacia = _m(20, lat=_LAT + 0.0001, localidad="caba ")  # ~11 m
    evs = puntuar_grupo_botellas([op, vacia])
    assert len(evs) == 1
    ev = evs[0]
    assert ev.regla == REGLA_GEMELO_VACIO
    assert (ev.objeto_tipo, ev.objeto_id, ev.accion) == ("BOTELLA", 20, "FUSIONAR_GEMELO")
    assert dict(ev.parametros) == {"origen": 20, "destino": 10}
    assert _codigos(ev) == {"VACIA_SIN_FUSIONES", "MISMA_LOCALIDAD", "CERCA_50M", "MISMA_CAMARA"}
    assert puntaje(ev.senales) == 95


def test_vacia_entre_50_y_300m_suma_menos():
    op = _m(10, cables=frozenset({100}))
    vacia = _m(20, lat=_LAT + 0.001)  # ~111 m
    (ev,) = puntuar_grupo_botellas([op, vacia])
    assert "CERCA_300M" in _codigos(ev)
    assert puntaje(ev.senales) == 30 + 20 + 10 + 15


def test_vacia_lejos_300m_veta():
    op = _m(10, cables=frozenset({100}))
    vacia = _m(20, lat=_LAT + 0.01)  # ~1,1 km
    (ev,) = puntuar_grupo_botellas([op, vacia])
    assert any(s.codigo == "LEJOS_300M" and s.veto for s in ev.senales)
    assert puntaje(ev.senales) == 0


@pytest.mark.parametrize("en_vacia", [True, False])
def test_separada_manual_veta(en_vacia):
    op = _m(10, cables=frozenset({100}), separada=not en_vacia)
    vacia = _m(20, separada=en_vacia)
    (ev,) = puntuar_grupo_botellas([op, vacia])
    assert any(s.codigo == "SEPARADA_MANUAL" and s.veto for s in ev.senales)
    assert puntaje(ev.senales) == 0


@pytest.mark.parametrize("en_vacia", [True, False])
def test_alias_previo_veta(en_vacia):
    op = _m(10, cables=frozenset({100}), alias=not en_vacia)
    vacia = _m(20, alias=en_vacia)
    (ev,) = puntuar_grupo_botellas([op, vacia])
    assert any(s.codigo == "ALIAS_PREVIO" and s.veto for s in ev.senales)


def test_con_fusiones_no_es_vacia():
    op = _m(10, cables=frozenset({100}))
    assert puntuar_grupo_botellas([op, _m(20, fusiones=True)]) == []


def test_sin_operativa_no_evalua():
    assert puntuar_grupo_botellas([_m(10), _m(20)]) == []


def test_isla_con_operativa_informa_no_fusiona():
    op = _m(10, cables=frozenset({100}))
    isla = _m(20, isla=True)
    (ev,) = puntuar_grupo_botellas([op, isla])
    assert ev.regla == REGLA_GEMELO_VACIO
    assert (ev.objeto_id, ev.accion) == (20, "INFORMAR")
    assert dict(ev.parametros) == {"origen": 20, "destino": 10}


def test_isla_con_fusiones_tambien_informa():
    op = _m(10, cables=frozenset({100}))
    (ev,) = puntuar_grupo_botellas([op, _m(20, isla=True, fusiones=True)])
    assert ev.accion == "INFORMAR"
    assert "VACIA_SIN_FUSIONES" not in _codigos(ev)


def test_dos_operativas_comparten_cables_informa_operativo():
    a = _m(30, cables=frozenset({1, 2}))
    b = _m(10, cables=frozenset({2, 3}))
    evs = puntuar_grupo_botellas([a, b, _m(50)])
    assert [e.regla for e in evs] == [REGLA_GEMELO_OPERATIVO]
    ev = evs[0]
    assert (ev.objeto_tipo, ev.objeto_id, ev.accion) == ("BOTELLA", 10, "INFORMAR")
    assert dict(ev.parametros) == {"miembros": [10, 30]}
    assert "COMPARTEN_CABLES" in _codigos(ev)
    assert puntaje(ev.senales) == min(100, COMPARTEN_CABLES + 20 + 30 + 15)


def test_dos_operativas_disjuntas_resta():
    a = _m(10, cables=frozenset({1}))
    b = _m(30, cables=frozenset({2}))
    (ev,) = puntuar_grupo_botellas([a, b])
    assert "CABLES_DISJUNTOS" in _codigos(ev)
    assert puntaje(ev.senales) == CABLES_DISJUNTOS + 20 + 30 + 15


def test_operativa_isla_y_otra_no_isla_informa_la_isla():
    a = _m(10, cables=frozenset({1}))
    b = _m(30, cables=frozenset({2}), isla=True)
    evs = puntuar_grupo_botellas([a, b])
    reglas = sorted((e.regla, e.objeto_id, e.accion) for e in evs)
    assert reglas == [(REGLA_GEMELO_OPERATIVO, 10, "INFORMAR"), (REGLA_GEMELO_VACIO, 30, "INFORMAR")]


def test_sin_coordenadas_no_emite_distancia():
    op = _m(10, cables=frozenset({100}), lat=None, localidad=None, camara=None)
    vacia = _m(20, localidad=None, camara=None)
    (ev,) = puntuar_grupo_botellas([op, vacia])
    assert _codigos(ev) == {"VACIA_SIN_FUSIONES"}
    assert senales_de_cercania(op, vacia) == []


def test_odf_isla_con_gemela_informa():
    isla = _m(70, isla=True, camara=None)
    gemela = _m(80, lat=_LAT + 0.0001, camara=None)
    ev = puntuar_odf_isla(isla, gemela)
    assert ev.regla == REGLA_ODF_GEMELA_ISLA
    assert (ev.objeto_tipo, ev.objeto_id, ev.accion) == ("ODF", 70, "INFORMAR")
    assert dict(ev.parametros) == {"isla": 70, "gemela": 80}
    assert _codigos(ev) == {"MISMA_LOCALIDAD", "CERCA_50M"}


@pytest.mark.asyncio
async def test_alcance_servicios_devuelve_vacio():
    for regla in (ReglaGemeloVacio(), ReglaGemeloOperativo(), ReglaOdfGemelaIsla()):
        assert await regla.evaluar(None, Alcance("SERVICIOS", (1,)), propios=frozenset(), contexto={}) == []
