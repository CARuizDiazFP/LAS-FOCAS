# Nombre de archivo: test_clientes_categoria_service.py
# Ubicación de archivo: tests/test_clientes_categoria_service.py
# Descripción: Pruebas unitarias (sin DB) de la normalización de clientes y la regla de categoría automática

from __future__ import annotations

import pytest

from core.parsers.servicios_excel import limpiar_clave
from core.services.clientes_categoria_service import (
    claves_de_nombres,
    elegir_categoria_automatica,
    nombre_mas_frecuente,
    normalizar_clave_cliente,
)


def test_limpiar_clave_es_publica_y_normaliza() -> None:
    assert limpiar_clave("  Él Ñandú S.A.  ") == "el nandu s a"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("BANCO DE GALICIA Y BUENOS AIRES SA", "BANCO DE GALICIA Y BUENOS AIRES S A U"),
        ("Banco de Galicia y Buenos Aires SA", "BANCO DE GALICIA Y BUENOS AIRES SA"),
        ("INVAP", "INVAP S.A.U."),
        ("BANCO CREDICOOP", "BANCO CREDICOOP COOPERATIVO LTDO"),
        ("GRUPO ILHSA", "GRUPO ILHSA SOCIEDAD ANONIMA"),
        ("ACME S.R.L.", "Acme SRL"),
        ("ACME SAIC", "ACME"),
        ("ACME INC.", "acme"),
    ],
)
def test_variantes_societarias_colapsan(a: str, b: str) -> None:
    assert normalizar_clave_cliente(a) == normalizar_clave_cliente(b)


def test_galicia_clave_exacta() -> None:
    assert normalizar_clave_cliente("BANCO DE GALICIA Y BUENOS AIRES S A U") == "BANCO DE GALICIA Y BUENOS AIRES"


def test_arsat_no_colapsa_solo() -> None:
    a = normalizar_clave_cliente("EMPRESA ARGENTINA DE SOLUCIONES SATELITALES (ARSAT)")
    b = normalizar_clave_cliente("EMPRESA ARGENTINA DE SOLUCIONES SATELITALES SOCIEDAD ANONIMA ARSAT")
    assert a != b


@pytest.mark.parametrize("nombre", ["SA", "S A", "INC"])
def test_no_deja_la_clave_vacia(nombre: str) -> None:
    assert normalizar_clave_cliente(nombre) == nombre


@pytest.mark.parametrize("nombre", [None, "", "   ", "---"])
def test_nombre_vacio_da_none(nombre: str | None) -> None:
    assert normalizar_clave_cliente(nombre) is None


def test_sufijo_solo_al_final() -> None:
    # "SA" en el medio no se toca; "SAN" no es sufijo.
    assert normalizar_clave_cliente("SA DE TRANSPORTE SAN") == "SA DE TRANSPORTE SAN"


def test_claves_de_nombres_ignora_vacios_y_deduplica() -> None:
    assert claves_de_nombres(["Acme SA", "ACME S.A.", "", None, "Otro"]) == {"ACME", "OTRO"}


def test_nombre_mas_frecuente_desempata_alfabetico() -> None:
    assert nombre_mas_frecuente({"Acme SA": 3, "ACME SA": 5}) == "ACME SA"
    assert nombre_mas_frecuente({"b": 2, "a": 2}) == "a"


class TestElegirCategoriaAutomatica:
    def test_moda_sla(self) -> None:
        assert elegir_categoria_automatica({3: 5, 4: 1}, hay_servicios=True) == (3, "SLA", True)

    def test_empate_gana_la_mas_alta(self) -> None:
        assert elegir_categoria_automatica({2: 3, 5: 3}, hay_servicios=False) == (5, "SLA", True)

    def test_una_sola_categoria_no_queda_a_revisar(self) -> None:
        assert elegir_categoria_automatica({6: 10}, hay_servicios=False) == (6, "SLA", False)

    def test_ignora_categorias_fuera_de_1_a_6(self) -> None:
        # categoria_sla 0 no cuenta como dato SLA; tiene servicios → 0 AUTO.
        assert elegir_categoria_automatica({0: 4}, hay_servicios=True) == (0, "AUTO", False)

    def test_sin_sla_con_servicios_queda_cero(self) -> None:
        assert elegir_categoria_automatica({}, hay_servicios=True) == (0, "AUTO", False)

    def test_sin_servicios_queda_null(self) -> None:
        assert elegir_categoria_automatica({}, hay_servicios=False) == (None, "AUTO", False)
