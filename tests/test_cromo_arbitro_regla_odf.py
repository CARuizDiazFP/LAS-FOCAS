# Nombre de archivo: test_cromo_arbitro_regla_odf.py
# Ubicación de archivo: tests/test_cromo_arbitro_regla_odf.py
# Descripción: Tests puros del puntaje de las reglas ODF_POR_CAMINO y CONTRADICCION_SERVICIO del árbitro

from __future__ import annotations

from collections import namedtuple

import pytest

from core.services.cromo.arbitro.reglas import REGLAS
from core.services.cromo.arbitro.reglas import odf_por_camino as modulo
from core.services.cromo.arbitro.reglas.odf_por_camino import (
    REGLA_CONTRADICCION,
    REGLA_ODF,
    TOPE_SOLO_LOCAL,
    ConectorVisto,
    ReglaContradiccionServicio,
    ReglaOdfPorCamino,
    ServicioCandidato,
    _bfs_conectores,
    _GrafoFusiones,
    puntuar_servicio,
)
from core.services.cromo.arbitro.senales import Alcance, evidencia_hash, puntaje

_SERVICIO = ServicioCandidato(id=7, identidades=frozenset({"1001", "1001-A"}))


def _c(
    odf: int,
    *,
    conector: int | None = None,
    fila: bool = True,
    at62: str | None = None,
    pelo: int | None = 500,
    resuelto: str | None = None,
    vivo: bool = True,
) -> ConectorVisto:
    return ConectorVisto(
        conector_n_id=conector if conector is not None else odf * 10,
        odf_n_id=odf,
        odf_tiene_fila=fila,
        servicio_at62=at62,
        pelo_conectado=pelo,
        servicio_resuelto=resuelto,
        en_vivo=vivo,
    )


def _asociar(evs):
    return [e for e in evs if e.regla == REGLA_ODF]


def _contradicciones(evs):
    return [e for e in evs if e.regla == REGLA_CONTRADICCION]


def test_reglas_registradas():
    codigos = [r.codigo for r in REGLAS]
    assert codigos[:2] == [REGLA_ODF, REGLA_CONTRADICCION]
    assert isinstance(REGLAS[0], ReglaOdfPorCamino)
    assert isinstance(REGLAS[1], ReglaContradiccionServicio)


def test_sin_conectores_no_evalua():
    assert puntuar_servicio(_SERVICIO, [], 5) == []


def test_vivo_completo_con_at62_libre_y_hermanos_da_100():
    evs = puntuar_servicio(_SERVICIO, [_c(20, at62="1001", pelo=501), _c(30)], 20)
    (ev,) = _asociar(evs)
    assert ev.accion == "ASOCIAR_ODF" and ev.objeto_tipo == "SERVICIO" and ev.objeto_id == 7
    assert dict(ev.parametros) == {"odf_n_id": 20, "pelo_n_id": 501, "odfs_extremo": [20, 30]}
    assert {s.codigo for s in ev.senales} == {
        "CAMINO_VIVO_COMPLETO",
        "AT62_COINCIDE",
        "CONECTOR_LIBRE",
        "HERMANOS_COINCIDEN",
        "EXTREMOS_COHERENTES",
    }
    assert ev.tope == 100
    assert puntaje(ev.senales, ev.tope) == 100
    assert _contradicciones(evs) == []


def test_vivo_sin_at62_ni_hermanos_da_60():
    (dos,) = _asociar(puntuar_servicio(_SERVICIO, [_c(20), _c(30)], None))
    assert puntaje(dos.senales, dos.tope) == 60  # 45 + 10 + 5
    (una,) = _asociar(puntuar_servicio(_SERVICIO, [_c(20)], None))
    assert puntaje(una.senales, una.tope) == 55  # sin el segundo extremo no hay coherencia


def test_hermanos_que_no_coinciden_no_suman():
    (ev,) = _asociar(puntuar_servicio(_SERVICIO, [_c(20)], 99))
    assert "HERMANOS_COINCIDEN" not in {s.codigo for s in ev.senales}


def test_solo_local_topa_en_60():
    conectores = [_c(20, at62="1001", vivo=False), _c(30, vivo=False)]
    (ev,) = _asociar(puntuar_servicio(_SERVICIO, conectores, 20))
    codigos = {s.codigo for s in ev.senales}
    assert "FUSIONES_LOCALES" in codigos and "CAMINO_VIVO_COMPLETO" not in codigos
    assert ev.tope == TOPE_SOLO_LOCAL
    assert puntaje(ev.senales, ev.tope) == 60


def test_conector_con_otro_servicio_veta_y_emite_contradiccion():
    conectores = [_c(20, conector=201, at62="1001"), _c(20, conector=202, resuelto="9999")]
    evs = puntuar_servicio(_SERVICIO, conectores, None)
    (contra,) = _contradicciones(evs)
    assert contra.accion == "INFORMAR" and contra.objeto_id == 7
    assert dict(contra.parametros) == {
        "conectores": [{"conector_n_id": 202, "odf_n_id": 20, "servicio_conector": "9999"}]
    }
    assert [(s.codigo, s.peso, dict(s.detalle)) for s in contra.senales] == [
        ("CONECTOR_OTRO_SERVICIO", 0, {"cantidad": 1})
    ]
    (ev,) = _asociar(evs)
    assert ev.parametros["odf_n_id"] == 20
    assert any(s.codigo == "CONECTOR_OTRO_SERVICIO" and s.veto for s in ev.senales)
    assert puntaje(ev.senales, ev.tope) == 0


def test_conector_resuelto_al_mismo_servicio_no_contradice_ni_es_libre():
    evs = puntuar_servicio(_SERVICIO, [_c(20, resuelto="1001-A")], None)
    assert _contradicciones(evs) == []
    (ev,) = _asociar(evs)
    assert "CONECTOR_LIBRE" not in {s.codigo for s in ev.senales}


def test_contradiccion_en_otra_odf_no_veta_la_objetivo():
    evs = puntuar_servicio(_SERVICIO, [_c(20), _c(30, resuelto="9999")], None)
    assert len(_contradicciones(evs)) == 1
    (ev,) = _asociar(evs)
    assert ev.parametros["odf_n_id"] == 20
    assert not any(s.veto for s in ev.senales)


def test_solo_contradicciones_no_propone_odf():
    evs = puntuar_servicio(_SERVICIO, [_c(20, resuelto="9999")], None)
    assert len(_contradicciones(evs)) == 1
    assert _asociar(evs) == []


def test_mas_de_dos_odf_no_propone():
    evs = puntuar_servicio(_SERVICIO, [_c(20), _c(30), _c(40)], None)
    assert _asociar(evs) == []


def test_odf_sin_fila_veta():
    (ev,) = _asociar(puntuar_servicio(_SERVICIO, [_c(20, fila=False)], None))
    assert any(s.codigo == "ODF_SIN_FILA" and s.veto for s in ev.senales)
    assert puntaje(ev.senales, ev.tope) == 0


def test_elige_odf_cuyo_at62_coincide():
    (ev,) = _asociar(puntuar_servicio(_SERVICIO, [_c(20), _c(30, at62="1001-A", pelo=777)], None))
    assert ev.parametros["odf_n_id"] == 30
    assert ev.parametros["pelo_n_id"] == 777
    assert "AT62_COINCIDE" in {s.codigo for s in ev.senales}


def test_sin_at62_elige_menor_odf():
    (ev,) = _asociar(puntuar_servicio(_SERVICIO, [_c(30), _c(20)], None))
    assert ev.parametros["odf_n_id"] == 20
    assert ev.parametros["odfs_extremo"] == [20, 30]


def test_contradiccion_varias_conectores_una_evaluacion():
    conectores = [
        _c(30, conector=302, resuelto="8888"),
        _c(20, conector=202, resuelto="9999"),
        _c(20, conector=201, resuelto="7777"),
    ]
    (contra,) = _contradicciones(puntuar_servicio(_SERVICIO, conectores, None))
    assert contra.parametros["conectores"] == [
        {"conector_n_id": 201, "odf_n_id": 20, "servicio_conector": "7777"},
        {"conector_n_id": 202, "odf_n_id": 20, "servicio_conector": "9999"},
        {"conector_n_id": 302, "odf_n_id": 30, "servicio_conector": "8888"},
    ]
    (senal,) = contra.senales
    assert senal.codigo == "CONECTOR_OTRO_SERVICIO" and dict(senal.detalle) == {"cantidad": 3}


def test_vivo_que_contradice_no_da_confianza_a_otra_odf():
    conectores = [_c(20, vivo=False), _c(30, resuelto="9999", vivo=True)]
    (ev,) = _asociar(puntuar_servicio(_SERVICIO, conectores, None))
    codigos = {s.codigo for s in ev.senales}
    assert ev.parametros["odf_n_id"] == 20
    assert "CAMINO_VIVO_COMPLETO" not in codigos and "FUSIONES_LOCALES" in codigos
    assert ev.tope == TOPE_SOLO_LOCAL


def test_vivo_en_otra_odf_valida_no_da_confianza_a_la_objetivo():
    conectores = [_c(20, at62="1001", vivo=False), _c(30, vivo=True)]
    (ev,) = _asociar(puntuar_servicio(_SERVICIO, conectores, None))
    assert ev.parametros["odf_n_id"] == 20
    assert ev.tope == TOPE_SOLO_LOCAL
    assert "CAMINO_VIVO_COMPLETO" not in {s.codigo for s in ev.senales}


def test_desempate_determinista_mismo_odf():
    conectores = [
        _c(20, conector=205, pelo=601, vivo=False),
        _c(20, conector=203, pelo=602),
        _c(20, conector=201, pelo=603, resuelto="1001"),
        _c(20, conector=204, pelo=604),
        _c(30, conector=301, pelo=605),
    ]
    (a,) = _asociar(puntuar_servicio(_SERVICIO, conectores, None))
    (b,) = _asociar(puntuar_servicio(_SERVICIO, list(reversed(conectores)), None))
    assert a == b and evidencia_hash(a) == evidencia_hash(b)
    # Misma ODF: gana el en vivo, libre y de menor conector.
    assert a.parametros["pelo_n_id"] == 602


def test_resuelto_solo_espacios_es_libre_y_no_contradice():
    evs = puntuar_servicio(_SERVICIO, [_c(20, resuelto="   ")], None)
    assert _contradicciones(evs) == []
    (ev,) = _asociar(evs)
    assert "CONECTOR_LIBRE" in {s.codigo for s in ev.senales}


def test_bfs_truncado_queda_en_la_senal_local():
    servicio = ServicioCandidato(id=7, identidades=_SERVICIO.identidades, bfs_truncado=True)
    (ev,) = _asociar(puntuar_servicio(servicio, [_c(20, vivo=False)], None))
    (local,) = [s for s in ev.senales if s.codigo == "FUSIONES_LOCALES"]
    assert dict(local.detalle) == {"truncado": True}
    (sin,) = _asociar(puntuar_servicio(_SERVICIO, [_c(20, vivo=False)], None))
    (local,) = [s for s in sin.senales if s.codigo == "FUSIONES_LOCALES"]
    assert dict(local.detalle) == {}


def _grafo(aristas):
    g = _GrafoFusiones()
    for a, b in sorted(aristas + [(b, a) for a, b in aristas]):
        g.agregar(a, b)
    return g


def test_grafo_fusiones_vecinos_en_los_bordes():
    g = _grafo([(1, 2), (1, 3), (5, 6)])
    assert list(g.de(1)) == [2, 3]
    assert list(g.de(6)) == [5]  # última clave: el rango termina en len(vecinos)
    assert list(g.de(2)) == [1]
    assert list(g.de(0)) == [] and list(g.de(4)) == [] and list(g.de(99)) == []


def test_bfs_corta_en_el_limite():
    g = _grafo([(1, 2), (2, 3), (3, 4), (4, 5)])
    indice = {5: [(900, 20, None, None)]}
    hallados, truncado = _bfs_conectores([1], g, indice)
    assert hallados == [(5, (900, 20, None, None))] and truncado is False
    hallados, truncado = _bfs_conectores([1], g, indice, limite=3)
    assert hallados == [] and truncado is True


# ─────────────────────────────────────────────────────────────────────────────
# Determinismo, inventario del conector y BFS local
# ─────────────────────────────────────────────────────────────────────────────


def test_parametros_estables_ante_orden_de_conectores():
    a = _c(20, conector=207, pelo=701)
    b = _c(20, conector=202, pelo=702)
    (uno,) = _asociar(puntuar_servicio(_SERVICIO, [a, b], None))
    (otro,) = _asociar(puntuar_servicio(_SERVICIO, [b, a], None))
    assert evidencia_hash(uno) == evidencia_hash(otro)
    assert uno.parametros["pelo_n_id"] == 702  # menor conector_n_id


def test_conector_fuera_de_inventario_no_es_libre():
    ausente = ConectorVisto(
        conector_n_id=201, odf_n_id=20, odf_tiene_fila=True, servicio_at62=None,
        pelo_conectado=500, servicio_resuelto=None, en_vivo=True, en_inventario=False,
    )
    (ev,) = _asociar(puntuar_servicio(_SERVICIO, [ausente], None))
    assert "CONECTOR_LIBRE" not in {s.codigo for s in ev.senales}


# --- `_cargar` con sesión falsa ------------------------------------------------

_FilaUniverso = namedtuple("_FilaUniverso", "id servicio_id numero_primer_servicio alias_ids")
_FilaVivo = namedtuple("_FilaVivo", "servicio_id conector_n_id odf_id servicio_at62 pelo_conectado")


class _Resultado:
    def __init__(self, filas):
        self._filas = list(filas)

    def all(self):
        return self._filas


class _SesionFalsa:
    def __init__(self, vivos=(), semillas=(), odfs=((20, 20),), conectores=()):
        self.respuestas = {
            id(modulo._SQL_UNIVERSO_TODO): [_FilaUniverso(7, "1001", "1001", None)],
            id(modulo._SQL_UNIVERSO_SERVICIOS): [_FilaUniverso(7, "1001", "1001", None)],
            id(modulo._SQL_EXTREMOS_VIVOS): list(vivos),
            id(modulo._SQL_SEMILLAS): list(semillas),
            id(modulo._SQL_RESOLVER_ODFS): list(odfs),
            id(modulo._SQL_CONECTORES_POR_ID): list(conectores),
        }

    async def execute(self, sql, params=None):
        return _Resultado(self.respuestas[id(sql)])


@pytest.fixture
def grafo_espiado(monkeypatch):
    cargas: list[int] = []
    grafo = _grafo([(100, 101), (101, 102)])
    indice = {102: [(902, 20, None, "1001")]}

    async def cargar_grafo(_sesion):
        cargas.append(1)
        return grafo, indice

    async def sin_hermanos(_sesion, _sid):
        return None

    monkeypatch.setattr(modulo, "_cargar_grafo", cargar_grafo)
    monkeypatch.setattr(modulo, "sugerencia_odf_para_servicio", sin_hermanos)
    return cargas


@pytest.mark.asyncio
async def test_carga_todo_conectores_locales_y_grafo_una_vez(grafo_espiado):
    sesion = _SesionFalsa(semillas=[(7, 100)])
    contexto: dict = {}
    (ev,) = await ReglaOdfPorCamino().evaluar(
        sesion, Alcance("TODO"), propios=frozenset(), contexto=contexto
    )
    assert await ReglaContradiccionServicio().evaluar(
        sesion, Alcance("TODO"), propios=frozenset(), contexto=contexto
    ) == []
    # Otro `propios` es otra carga, pero el grafo sigue siendo el mismo.
    await ReglaOdfPorCamino().evaluar(
        sesion, Alcance("TODO"), propios=frozenset({7}), contexto=contexto
    )
    assert grafo_espiado == [1]
    datos = contexto["odf_por_camino"]["cargas"][(Alcance("TODO"), frozenset())]
    (_, (conector,), _) = datos[7]
    assert conector.en_vivo is False
    assert conector.servicio_at62 == "1001"  # servicio_numero_atributo del conector
    assert conector.pelo_conectado == 102 and conector.conector_n_id == 902
    assert ev.parametros["odf_n_id"] == 20 and ev.tope == TOPE_SOLO_LOCAL


@pytest.mark.asyncio
async def test_carga_local_resuelve_odf_por_version_id(monkeypatch, grafo_espiado):
    sesion = _SesionFalsa(semillas=[(7, 100)], odfs=[(77, 20)])  # 20 es el version_id de 77
    (ev,) = await ReglaOdfPorCamino().evaluar(
        sesion, Alcance("TODO"), propios=frozenset(), contexto={}
    )
    assert ev.parametros["odf_n_id"] == 77
    assert "ODF_SIN_FILA" not in {s.codigo for s in ev.senales}


@pytest.mark.asyncio
async def test_alcance_servicios_no_corre_bfs(monkeypatch, grafo_espiado):
    def bfs_prohibido(*_a, **_k):
        raise AssertionError("el BFS local no corre con alcance SERVICIOS")

    monkeypatch.setattr(modulo, "_bfs_por_servicio", bfs_prohibido)
    sesion = _SesionFalsa(
        vivos=[_FilaVivo(7, 905, 20, "1001", 500)], semillas=[(7, 100)], conectores=[(905, None)]
    )
    (ev,) = await ReglaOdfPorCamino().evaluar(
        sesion, Alcance("SERVICIOS", (7,)), propios=frozenset(), contexto={}
    )
    assert grafo_espiado == []
    assert ev.tope == 100
    assert "CONECTOR_LIBRE" in {s.codigo for s in ev.senales}


@pytest.mark.asyncio
async def test_misma_fila_viva_repetida_gana_la_ultima(grafo_espiado):
    # Las filas llegan ORDER BY generado_at: la última es la más nueva.
    sesion = _SesionFalsa(
        vivos=[_FilaVivo(7, 905, 20, None, 500), _FilaVivo(7, 905, 20, "1001", 501)],
        conectores=[(905, None)],
    )
    (ev,) = await ReglaOdfPorCamino().evaluar(
        sesion, Alcance("SERVICIOS", (7,)), propios=frozenset(), contexto={}
    )
    assert ev.parametros["pelo_n_id"] == 501
