# Nombre de archivo: test_cromo_arbitro_regla_odf.py
# Ubicación de archivo: tests/test_cromo_arbitro_regla_odf.py
# Descripción: Tests puros del puntaje de las reglas ODF_POR_CAMINO y CONTRADICCION_SERVICIO del árbitro

from __future__ import annotations

from core.services.cromo.arbitro.reglas import REGLAS
from core.services.cromo.arbitro.reglas.odf_por_camino import (
    REGLA_CONTRADICCION,
    REGLA_ODF,
    TOPE_SOLO_LOCAL,
    ConectorVisto,
    ReglaContradiccionServicio,
    ReglaOdfPorCamino,
    ServicioCandidato,
    puntuar_servicio,
)
from core.services.cromo.arbitro.senales import puntaje

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
