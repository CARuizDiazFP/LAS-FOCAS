# Nombre de archivo: test_cromo_pelo_servicios.py
# Ubicación de archivo: tests/test_cromo_pelo_servicios.py
# Descripción: Pruebas de la regla pura de prioridad de fuentes de servicio por pelo (at.61 > conector ODF > at.62 del pelo)

from __future__ import annotations

from core.services.cromo.pelo_servicios import (
    METODO_ATRIBUTO_CONECTOR,
    METODO_ATRIBUTO_PELO,
    METODO_REGEX,
    PeloAtributos,
    resolver_servicios_de_cable,
)


def _pelo(n_id, raw=None, at62=None, at63=None):
    return PeloAtributos(n_id=n_id, servicio_raw=raw, servicio_atributo=at62, estado_cromo=at63)


# Los pelos reales de F-PE-AL-99 (cable 6599543) según `/inner` del 2026-09-30.
PELOS_F_PE_AL_99 = [
    _pelo(1, "TLS 116548 - CREDICOOP COMPAÃ\x91IA DE SEGUROS DE RETIRO SA", "116548", "Utilizado"),
    _pelo(2, "OLT1_Chacabuco-S2-L1", "120893", "Utilizado"),
    _pelo(4, "ATENUADO 2 DB A LOS 60 MTS", "116548"),
    _pelo(5, "ATENUADO 2 DB A LOS 59 MTS DESDE ALSINA 699 BOT 2"),
    _pelo(29, "Dañado - F-PIE-ALS", "0", "Dañado"),
    _pelo(30, "PON Mz 02-025", "0", "Utilizado"),
    _pelo(32, "Mz 002-025 IAAS TECO P2", "56747", "Utilizado"),
    _pelo(33),
    _pelo(61, "LIBRE", "0", "Libre"),
]


def test_caso_real_f_pe_al_99():
    r = resolver_servicios_de_cable(PELOS_F_PE_AL_99, conector_at62_por_pelo={})
    assert r[1] == [("116548", METODO_REGEX)]
    assert r[2] == [("120893", METODO_ATRIBUTO_PELO)]
    assert r[32] == [("56747", METODO_ATRIBUTO_PELO)]
    # Pelo 4: servicio migrado al pelo 1 (texto "ATENUADO" y el número ya está ubicado en el cable).
    assert r[4] == []
    for n_id in (5, 29, 30, 33, 61):
        assert r[n_id] == [], n_id


def test_texto_del_pelo_gana_sobre_los_atributos():
    r = resolver_servicios_de_cable([_pelo(1, "FO 114830 - EDGE", "99999")], conector_at62_por_pelo={1: "88888"})
    assert r[1] == [("114830", METODO_REGEX)]


def test_conector_de_odf_gana_sobre_el_at62_del_pelo():
    r = resolver_servicios_de_cable([_pelo(1, "sin numero", "99999")], conector_at62_por_pelo={1: "88888"})
    assert r[1] == [("88888", METODO_ATRIBUTO_CONECTOR)]


def test_conector_de_odf_en_cero_cae_al_at62_del_pelo():
    r = resolver_servicios_de_cable([_pelo(1, None, "99999")], conector_at62_por_pelo={1: "0"})
    assert r[1] == [("99999", METODO_ATRIBUTO_PELO)]


def test_pelo_fuera_de_uso_no_toma_atributos():
    for raw in ("CORTADO A LOS 60 MTS", "Dañado", "DANADO", "ATENUADO 5 DB", "LIBRE", "RESERVA"):
        r = resolver_servicios_de_cable([_pelo(1, raw, "99999")], conector_at62_por_pelo={1: "88888"})
        assert r[1] == [], raw


def test_estado_cromo_danado_o_libre_bloquea_atributos():
    for estado in ("Dañado", "Libre", "LIBRE"):
        r = resolver_servicios_de_cable([_pelo(1, None, "99999", estado)], conector_at62_por_pelo={1: "88888"})
        assert r[1] == [], estado


def test_at62_del_pelo_ya_ubicado_en_otro_pelo_por_conector_se_descarta():
    r = resolver_servicios_de_cable(
        [_pelo(1, None, None), _pelo(2, None, "88888")], conector_at62_por_pelo={1: "88888"}
    )
    assert r[1] == [("88888", METODO_ATRIBUTO_CONECTOR)]
    assert r[2] == []


def test_at62_no_numerico_se_ignora():
    r = resolver_servicios_de_cable([_pelo(1, None, "abc"), _pelo(2, None, " ")], conector_at62_por_pelo={})
    assert r == {1: [], 2: []}
