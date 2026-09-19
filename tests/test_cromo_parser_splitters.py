# Nombre de archivo: test_cromo_parser_splitters.py
# Ubicación de archivo: tests/test_cromo_parser_splitters.py
# Descripción: Pruebas del parseo de splitters (133) y sus puertos (134) desde el árbol de Botella

"""Los payloads calcan la forma REAL medida contra Cromo el 2026-09-17: el barrido de colección de
botellas (`show=ALL`) ya trae 133 y 134 dentro de `inner[]`, con `parent` como entero — a diferencia
del fetch directo de un objeto, donde `parent` viene como diccionario."""

from __future__ import annotations

import pytest

from core.services.cromo.parser import (
    parse_arbol_botella,
    parse_puerto_splitter,
    parse_splitter,
    salidas_de_ratio,
)

# Recorte real de botella 6637745 (3 splitters, 27 puertos, 72 fusiones).
SPLITTER_CRUDO = {
    "id": 8473945,
    "n_id": 8473945,
    "class": 133,
    "name": "S-1269002-2",
    "at": [
        {"id": 78, "value": "S-1269002-2", "name": "nombre"},
        {"id": 83, "value": "1x8", "name": "fo.tipo"},
    ],
    "parent": 6637745,
}

PUERTO_CRUDO = {
    "id": 8473964,
    "n_id": 8473964,
    "class": 134,
    "name": "",
    "at": [
        {"id": 80, "value": "S8", "name": "fo.nombre_ent_sal"},
        {"id": 82, "value": "SALIDA", "name": "fo.entrada_salida"},
    ],
    "parent": 8473955,
}

# Puerto traído por `/inner`, que SÍ incluye el at.62 del servicio (botella 8941541, puerto E1).
PUERTO_CON_SERVICIOS = {
    "id": 8980339,
    "n_id": 8980339,
    "class": 134,
    "at": [
        {"id": 80, "value": "E1", "name": "fo.nombre_ent_sal"},
        {"id": 82, "value": "ENTRADA", "name": "fo.entrada_salida"},
        {"id": 62, "value": "99250"},
        {"id": 62, "value": "99430"},
        {"id": 62, "value": "100950"},
        {"id": 62, "value": "106587"},
    ],
    "parent": 8980330,
}


class TestSalidasDeRatio:
    @pytest.mark.parametrize(
        "crudo,esperado",
        [("1x8", 8), ("1x4", 4), ("1x2", 2), ("1X16", 16), (" 1 x 32 ", 32)],
    )
    def test_extrae_el_numero_de_salidas(self, crudo, esperado):
        assert salidas_de_ratio(crudo) == esperado

    @pytest.mark.parametrize("crudo", [None, "", "raro", "2x4", "1x", "1x0", "SPLITTER"])
    def test_lo_que_no_entiende_no_se_inventa(self, crudo):
        """Un ratio que no matchea deja `salidas=None` y conserva el crudo: normalizarlo a un
        número equivocado sería peor que admitir que no se entendió."""
        assert salidas_de_ratio(crudo) is None


class TestParseSplitter:
    def test_toma_el_ratio_que_publica_cromo(self):
        """`at.83` es dato. Es todo el punto: `empalmes.py` lo deducía por fan-out y fallaba."""
        splitter = parse_splitter(SPLITTER_CRUDO)
        assert splitter.n_id == 8473945
        assert splitter.ratio == "1x8"
        assert splitter.salidas == 8

    def test_cuelga_de_la_botella_por_parent(self):
        assert parse_splitter(SPLITTER_CRUDO).botella_n_id == 6637745

    def test_el_nombre_sale_de_at78(self):
        assert parse_splitter(SPLITTER_CRUDO).nombre == "S-1269002-2"

    def test_sin_ratio_no_revienta(self):
        crudo = {**SPLITTER_CRUDO, "at": [{"id": 78, "value": "SPLITTER1"}]}
        splitter = parse_splitter(crudo)
        assert splitter.ratio is None and splitter.salidas is None


class TestParsePuertoSplitter:
    def test_parent_es_el_splitter_no_la_botella(self):
        """El puerto cuelga del splitter; la botella la aporta el llamador."""
        puerto = parse_puerto_splitter(PUERTO_CRUDO, botella_n_id=6637745)
        assert puerto.splitter_n_id == 8473955
        assert puerto.botella_n_id == 6637745

    def test_nombre_y_sentido(self):
        puerto = parse_puerto_splitter(PUERTO_CRUDO)
        assert puerto.nombre == "S8"
        assert puerto.sentido == "SALIDA"

    def test_del_barrido_no_se_sabe_nada_del_servicio(self):
        """`None` es "no se preguntó": el barrido de colección no trae `at.62`, sólo `/inner`.
        Es el default a propósito: la fase de ingesta regular corre sobre el barrido."""
        assert parse_puerto_splitter(PUERTO_CRUDO).servicios_atributo is None

    def test_la_entrada_agrega_todos_los_servicios_del_splitter(self):
        """Dato real: E1 del splitter 1x8 de la botella 8941541 lista sus 4 servicios."""
        puerto = parse_puerto_splitter(PUERTO_CON_SERVICIOS, trae_servicios=True)
        assert puerto.sentido == "ENTRADA"
        assert puerto.servicios_atributo == ["99250", "99430", "100950", "106587"]

    def test_un_puerto_libre_no_se_confunde_con_uno_no_preguntado(self):
        """La distinción de tres estados: `[]` es "se preguntó y está libre", `None` es "no se
        preguntó". Sin el flag las dos colapsan, y S4/S6/S7/S8 de un splitter relevado parecerían
        nunca haberse consultado (hallazgo real al inspeccionar la tabla tras la primera ingesta)."""
        libre = parse_puerto_splitter(PUERTO_CRUDO, trae_servicios=True)
        no_preguntado = parse_puerto_splitter(PUERTO_CRUDO, trae_servicios=False)
        assert libre.servicios_atributo == []
        assert no_preguntado.servicios_atributo is None


class TestArbolBotella:
    def _arbol(self):
        botella = {
            "n_id": 6637745,
            "id": 6637745,
            "class": 68,
            "at": [{"id": 34, "value": "Botella de prueba"}],
            "inner": [
                SPLITTER_CRUDO,
                PUERTO_CRUDO,
                {
                    "n_id": 111,
                    "class": 132,
                    "at": [{"id": 84, "value": "1-1"}],
                    "parent": 6637745,
                    "tp": [],
                },
            ],
        }
        return parse_arbol_botella(botella)

    def test_recoge_splitters_y_puertos_sin_tratarlos_como_error(self):
        """Antes de 2026-09-17 ambos caían en `errores` como "clase inesperada" y se descartaban."""
        arbol = self._arbol()
        assert [s.n_id for s in arbol.splitters] == [8473945]
        assert [p.n_id for p in arbol.puertos_splitter] == [8473964]
        assert arbol.errores == []

    def test_las_fusiones_siguen_saliendo_igual(self):
        assert [f.n_id for f in self._arbol().fusiones] == [111]

    def test_el_arbol_propaga_la_procedencia_del_payload(self):
        """Quien llama sabe si el payload vino del barrido o de `/inner`; el parser no puede."""
        from core.services.cromo.parser import parse_arbol_botella as _parse

        botella = {
            "n_id": 1,
            "class": 68,
            "at": [],
            "inner": [{**PUERTO_CRUDO, "parent": None}],
        }
        assert _parse(botella).puertos_splitter[0].servicios_atributo is None
        assert _parse(botella, puertos_traen_servicios=True).puertos_splitter[0].servicios_atributo == []

    def test_el_puerto_hereda_la_botella_del_arbol(self):
        assert self._arbol().puertos_splitter[0].botella_n_id == 6637745

    def test_una_clase_realmente_inesperada_sigue_siendo_error(self):
        botella = {
            "n_id": 1,
            "class": 68,
            "at": [],
            "inner": [{"n_id": 9, "class": 999, "at": []}],
        }
        arbol = parse_arbol_botella(botella)
        assert len(arbol.errores) == 1
        assert arbol.errores[0].clase == 999


# --------------------------------------------------------------------------------------------
# Barrido DIRECTO de las colecciones 133 y 134 (`filter=133`/`filter=134`, `show=ALL`).
#
# Forma medida contra Cromo real el 2026-09-19 sobre 60 objetos de cada clase. Es distinta de la
# del árbol de Botella de más arriba, y la diferencia no es cosmética:
#   - En el splitter, `parent` es SIEMPRE un diccionario (60/60), nunca el entero que trae `inner[]`.
#   - En el puerto, `parent` es el CONTENEDOR PON (138/137/139 en la muestra), **no** el splitter.
#     El splitter viaja en `extra.parent` (clase 133 en 60/60) y su `n_id` coincide con `at.71`
#     en 60/60.
# --------------------------------------------------------------------------------------------

SPLITTER_BARRIDO_DIRECTO = {
    "id": 9055426,
    "n_id": 9055426,
    "class": 133,
    "name": "SPLITTER 1",
    "vmax": 33490,
    "at": [
        {"id": 78, "value": "SPLITTER 1", "name": "nombre"},
        {"id": 83, "value": "1x8", "name": "fo.tipo"},
    ],
    "parent": {"id": 8992249, "class": 138, "name": "PON 2 PARAGUAY 1338 RED 92889"},
    "extra": {
        "container": {"id": 8992249, "n_id": 8992249, "class": 138, "name": "PON 2 PARAGUAY 1338"},
    },
}

SPLITTER_BARRIDO_DIRECTO_EN_BOTELLA = {
    **SPLITTER_BARRIDO_DIRECTO,
    "id": 8941542,
    "n_id": 8941542,
    "parent": {"id": 8941541, "class": 68, "name": "Bot Corrientes 1234 CF"},
    "extra": {"container": {"id": 8941541, "n_id": 8941541, "class": 68}},
}

# `parent.id` es un id de VERSION, no el de linaje. Medido: en 4 de 60 objetos reales
# `container.id != container.n_id`, y en esos mismos `parent.id` tampoco coincide con el n_id.
# Tomar `parent.id` como contenedor deja la referencia apuntando a una version, que es el viejo
# problema de "ID dual" ya documentado para cables y botellas.
SPLITTER_CONTENEDOR_CON_ID_DUAL = {
    **SPLITTER_BARRIDO_DIRECTO,
    "id": 9200001,
    "n_id": 9200001,
    "parent": {"id": 7000999, "class": 137, "name": "IAAS - PON version vieja"},
    "extra": {"container": {"id": 7000999, "n_id": 6999001, "class": 137}},
}

PUERTO_BARRIDO_DIRECTO = {
    "id": 9055281,
    "n_id": 9055281,
    "class": 134,
    "at": [
        {"id": 80, "value": "S5", "name": "fo.nombre_ent_sal"},
        {"id": 82, "value": "SALIDA", "name": "fo.entrada_salida"},
        {"id": 70, "value": "6685157"},
        {"id": 71, "value": "9055276"},
    ],
    "parent": {"id": 6685157, "class": 138, "name": "IAAS- PON SAN JOSE DE CALASANZ 530"},
    "extra": {
        "parent": {"id": 9055276, "n_id": 9055276, "class": 133, "name": "SPLITTER2"},
        "container": {"id": 6685157, "n_id": 6685157, "class": 138},
    },
}


class TestSplitterDelBarridoDirecto:
    def test_no_guarda_el_diccionario_de_parent_como_botella(self):
        """El bug que esta forma de payload provoca: `botella_n_id` terminaba siendo un dict.

        Es la misma basura silenciosa que ya se documentó para `tubo_n_id`: nadie falla, la fila se
        escribe y el dato queda inservible.
        """
        splitter = parse_splitter(SPLITTER_BARRIDO_DIRECTO)

        assert splitter.botella_n_id is None

    def test_registra_el_contenedor_y_su_clase(self):
        splitter = parse_splitter(SPLITTER_BARRIDO_DIRECTO)

        assert splitter.contenedor_n_id == 8992249
        assert splitter.contenedor_clase == 138

    def test_cuando_el_contenedor_es_una_botella_puebla_botella_n_id(self):
        """`botella_n_id` sigue existiendo para `empalmes.py`, que consulta por esa columna.

        Se puebla sólo cuando el contenedor es realmente una Botella — el 12% de los casos según la
        medición de 800 splitters reales.
        """
        splitter = parse_splitter(SPLITTER_BARRIDO_DIRECTO_EN_BOTELLA)

        assert splitter.botella_n_id == 8941541
        assert splitter.contenedor_n_id == 8941541
        assert splitter.contenedor_clase == 68

    def test_prefiere_el_n_id_de_linaje_sobre_el_id_de_version_del_parent(self):
        """Con "ID dual", `parent.id` apunta a una version y `extra.container.n_id` al linaje."""
        splitter = parse_splitter(SPLITTER_CONTENEDOR_CON_ID_DUAL)

        assert splitter.contenedor_n_id == 6999001
        assert splitter.contenedor_clase == 137

    def test_el_embebido_en_arbol_de_botella_conserva_su_comportamiento(self):
        """La vía del árbol sigue mandando: el recorrido sabe de quién cuelga."""
        splitter = parse_splitter(SPLITTER_CRUDO, botella_n_id=6637745)

        assert splitter.botella_n_id == 6637745
        assert splitter.contenedor_n_id == 6637745


class TestPuertoDelBarridoDirecto:
    def test_cuelga_del_splitter_y_no_del_contenedor_pon(self):
        """`parent` acá es la caja PON, no el splitter: tomarlo sin mirar cuelga mal el puerto."""
        puerto = parse_puerto_splitter(PUERTO_BARRIDO_DIRECTO)

        assert puerto.splitter_n_id == 9055276

    def test_no_inventa_botella(self):
        puerto = parse_puerto_splitter(PUERTO_BARRIDO_DIRECTO)

        assert puerto.botella_n_id is None
        assert puerto.nombre == "S5"
        assert puerto.sentido == "SALIDA"
