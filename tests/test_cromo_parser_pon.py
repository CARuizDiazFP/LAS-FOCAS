# Nombre de archivo: test_cromo_parser_pon.py
# Ubicación de archivo: tests/test_cromo_parser_pon.py
# Descripción: Pruebas del parseo de elementos raíz de la red de acceso PON (cajas PON y rosetas)

"""Los payloads calcan la forma REAL medida contra Cromo el 2026-09-19 sobre las ocho clases: todas
son objetos raíz (`parent` ausente), traen `ll` y `pts`, y publican el mismo juego de `at`."""

from __future__ import annotations

import pytest

from core.services.cromo.parser import parse_pon_elemento

# Recorte real de la caja PON 6677085 (clase 84) más los atributos que sólo traen las clases
# "IAAS - PON ... RED": at.40 (tipo de conector), at.46 (capacidad) y at.47 (propietario).
CAJA_PON_CRUDA = {
    "id": 6677085,
    "n_id": 6677085,
    "class": 84,
    "vmax": 517,
    "name": "Caja PON Paraguay 2386 C.F. FO37770",
    "at": [
        {"id": 45, "value": "SI"},
        {"id": 16, "value": "2386"},
        {"id": 34, "value": "Caja PON Paraguay 2386 C.F. FO37770", "name": "nombre"},
        {"id": 41, "value": "PON 8 PORT", "name": "codigo"},
        {"id": 40, "value": "Fast connect"},
        {"id": 46, "value": "8"},
        {"id": 47, "value": "Metrotel"},
        {"id": 20, "value": "Terraza"},
        {"id": 67, "value": "PARAGUAY"},
        {"id": 68, "value": "Capital Federal"},
        {"id": 69, "value": "Capital Federal"},
        {"id": 91, "value": "1247573"},
        {"id": 203, "value": "00000"},
    ],
    "ll": [-58.40186988, -34.59806882],
    "pts": [5646606.963482, 6170800.675813],
}

# Roseta real 6655863 (clase 85): mismo esquema, menos atributos.
ROSETA_CRUDA = {
    "id": 6655863,
    "n_id": 6655863,
    "class": 85,
    "vmax": 12,
    "name": "RST-66700",
    "at": [
        {"id": 34, "value": "RST-66700", "name": "nombre"},
        {"id": 67, "value": "CHARCAS"},
        {"id": 16, "value": "5131"},
        {"id": 68, "value": "Capital Federal"},
        {"id": 69, "value": "Capital Federal"},
        {"id": 91, "value": "1264856"},
    ],
    "ll": [-58.43015854, -34.57817467],
    "pts": [5644045.963064, 6173048.643082],
}


class TestParsePonElemento:
    def test_identidad_y_clase(self):
        elemento = parse_pon_elemento(CAJA_PON_CRUDA)

        assert elemento.n_id == 6677085
        assert elemento.version_id == 6677085
        assert elemento.vmax == 517
        assert elemento.clase == 84

    def test_direccion_y_nombre_salen_de_los_mismos_at_que_una_botella(self):
        """El mapeo coincide con `parse_botella`: por eso el parser lo reusa en vez de reinventarlo."""
        elemento = parse_pon_elemento(CAJA_PON_CRUDA)

        assert elemento.nombre == "Caja PON Paraguay 2386 C.F. FO37770"
        assert elemento.calle == "PARAGUAY"
        assert elemento.altura == "2386"
        assert elemento.localidad == "Capital Federal"
        assert elemento.codigo_modelo == "PON 8 PORT"
        assert elemento.id_legacy == "1247573"
        assert elemento.tendido == "Terraza"

    def test_los_tres_atributos_propios_de_una_caja_pon(self):
        """at.46 tomó sólo los valores 8, 16 y 4 sobre 81 objetos reales: es la capacidad."""
        elemento = parse_pon_elemento(CAJA_PON_CRUDA)

        assert elemento.capacidad_puertos == 8
        assert elemento.tipo_conector == "Fast connect"
        assert elemento.propietario == "Metrotel"

    def test_capacidad_no_numerica_no_revienta(self):
        """Mismo criterio que `salidas_de_ratio`: ante un valor que no se entiende, None."""
        crudo = {**CAJA_PON_CRUDA, "at": [{"id": 46, "value": "ocho"}]}

        assert parse_pon_elemento(crudo).capacidad_puertos is None

    def test_una_roseta_se_parsea_con_el_mismo_parser(self):
        """Roseta y caja PON comparten esquema; lo que las separa es `cromo_clases.entidad`."""
        elemento = parse_pon_elemento(ROSETA_CRUDA)

        assert elemento.clase == 85
        assert elemento.nombre == "RST-66700"
        assert elemento.calle == "CHARCAS"
        assert elemento.capacidad_puertos is None

    def test_conserva_el_payload_crudo_para_los_atributos_sin_significado(self):
        """at.45 fue constante ('SI' en 81 de 81) y at.203 devolvió valores incoherentes.

        No se les inventa columna ni semántica, pero tampoco se pierden.
        """
        elemento = parse_pon_elemento(CAJA_PON_CRUDA)

        ids = {a["id"] for a in elemento.payload_raw["at"]}
        assert 45 in ids and 203 in ids
