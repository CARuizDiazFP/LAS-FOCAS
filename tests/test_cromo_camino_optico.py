# Nombre de archivo: test_cromo_camino_optico.py
# Ubicación de archivo: tests/test_cromo_camino_optico.py
# Descripción: Pruebas del servicio de camino óptico de Cromo (parseo del dict de /path) sin red ni base de datos

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.services.cromo.camino_optico_service import (
    ESTADO_SIN_CAMINO,
    TIPO_CONECTOR_ODF,
    TIPO_FUSION,
    TIPO_NO_RESUELTO,
    TIPO_PELO,
    _construir_lado,
    _desenvolver_dict,
    _localizar_raiz,
    calcular_estadisticas,
    comparar_at62_vs_regex,
    odfs_del_camino,
)

FIXTURE = Path(__file__).parent / "fixtures" / "cromo" / "camino_optico_pelo_10006353_reducido.json"
PELO_RAIZ = 10006353


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _dic() -> dict[int, dict]:
    return _desenvolver_dict(_fixture())


# ── Desenvoltura de la respuesta ─────────────────────────────────────────────


def test_desenvuelve_la_forma_real_de_cromo():
    # Medido contra Cromo real (2026-09-10): las claves de nivel superior son
    # `['dict', 'msg', 'st']` y el diccionario cuelga de `payload['dict']`.
    dic = _desenvolver_dict(_fixture())

    assert PELO_RAIZ in dic
    assert dic[PELO_RAIZ]["class"] == 130


@pytest.mark.parametrize(
    "payload",
    [
        {"dict": {"7": {"class": 130}}},
        {"st": 0, "response": {"dict": {"7": {"class": 130}}}},
        {"response": {"7": {"class": 130}}},
        {"7": {"class": 130}},
    ],
)
def test_desenvuelve_las_cuatro_envolturas_posibles(payload):
    assert _desenvolver_dict(payload) == {7: {"class": 130}}


def test_normaliza_las_claves_a_entero_y_descarta_las_no_numericas():
    # Las claves JSON son strings pero `a[]`/`b[]` traen enteros: sin normalizar, cualquier
    # lookup es una bomba de tipos.
    dic = _desenvolver_dict({"dict": {"7": {"class": 130}, "msg": "", "st": 0, "next": 0}})

    assert list(dic) == [7]


def test_payload_sin_claves_numericas_no_revienta():
    assert _desenvolver_dict({"st": 1, "msg": "error"}) == {}
    assert _desenvolver_dict("no soy un objeto") == {}


# ── Localización de la raíz (n_id de linaje vs. id de versión) ───────────────


def test_localiza_la_raiz_por_clave_exacta():
    id_raiz, raiz, es_mismo_id = _localizar_raiz(_dic(), PELO_RAIZ)

    assert id_raiz == PELO_RAIZ
    assert es_mismo_id is True
    assert raiz["class"] == 130


def test_localiza_la_raiz_por_el_unico_nodo_con_ambos_lados_si_el_id_no_es_clave():
    # Instrumenta la incógnita del id dual: si Cromo devolviera la raíz bajo otro id (el de
    # versión), se la reconoce igual porque es el único nodo que trae `a[]` y `b[]`.
    dic = {99: {"class": 130, "a": [1], "b": [2]}, 1: {"class": 132}, 2: {"class": 132}}

    id_raiz, raiz, es_mismo_id = _localizar_raiz(dic, 12345)

    assert id_raiz == 99
    assert es_mismo_id is False
    assert raiz is dic[99]


def test_sin_candidato_de_raiz_no_hay_raiz():
    dic = {1: {"class": 132}, 2: {"class": 132}}

    assert _localizar_raiz(dic, 12345) == (None, None, False)


def test_con_dos_candidatos_de_raiz_no_se_elige_ninguno():
    # Pedir varios pelos en una sola llamada es legítimo (el manual lo documenta), pero
    # entonces la raíz es ambigua y hay que resolverla por el id pedido, no adivinando.
    dic = {
        1: {"class": 130, "a": [], "b": []},
        2: {"class": 130, "a": [], "b": []},
    }

    assert _localizar_raiz(dic, 999) == (None, None, False)


# ── Construcción de un lado ──────────────────────────────────────────────────


def test_construye_el_lado_con_el_orden_y_los_tipos_reales():
    dic = _dic()
    raiz = dic[PELO_RAIZ]

    nodos, no_resueltos = _construir_lado(dic, raiz["a"], "A", {})

    assert [n.orden for n in nodos] == [0, 1, 2]
    assert all(n.lado == "A" for n in nodos)
    # Medido real: `a[]`/`b[]` sólo traen pelos (130), fusiones (132) y conectores (136).
    assert {n.tipo for n in nodos} <= {TIPO_PELO, TIPO_FUSION, TIPO_CONECTOR_ODF}
    assert no_resueltos == []


def test_el_pelo_del_camino_trae_su_cable_y_su_tubo_resueltos():
    dic = _dic()
    nodos, _ = _construir_lado(dic, dic[PELO_RAIZ]["a"], "A", {})

    pelos = [n for n in nodos if n.tipo == TIPO_PELO]
    assert pelos, "la fixture real trae al menos un pelo en el lado A"
    pelo = pelos[0]
    assert pelo.cable_nombre  # at.26 del cable (gfather)
    assert pelo.distancia_geo_m is not None  # at.23
    assert pelo.distancia_real_m is not None  # at.24
    assert pelo.tubo_color  # at.76 del tubo (father)


def test_el_conector_del_camino_resuelve_patchera_y_odf():
    # Hallazgo real: el conector (136) trae `father` = patchera (135) y `gfather` = ODF (69),
    # así que el extremo se resuelve sin una sola llamada extra.
    dic = _dic()
    nodos, _ = _construir_lado(dic, dic[PELO_RAIZ]["a"], "A", {})

    conectores = [n for n in nodos if n.tipo == TIPO_CONECTOR_ODF]
    assert conectores, "el lado A de la fixture termina en un conector de patchera"
    conector = conectores[-1]
    assert conector.conector_numero == "5"  # at.81
    assert conector.patchera_nombre == "O-1249382-1"  # at.79 de la patchera
    assert conector.odf_id == 6644124
    assert conector.odf_nombre.startswith("ODF Frontera")
    assert conector.servicio_at62 == "93154"  # el conector también trae el servicio


def test_un_id_ausente_del_dict_conserva_su_posicion_y_se_reporta():
    # La posición dice DÓNDE se rompió el camino: saltearlo en silencio destruye esa información.
    dic = {1: {"class": 132}, 3: {"class": 132}}

    nodos, no_resueltos = _construir_lado(dic, [1, 2, 3], "A", {})

    assert [n.orden for n in nodos] == [0, 1, 2]
    assert nodos[1].tipo == TIPO_NO_RESUELTO
    assert nodos[1].id_cromo == 2
    assert no_resueltos == [2]


def test_un_id_repetido_se_marca_y_no_se_duplica_en_las_distancias():
    dic = {
        1: {"class": 130, "father": 10, "gfather": 20},
        10: {"class": 129, "at": [{"id": 76, "value": "AZ"}]},
        20: {"class": 51, "at": [{"id": 23, "value": "100"}, {"id": 24, "value": "110"}]},
    }

    nodos, _ = _construir_lado(dic, [1, 1], "A", {})

    assert nodos[0].repetido is False
    assert nodos[1].repetido is True

    estadisticas = calcular_estadisticas(nodos, [])
    assert estadisticas.longitud_geo_m == 100.0  # no 200: el cable repetido no se suma dos veces
    assert estadisticas.longitud_optica_m == 110.0


def test_nodo_sin_clase_no_revienta():
    nodos, _ = _construir_lado({1: {"at": []}}, [1], "A", {})

    assert nodos[0].clase is None
    assert nodos[0].tipo == "CLASE_DESCONOCIDA"


def test_clase_desconocida_cae_a_una_etiqueta_explicita_y_no_a_un_tipo_inventado():
    nodos, _ = _construir_lado({1: {"class": 777, "at": []}}, [1], "A", {})

    assert nodos[0].tipo == "CLASE_777"


def test_la_clase_52_se_trata_como_cable():
    # Apareció en un camino real (2026-09-10) como un segundo tipo de cable, de un tercero
    # (`at.25` = "Arsat"), con los mismos atributos que un 51: nombre, capacidad y distancias.
    # La ingesta no barre esa clase, así que no está en `app.cromo_clases`.
    dic = {
        1: {
            "class": 52,
            "at": [
                {"id": 26, "value": "F-CROS-1"},
                {"id": 23, "value": "619"},
                {"id": 24, "value": "634.5"},
            ],
        }
    }

    nodos, _ = _construir_lado(dic, [1], "A", {})

    assert nodos[0].tipo == "CABLE"
    assert nodos[0].cable_nombre == "F-CROS-1"
    assert nodos[0].distancia_real_m == 634.5


def test_el_catalogo_de_clases_de_la_base_gana_sobre_el_fallback():
    nodos, _ = _construir_lado({1: {"class": 999, "at": []}}, [1], "A", {999: "COSA_NUEVA"})

    assert nodos[0].tipo == "COSA_NUEVA"


def test_los_atributos_se_resuelven_por_id_y_nunca_por_posicion():
    # Garantía declarada en todo el módulo Cromo: hay que testearla, no comentarla.
    dic = {
        1: {"class": 130, "father": 10, "gfather": 20, "at": [{"id": 77, "value": "MR"}, {"id": 75, "value": "4"}]},
        10: {"class": 129, "at": [{"id": 76, "value": "AZ"}, {"id": 72, "value": "1"}]},
        20: {"class": 51, "at": [{"id": 26, "value": "F-X"}, {"id": 24, "value": "9"}, {"id": 23, "value": "8"}]},
    }

    nodos, _ = _construir_lado(dic, [1], "A", {})

    assert nodos[0].numero_pelo == "4"
    assert nodos[0].color_pelo == "MR"
    assert nodos[0].cable_nombre == "F-X"


def test_corta_el_lado_en_la_cota_y_avisa():
    dic = {i: {"class": 132} for i in range(1, 12)}

    nodos, _ = _construir_lado(dic, list(range(1, 12)), "A", {}, max_nodos=5)

    assert len(nodos) == 5


# ── Estadísticas (mismo panel que muestra la web de Cromo) ───────────────────


def test_estadisticas_del_camino_real():
    dic = _dic()
    lado_a, _ = _construir_lado(dic, dic[PELO_RAIZ]["a"], "A", {})
    lado_b, _ = _construir_lado(dic, dic[PELO_RAIZ]["b"], "B", {})

    estadisticas = calcular_estadisticas(lado_a, lado_b)

    assert estadisticas.nodos == len(lado_a) + len(lado_b)
    assert estadisticas.conectores >= 1
    assert estadisticas.longitud_optica_m >= estadisticas.longitud_geo_m


def test_el_cable_del_pelo_raiz_entra_en_las_longitudes():
    """Bug real encontrado comparando contra el panel de la web de Cromo: el pelo raíz no está
    en `a[]` ni en `b[]`, pero su cable ES un tramo del camino. Sin contarlo faltaban
    exactamente los 295 m de ese cable (72.754 m calculados vs. 73.049 m de Cromo)."""
    dic = {
        1: {"class": 130, "father": 10, "gfather": 20},
        10: {"class": 129, "at": [{"id": 76, "value": "AZ"}]},
        20: {"class": 51, "at": [{"id": 23, "value": "295"}, {"id": 24, "value": "302.36"}]},
    }
    raiz, _ = _construir_lado(dic, [1], "RAIZ", {})

    sin_raiz = calcular_estadisticas([], [])
    con_raiz = calcular_estadisticas([], [], raiz[0])

    assert sin_raiz.longitud_geo_m == 0.0
    assert con_raiz.longitud_geo_m == 295.0
    assert con_raiz.longitud_optica_m == 302.36
    assert con_raiz.cables == 1


# ── ODFs descubiertas en el camino ───────────────────────────────────────────


def test_odfs_del_camino_sale_de_los_conectores_sin_llamadas_extra():
    dic = _dic()
    lado_a, _ = _construir_lado(dic, dic[PELO_RAIZ]["a"], "A", {})
    lado_b, _ = _construir_lado(dic, dic[PELO_RAIZ]["b"], "B", {})

    odfs = odfs_del_camino(lado_a, lado_b)

    assert odfs, "el camino real termina en conectores de ODF"
    assert all(o.odf_id for o in odfs)
    assert odfs[0].patchera_nombre


def test_odfs_del_camino_no_duplica_la_misma_odf():
    dic = {
        1: {"class": 136, "father": 10, "gfather": 20, "at": [{"id": 81, "value": "1"}]},
        2: {"class": 136, "father": 10, "gfather": 20, "at": [{"id": 81, "value": "2"}]},
        10: {"class": 135, "at": [{"id": 79, "value": "O-1-1"}]},
        20: {"class": 69, "at": [{"id": 34, "value": "ODF X"}]},
    }
    nodos, _ = _construir_lado(dic, [1, 2], "A", {})

    odfs = odfs_del_camino(nodos, [])

    assert len(odfs) == 1
    assert odfs[0].odf_id == 20


# ── Discrepancia at.62 vs. regex sobre at.61 ─────────────────────────────────


@pytest.mark.parametrize(
    "at62, at61, veredicto_esperado",
    [
        ("93154", "FO 93154 - ODF Guanahani 580", "COINCIDE"),
        ("61943", "FO 41140 - algo viejo", "DIFIERE"),
        ("93154", "texto libre sin numero", "SOLO_AT62"),
        (None, "FO 93154 - ODF", "SOLO_REGEX"),
        (None, None, "SIN_DATO"),
        (None, "texto libre", "SIN_DATO"),
        ("abc", "FO 93154 - ODF", "AT62_NO_PLAUSIBLE"),
        ("12", "FO 93154 - ODF", "AT62_NO_PLAUSIBLE"),
    ],
)
def test_tabla_de_verdad_de_la_discrepancia(at62, at61, veredicto_esperado):
    assert comparar_at62_vs_regex(at62, at61).veredicto == veredicto_esperado


def test_la_discrepancia_conserva_los_tres_valores_crudos():
    # Es un dato de auditoría: no se pierde ninguno de los tres lados de la comparación.
    discrepancia = comparar_at62_vs_regex("61943", "FO 41140 - viejo")

    assert discrepancia.at62 == "61943"
    assert discrepancia.at61 == "FO 41140 - viejo"
    assert discrepancia.numero_regex == "41140"


# ── Estado sin camino ────────────────────────────────────────────────────────


def test_el_estado_sin_camino_es_un_nombre_publico():
    # Se usa desde los endpoints para responder 200 con estado, no un error HTTP.
    assert ESTADO_SIN_CAMINO == "SIN_CAMINO"
