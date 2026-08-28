# Nombre de archivo: test_tracking_parser.py
# Ubicación de archivo: tests/test_tracking_parser.py
# Descripción: Tests de regresión para core/parsers/tracking_parser.py — hasta ahora sin
# ninguna cobertura pese a ser código productivo crítico para el nuevo endpoint de ODFs
# de tracking en Detalle de Servicio (Task 7). No modifica tracking_parser.py: sólo
# protege el comportamiento real ya existente contra cambios accidentales futuros.
#
# Fixture armada con ejemplos literales reales verificados en el brief de la tarea:
# "O-1247501-5: 112", "Patch 6646670: Nodo Dixon", "F-GP-25M: 136 (CE / 12 - 4)",
# "Empalme 6633037: ...".

from core.parsers.tracking_parser import (
    TrackingEntry,
    TrackingParseResult,
    extract_alias_id,
    extract_cantidad_pelos,
    extract_odf_terminal,
    extract_pelo_conector,
    extract_servicio_id,
    extract_tracking_terminals,
    is_transito,
    iter_empalmes,
    iter_tramos,
    parse_punta,
    parse_tracking,
    parse_tracking_as_dicts,
    parse_tracking_entries,
)

# Combina literalmente los dos fragmentos del brief en una sola línea de empalme:
# "Empalme 6633037: ..." + "Patch 6646670: Nodo Dixon" -> línea real de tránsito
# (contiene la keyword "NODO").
LINEA_EMPALME_TRANSITO = "Empalme 6633037: Patch 6646670: Nodo Dixon"
LINEA_TERMINAL_ODF_A = "O-1247501-5: 112"
LINEA_NO_MATCHEA_NADA = "F-GP-25M: 136 (CE / 12 - 4)"
LINEA_EMPALME_SIMPLE = "Empalme 100: CAMARA Retiro"
LINEA_TRAMO_CON_DB = "F-CABLE-1: enlace 7.5 dB"
LINEA_TERMINAL_ODF_B = "ODF DWDM 91719: 15"

FIXTURE_TRACKING = "\n".join(
    [
        "2 Pelos",
        "Punta A: O-1247501-5: 112",
        LINEA_TERMINAL_ODF_A,
        LINEA_EMPALME_TRANSITO,
        LINEA_NO_MATCHEA_NADA,
        LINEA_EMPALME_SIMPLE,
        LINEA_TRAMO_CON_DB,
        "Punta B: ODF DWDM 91719: 15",
        LINEA_TERMINAL_ODF_B,
    ]
)

FIXTURE_FILENAME = "FO 111995 C2.txt"


# ---------------------------------------------------------------------------
# Funciones de extracción a partir del nombre de archivo
# ---------------------------------------------------------------------------


def test_extract_servicio_id_variantes():
    assert extract_servicio_id("FO 111995 C2.txt") == "111995"
    assert extract_servicio_id("FO111995.txt") == "111995"
    assert extract_servicio_id("111995_backup.txt") == "111995"
    assert extract_servicio_id("tracking_servicio_999999.txt") == "999999"
    assert extract_servicio_id("sin_digitos.txt") is None


def test_extract_alias_id_variantes():
    assert extract_alias_id("52547 O1C1.txt") == "O1C1"
    assert extract_alias_id("91710 C1.txt") == "C1"
    assert extract_alias_id("3601 C2.txt") == "C2"
    assert extract_alias_id("sin_alias.txt") is None


# ---------------------------------------------------------------------------
# is_transito / keywords de tránsito
# ---------------------------------------------------------------------------


def test_is_transito_detecta_keywords():
    assert is_transito("Patch 6646670: Nodo Dixon") is True
    assert is_transito("ODF Retiro Bandeja 3") is True
    assert is_transito("RACK 1 BANDEJA 2") is True
    assert is_transito("DISTRIBUIDOR Principal") is True
    assert is_transito("DDF Central") is True


def test_is_transito_false_para_empalme_simple():
    assert is_transito("CAMARA Retiro") is False
    assert is_transito("Empalme físico entre cables") is False


# ---------------------------------------------------------------------------
# extract_pelo_conector / extract_cantidad_pelos
# ---------------------------------------------------------------------------


def test_extract_pelo_conector_formatos_soportados():
    assert extract_pelo_conector("P09-C10") == "P09-C10"
    assert extract_pelo_conector("Pelo 9 Conector 10") == "P09-C10"
    assert extract_pelo_conector("P-09/C-10") == "P09-C10"
    assert extract_pelo_conector("sin referencia") is None


def test_extract_cantidad_pelos():
    assert extract_cantidad_pelos("2 Pelos") == 2
    assert extract_cantidad_pelos("Cantidad: 12 Pelos totales") == 12
    assert extract_cantidad_pelos("sin mención") is None


# ---------------------------------------------------------------------------
# extract_odf_terminal / extract_tracking_terminals (terminal_a / terminal_b)
# ---------------------------------------------------------------------------


def test_extract_odf_terminal_formato_o_guion():
    assert extract_odf_terminal(LINEA_TERMINAL_ODF_A) == ("O-1247501-5", "112")


def test_extract_odf_terminal_formato_odf_nombre():
    assert extract_odf_terminal(LINEA_TERMINAL_ODF_B) == ("ODF DWDM 91719", "15")


def test_extract_odf_terminal_none_si_no_matchea():
    assert extract_odf_terminal(LINEA_NO_MATCHEA_NADA) is None
    assert extract_odf_terminal(LINEA_EMPALME_TRANSITO) is None


def test_extract_tracking_terminals_primero_y_ultimo():
    terminal_a, terminal_b = extract_tracking_terminals(FIXTURE_TRACKING)
    assert terminal_a == ("O-1247501-5", "112")
    assert terminal_b == ("ODF DWDM 91719", "15")


def test_extract_tracking_terminals_sin_odf_da_none():
    terminal_a, terminal_b = extract_tracking_terminals("Empalme 1: CAMARA Sin ODF\nF-X: 1 dB")
    assert terminal_a is None
    assert terminal_b is None


# ---------------------------------------------------------------------------
# parse_punta
# ---------------------------------------------------------------------------


def test_parse_punta_formato_odf_conector():
    punta = parse_punta("Punta A: O-1247501-5: 112")
    assert punta is not None
    assert punta.tipo == "A"
    assert punta.sitio_descripcion == "O-1247501-5"
    assert punta.pelo_conector == "112"


def test_parse_punta_none_si_no_matchea():
    assert parse_punta(LINEA_EMPALME_TRANSITO) is None


# ---------------------------------------------------------------------------
# parse_tracking — comportamiento integral sobre la fixture realista
# ---------------------------------------------------------------------------


def test_parse_tracking_extrae_servicio_y_alias_desde_filename():
    resultado = parse_tracking(FIXTURE_TRACKING, FIXTURE_FILENAME)
    assert resultado.servicio_id == "111995"
    assert resultado.alias_id == "C2"
    assert resultado.nombre_archivo == FIXTURE_FILENAME


def test_parse_tracking_sin_filename_no_extrae_servicio_ni_alias():
    resultado = parse_tracking(FIXTURE_TRACKING)
    assert resultado.servicio_id is None
    assert resultado.alias_id is None


def test_parse_tracking_cantidad_pelos():
    resultado = parse_tracking(FIXTURE_TRACKING, FIXTURE_FILENAME)
    assert resultado.cantidad_pelos == 2


def test_parse_tracking_terminales_odf():
    resultado = parse_tracking(FIXTURE_TRACKING, FIXTURE_FILENAME)
    assert resultado.terminal_a == ("O-1247501-5", "112")
    assert resultado.terminal_b == ("ODF DWDM 91719", "15")


def test_parse_tracking_puntas_a_b():
    resultado = parse_tracking(FIXTURE_TRACKING, FIXTURE_FILENAME)
    assert resultado.punta_a is not None
    assert resultado.punta_a.tipo == "A"
    assert resultado.punta_b is not None
    assert resultado.punta_b.tipo == "B"


def test_parse_tracking_linea_sin_db_no_genera_entrada():
    """Regresión: 'F-GP-25M: 136 (CE / 12 - 4)' es una línea real de tracking que NO
    matchea FIBRA_REGEX (no termina en 'N dB') ni ningún otro patrón — el parser la
    descarta silenciosamente. Este test documenta ese comportamiento actual tal cual
    es, sin intentar "arreglarlo": no se debe modificar tracking_parser.py."""

    resultado = parse_tracking(FIXTURE_TRACKING, FIXTURE_FILENAME)
    nombres_cable = [e.cable_nombre for e in resultado.entries if e.cable_nombre]
    assert "F-GP-25M" not in nombres_cable
    assert not any(LINEA_NO_MATCHEA_NADA in e.raw_line for e in resultado.entries)


def test_parse_tracking_get_empalmes():
    resultado = parse_tracking(FIXTURE_TRACKING, FIXTURE_FILENAME)
    empalmes = resultado.get_empalmes()
    assert len(empalmes) == 2
    assert all(e.tipo == "empalme" for e in empalmes)

    transito, simple = empalmes
    assert transito.empalme_id == "6633037"
    assert transito.empalme_descripcion == "Patch 6646670: Nodo Dixon"
    assert transito.es_transito is True

    assert simple.empalme_id == "100"
    assert simple.empalme_descripcion == "CAMARA Retiro"
    assert simple.es_transito is False


def test_parse_tracking_get_transitos_solo_devuelve_los_transito():
    resultado = parse_tracking(FIXTURE_TRACKING, FIXTURE_FILENAME)
    transitos = resultado.get_transitos()
    assert len(transitos) == 1
    assert transitos[0].empalme_id == "6633037"
    assert transitos[0].es_transito is True


def test_parse_tracking_conteos():
    resultado = parse_tracking(FIXTURE_TRACKING, FIXTURE_FILENAME)
    assert resultado.empalmes_count == 2
    assert resultado.tramos_count == 1
    assert resultado.transitos_count == 1


def test_parse_tracking_tramo_con_db_parsea_atenuacion():
    resultado = parse_tracking(FIXTURE_TRACKING, FIXTURE_FILENAME)
    tramos = [e for e in resultado.entries if e.tipo == "tramo"]
    assert len(tramos) == 1
    assert tramos[0].cable_nombre == "F-CABLE-1"
    assert tramos[0].atenuacion_db == 7.5


def test_parse_tracking_get_topologia():
    resultado = parse_tracking(FIXTURE_TRACKING, FIXTURE_FILENAME)
    topologia = resultado.get_topologia()
    assert topologia == [
        ("6633037", "Patch 6646670: Nodo Dixon"),
        ("100", "CAMARA Retiro"),
    ]


def test_parse_tracking_to_dict_serializa_terminales():
    resultado = parse_tracking(FIXTURE_TRACKING, FIXTURE_FILENAME)
    data = resultado.to_dict()
    assert data["terminal_a"] == {"odf_id": "O-1247501-5", "conector": "112"}
    assert data["terminal_b"] == {"odf_id": "ODF DWDM 91719", "conector": "15"}
    assert data["empalmes_count"] == 2
    assert data["transitos_count"] == 1
    assert len(data["entries"]) == len(resultado.entries)


def test_parse_tracking_to_dict_terminales_none_cuando_no_hay_odf():
    resultado = parse_tracking("Empalme 1: CAMARA Sin ODF\nF-X: 1 dB")
    data = resultado.to_dict()
    assert data["terminal_a"] is None
    assert data["terminal_b"] is None
    assert data["punta_a"] is None
    assert data["punta_b"] is None


def test_parse_tracking_texto_vacio():
    resultado = parse_tracking("", "")
    assert resultado.entries == []
    assert resultado.empalmes_count == 0
    assert resultado.tramos_count == 0
    assert resultado.transitos_count == 0
    assert resultado.get_empalmes() == []
    assert resultado.get_transitos() == []
    assert resultado.terminal_a is None
    assert resultado.terminal_b is None


# ---------------------------------------------------------------------------
# Helpers de compatibilidad hacia atrás / iteradores
# ---------------------------------------------------------------------------


def test_parse_tracking_as_dicts_delega_en_to_dict():
    esperado = parse_tracking(FIXTURE_TRACKING, FIXTURE_FILENAME).to_dict()
    assert parse_tracking_as_dicts(FIXTURE_TRACKING, FIXTURE_FILENAME) == esperado


def test_parse_tracking_entries_devuelve_solo_entries():
    entries = parse_tracking_entries(FIXTURE_TRACKING)
    esperado = parse_tracking(FIXTURE_TRACKING).entries
    assert [e.to_dict() for e in entries] == [e.to_dict() for e in esperado]


def test_iter_empalmes_y_iter_tramos():
    resultado = parse_tracking(FIXTURE_TRACKING, FIXTURE_FILENAME)
    empalmes = list(iter_empalmes(resultado.entries))
    tramos = list(iter_tramos(resultado.entries))
    assert len(empalmes) == 2
    assert len(tramos) == 1
    assert all(isinstance(e, TrackingEntry) for e in empalmes + tramos)


def test_tracking_entry_to_dict():
    entry = TrackingEntry(
        tipo="empalme",
        empalme_id="1",
        empalme_descripcion="ODF Test",
        cable_nombre=None,
        atenuacion_db=None,
        raw_line="Empalme 1: ODF Test",
        index=0,
        es_transito=True,
    )
    data = entry.to_dict()
    assert data["tipo"] == "empalme"
    assert data["es_transito"] is True


def test_tracking_parse_result_es_dataclass_con_defaults():
    resultado = TrackingParseResult(servicio_id=None, alias_id=None, nombre_archivo="")
    assert resultado.entries == []
    assert resultado.empalmes_count == 0
    assert resultado.punta_a is None
    assert resultado.terminal_a is None
