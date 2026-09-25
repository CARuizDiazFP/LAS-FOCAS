# Nombre de archivo: test_cromo_camino_clases_pon.py
# Ubicación de archivo: tests/test_cromo_camino_clases_pon.py
# Descripción: Pruebas del etiquetado y enriquecimiento de la red de acceso PON en el camino óptico

"""Los payloads de estos tests calcan la forma REAL medida contra Cromo el 2026-09-17 sembrando
el camino desde una salida de splitter (`splitter_a.c_out`), que es la única forma de que Cromo
devuelva la caja PON y los cables de bajada — sembrando desde el lado de red el recorrido se corta
en el splitter."""

from __future__ import annotations

import pytest

from core.services.cromo.camino_optico_service import (
    TIPO_CABLE_BAJADA,
    TIPO_CAJA_PON,
    TIPO_FUSION_ODF,
    TIPO_NODO,
    TIPO_PUERTO_SPLITTER,
    TIPO_SPLITTER,
    _construir_lado,
    calcular_estadisticas,
)

# Recorte del payload real del camino sembrado en el puerto 8455773 (servicio 47279).
DIC = {
    8455766: {
        "class": 133,
        "at": [
            {"id": 78, "value": "S-1243457-3", "name": "nombre"},
            {"id": 83, "value": "1x8", "name": "fo.tipo"},
        ],
        "father": 6633268,
    },
    8455773: {
        "class": 134,
        "at": [
            {"id": 80, "value": "S6", "name": "fo.nombre_ent_sal"},
            {"id": 82, "value": "SALIDA", "name": "fo.entrada_salida"},
        ],
        "father": 8455766,
        "gfather": 6633268,
        "splitter_a": {
            "id": 8455766,
            "c_in": [8455767],
            "c_out": [8455773, 8455774, 8455775, 8455768, 8455770, 8455772, 8455769, 8455771],
        },
    },
    6676208: {
        "class": 84,
        "at": [
            {"id": 45, "value": "SI"},
            {"id": 16, "value": "602"},
            {"id": 34, "value": "Caja PON Subs Libertador 602", "name": "nombre"},
        ],
    },
    6617978: {
        "class": 66,
        "at": [
            {"id": 20, "value": "Aereo"},
            {"id": 26, "value": "FBJ-31363", "name": "nombre"},
            {"id": 27, "value": "Bajada"},
            {"id": 23, "value": "175"},
        ],
    },
    6646668: {
        "class": 86,
        "at": [{"id": 34, "value": "Nodo Paraguay 2302 P3 D5 Rack 1 de FO C.F.", "name": "nombre"}],
    },
    10002472: {
        "class": 141,
        "at": [
            {"id": 84, "value": "2-2", "name": "nombre"},
            {"id": 85, "value": "FUSION", "name": "fo.tipo"},
        ],
        "tp": [{"id_to": 10002448}, {"id_to": 10002422}],
    },
}

SECUENCIA = [8455766, 8455773, 6676208, 6617978, 6646668, 10002472]


def _nodos(catalogo=None):
    nodos, _no_resueltos = _construir_lado(DIC, SECUENCIA, "A", catalogo or {})
    return {n.id_cromo: n for n in nodos}


class TestEtiquetado:
    def test_las_clases_pon_dejan_de_caer_al_generico_clase_n(self):
        """El síntoma reportado: el diagrama mostraba `CLASE_84` sin nombre ni contexto."""
        nodos = _nodos()
        assert nodos[8455766].tipo == TIPO_SPLITTER
        assert nodos[8455773].tipo == TIPO_PUERTO_SPLITTER
        assert nodos[6676208].tipo == TIPO_CAJA_PON
        assert nodos[6617978].tipo == TIPO_CABLE_BAJADA
        assert nodos[6646668].tipo == TIPO_NODO
        assert nodos[10002472].tipo == TIPO_FUSION_ODF
        assert not any(n.tipo.startswith("CLASE_") for n in nodos.values())

    def test_el_catalogo_de_la_base_le_gana_al_fallback(self):
        """`app.cromo_clases` manda: el fallback del código es la red de seguridad, no la verdad."""
        nodos = _nodos({84: "CAJA_PON_DE_LA_BASE"})
        assert nodos[6676208].tipo == "CAJA_PON_DE_LA_BASE"

    def test_una_clase_realmente_desconocida_sigue_cayendo_al_generico(self):
        dic = {1: {"class": 999, "at": []}}
        nodos, _ = _construir_lado(dic, [1], "A", {})
        assert nodos[0].tipo == "CLASE_999"


class TestEnriquecimiento:
    def test_el_splitter_expone_el_ratio_que_publica_cromo(self):
        """`at.83` es dato, no inferencia por fan-out como en el detalle de empalmes de Botella."""
        nodo = _nodos()[8455766]
        assert nodo.splitter_ratio == "1x8"
        assert nodo.splitter_nombre == "S-1243457-3"
        assert nodo.nombre == "S-1243457-3"

    def test_el_puerto_hereda_el_ratio_de_su_splitter_padre(self):
        nodo = _nodos()[8455773]
        assert nodo.puerto_nombre == "S6"
        assert nodo.puerto_sentido == "SALIDA"
        assert nodo.splitter_id == 8455766
        assert nodo.splitter_ratio == "1x8"

    def test_el_puerto_cuenta_las_salidas_reales_del_splitter(self):
        """`splitter_a.c_out` trae la topología explícita: el fan-out no hay que deducirlo."""
        assert _nodos()[8455773].splitter_salidas == 8

    def test_la_caja_pon_muestra_su_nombre_real(self):
        assert _nodos()[6676208].nombre == "Caja PON Subs Libertador 602"

    def test_el_cable_de_bajada_trae_nombre_metraje_y_tendido(self):
        nodo = _nodos()[6617978]
        assert nodo.cable_nombre == "FBJ-31363"
        assert nodo.distancia_geo_m == pytest.approx(175.0)
        assert nodo.tendido == "Aereo"

    def test_la_fusion_de_odf_trae_su_par_y_los_pelos(self):
        nodo = _nodos()[10002472]
        assert nodo.nombre == "2-2"
        assert nodo.pelos_fusionados == [10002448, 10002422]


class TestEstadisticas:
    def test_cuenta_la_red_pon_por_separado(self):
        """Mezclar el cable de bajada con la troncal distorsionaría la longitud del backbone."""
        nodos, _ = _construir_lado(DIC, SECUENCIA, "A", {})
        est = calcular_estadisticas(nodos, [])
        assert est.splitters == 1
        assert est.cajas_pon == 1
        assert est.cables_bajada == 1
        assert est.cables == 0, "un cable de bajada no es un tramo de la troncal"


# ── Ampliación del submódulo PON (2026-09-19) ──


class TestClasesPonQueFaltaban:
    """Las cajas PON son siete clases, no dos.

    Medido contra Cromo: además de la 84 y la 137 existen 126 (391 objetos), 127 (111), 138 (1.394),
    139 (1.814) y 140 (490). Ninguna estaba en el catálogo ni en el fallback, así que el diagrama
    las dibujaba como `CLASE_139`.
    """

    @pytest.mark.parametrize("clase", [126, 127, 138, 139, 140])
    def test_las_cinco_clases_nuevas_se_etiquetan_como_caja_pon(self, clase):
        dic = {1: {"class": clase, "at": [{"id": 34, "value": "IAAS - PON Alberdi 1642 RED"}]}}
        nodos, _ = _construir_lado(dic, [1], "A", {})

        assert nodos[0].tipo == TIPO_CAJA_PON
        assert not nodos[0].tipo.startswith("CLASE_")

    @pytest.mark.parametrize("clase", [126, 127, 138, 139, 140])
    def test_las_cinco_reciben_el_enriquecimiento_de_nombre(self, clase):
        """No alcanza con etiquetarlas: tienen que entrar en `_CLASES_CAJA_PON` para que
        `_construir_lado` les lea el `at.34`, si no el nodo queda con tipo pero sin nombre."""
        dic = {1: {"class": clase, "at": [{"id": 34, "value": "IAAS - PON Doblas 497 RED 90857"}]}}
        nodos, _ = _construir_lado(dic, [1], "A", {})

        assert nodos[0].nombre == "IAAS - PON Doblas 497 RED 90857"

    def test_la_roseta_tiene_tipo_propio_y_no_cae_al_generico(self):
        """La 85 no aparece en ningún `/path` medido, pero su colección existe (17.348 objetos).

        Que no se haya observado en un recorrido no es razón para no saber qué es si aparece.
        """
        dic = {1: {"class": 85, "at": [{"id": 34, "value": "RST-66700"}]}}
        nodos, _ = _construir_lado(dic, [1], "A", {})

        assert nodos[0].tipo == "ROSETA"


class TestTablasVinculables:
    """Hasta ahora estos nodos llegaban siempre con `vinculo_local=None`: no fallaba la resolución,
    no había fila local que resolver. Con los modos de ingesta propios, ahora la hay."""

    def test_las_tablas_de_la_red_pon_estan_registradas(self):
        from core.services.cromo.camino_optico_service import _TABLAS_VINCULABLES

        registradas = {(tabla, tipo) for tabla, tipo, _col, _ver in _TABLAS_VINCULABLES}

        assert ("cromo_pon_elementos", TIPO_CAJA_PON) in registradas
        assert ("cromo_pon_elementos", "ROSETA") in registradas
        assert ("cromo_cables", TIPO_CABLE_BAJADA) in registradas
        assert ("cromo_splitters", TIPO_SPLITTER) in registradas
        assert ("cromo_splitter_puertos", TIPO_PUERTO_SPLITTER) in registradas

    def test_splitters_y_puertos_no_declaran_version_id(self):
        """Su tabla es liviana, sin versionado: declarar `version_id` haría que el vinculador
        corriera una segunda pasada contra una columna que no existe."""
        from core.services.cromo.camino_optico_service import _TABLAS_VINCULABLES

        por_tabla = {tabla: ver for tabla, _tipo, _col, ver in _TABLAS_VINCULABLES}

        assert por_tabla["cromo_splitters"] is False
        assert por_tabla["cromo_splitter_puertos"] is False
        assert por_tabla["cromo_pon_elementos"] is True
