# Nombre de archivo: test_cromo_parser.py
# Ubicación de archivo: tests/test_cromo_parser.py
# Descripción: Pruebas del parser puro de payloads de Cromo Red, sin red ni base de datos

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.services.cromo.parser import (
    ClaseExcluidaError,
    atributo,
    extraer_tubos_y_pelos,
    parse_arbol_botella,
    parse_botella,
    parse_cable,
    parse_objeto,
    parse_pagina,
    parse_pelo,
    resolver_lat_lon,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "cromo"


def _cargar_fixture(nombre: str) -> dict:
    with open(FIXTURES_DIR / nombre, encoding="utf-8") as f:
        return json.load(f)


# ── atributo() ────────────────────────────────────────────────────────────────


def test_atributo_resuelve_por_id_no_por_posicion():
    obj = {"at": [{"seq": 5, "id": 61, "value": "primero"}, {"seq": 1, "id": 34, "value": "segundo"}]}
    assert atributo(obj, 34) == "segundo"
    assert atributo(obj, 61) == "primero"


def test_atributo_devuelve_none_si_no_existe():
    obj = {"at": [{"seq": 1, "id": 34, "value": "x"}]}
    assert atributo(obj, 999) is None


def test_atributo_tolera_ausencia_de_at():
    assert atributo({}, 34) is None


# ── ll → latitud/longitud ───────────────────────────────────────────────────


def test_resolver_lat_lon_orden_correcto():
    # ll viene como [longitud, latitud]. Si se invierte el mapeo, este test falla.
    latitud, longitud = resolver_lat_lon([-58.4173, -34.6037])
    assert latitud == -34.6037
    assert longitud == -58.4173


def test_resolver_lat_lon_ausente():
    assert resolver_lat_lon(None) == (None, None)
    assert resolver_lat_lon([]) == (None, None)


# ── n_id como PK, id como version_id ────────────────────────────────────────


def test_n_id_es_pk_e_id_es_version_id_sobre_objeto_con_historial():
    obj = _cargar_fixture("botella_con_arbol.json")
    assert len(obj["hist"]) == 2
    botella = parse_botella(obj)
    assert botella.n_id == 10178728
    assert botella.version_id == 10193090
    assert botella.n_id != botella.version_id


def test_n_id_faltante_usa_id_como_fallback():
    obj = {"id": 42, "class": 68, "at": []}
    botella = parse_botella(obj)
    assert botella.n_id == 42


# ── clase 120 excluida ───────────────────────────────────────────────────────


def test_clase_120_es_rechazada_con_error_explicito():
    obj = _cargar_fixture("parcela_clase_120.json")
    with pytest.raises(ClaseExcluidaError):
        parse_objeto(obj)
    with pytest.raises(ClaseExcluidaError):
        parse_botella(obj)


def test_clase_124_se_marca_no_homologada():
    obj = _cargar_fixture("botella_no_homologada.json")
    botella = parse_botella(obj)
    assert botella.clase_no_homologada is True


# ── parent resuelve contra n_id, no contra id ───────────────────────────────


def test_parent_resuelve_contra_n_id_no_contra_id():
    obj = _cargar_fixture("botella_con_arbol.json")
    cable_embebido = obj["tp"][0]
    tubos, pelos, errores = extraer_tubos_y_pelos(cable_embebido)
    assert not errores

    n_ids_tubos = {t.n_id for t in tubos}
    # El primer tubo tiene id=60099 pero n_id=60010: sus pelos deben matchear n_id, no id.
    tubo_con_historia = next(t for t in tubos if t.n_id == 60010)
    assert tubo_con_historia.n_id != 60099  # id original del fixture, nunca debe usarse como PK

    pelos_del_tubo = [p for p in pelos if p.tubo_n_id == tubo_con_historia.n_id]
    assert len(pelos_del_tubo) == 2
    assert all(p.tubo_n_id in n_ids_tubos for p in pelos)


# ── atributo(obj, id) ya cubierto arriba; helper reutilizado en todos los parsers ──


def test_pelo_sin_at61_se_parsea_sin_excepcion():
    obj = {"id": 1, "n_id": 1, "class": 130, "parent": 60010, "at": [{"id": 75, "value": "9"}]}
    pelo = parse_pelo(obj)
    assert pelo.servicio_numero is None
    assert pelo.tipo_asociacion == "INDETERMINADO"
    assert pelo.servicio_raw is None


def test_pelo_con_at61_extrae_numero_de_servicio():
    obj = {
        "id": 1,
        "n_id": 1,
        "class": 130,
        "parent": 60010,
        "at": [{"id": 61, "value": "FO 114830 - EDGE - CIRION - Pelo 1 de 2"}],
    }
    pelo = parse_pelo(obj)
    assert pelo.servicio_numero == "114830"
    assert pelo.servicio_raw == "FO 114830 - EDGE - CIRION - Pelo 1 de 2"


# ── botella.inner[] → sólo fusiones ──────────────────────────────────────────


def test_botella_inner_produce_fusiones_y_nunca_tubos_ni_pelos():
    obj = _cargar_fixture("botella_con_arbol.json")
    arbol = parse_arbol_botella(obj)
    assert len(arbol.fusiones) == 1
    assert arbol.fusiones[0].nombre_par == "53-17"
    assert arbol.fusiones[0].tipo == "FUSION"
    # Las fusiones vienen de inner[]; tubos y pelos vienen de tp[] → cable.inner[], nunca de acá.
    assert arbol.tubos  # sí hay tubos, pero originados en el cable, no en botella.inner[]
    assert arbol.pelos


# ── cable.inner[] → tubos y pelos, pelo asociado a su tubo ──────────────────


def test_cable_inner_produce_tubos_y_pelos_asociados():
    obj = _cargar_fixture("botella_con_arbol.json")
    arbol = parse_arbol_botella(obj)
    assert len(arbol.cables) == 1
    assert len(arbol.tubos) == 2
    assert len(arbol.pelos) == 3

    n_ids_tubos = {t.n_id for t in arbol.tubos}
    for pelo in arbol.pelos:
        assert pelo.tubo_n_id in n_ids_tubos
        assert pelo.cable_n_id == arbol.cables[0].n_id


def test_cable_parseado_desde_barrido_directo():
    obj = _cargar_fixture("cable_barrido_directo.json")
    cable = parse_cable(obj)
    assert cable.n_id == 50010
    assert cable.version_id == 50199
    assert cable.nombre == "F-PLB-ART"
    assert cable.capacidad == "72-BRUG"
    assert cable.capacidad_pelos == 72
    assert cable.propietario == "Metrotel"
    assert cable.jerarquia == "Troncal"
    assert cable.extremo_a_n_id == 10178728
    assert cable.extremo_a_clase == 68
    assert cable.extremo_b_n_id == 10444555
    assert cable.extremo_b_clase == 124


# ── iterar_coleccion / tolerancia de página: cubiertas del lado del parser ──


def test_objeto_malformado_en_pagina_no_impide_procesar_el_resto():
    valido_1 = {"id": 1, "n_id": 1, "class": 68, "at": []}
    malformado = {"id": 2, "n_id": 2, "class": 9999, "at": []}  # clase sin parser asociado
    valido_2 = {"id": 3, "n_id": 3, "class": 51, "at": []}

    ok, errores = parse_pagina([valido_1, malformado, valido_2])

    assert len(ok) == 2
    assert len(errores) == 1
    assert errores[0].n_id == 2
    assert errores[0].clase == 9999


def test_clase_132_no_asume_siempre_fusion():
    obj = {
        "id": 1,
        "n_id": 1,
        "class": 132,
        "parent": 10,
        "at": [{"id": 84, "value": "X-Y"}, {"id": 85, "value": "OTRO_TIPO"}],
        "tp": [],
    }
    from core.services.cromo.parser import parse_fusion

    fusion = parse_fusion(obj)
    assert fusion.tipo == "OTRO_TIPO"
