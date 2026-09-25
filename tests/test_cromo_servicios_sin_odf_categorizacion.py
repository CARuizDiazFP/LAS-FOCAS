# Nombre de archivo: test_cromo_servicios_sin_odf_categorizacion.py
# Ubicación de archivo: tests/test_cromo_servicios_sin_odf_categorizacion.py
# Descripción: Tabla de casos de la categorización pura de causa (equipo/nodo PROV) del gestor "Servicios sin ODF"

"""`categorizar()` y `categorizar_extremos()` son funciones PURAS: reciben los valores de
`app.servicios_equipos_ultima_milla` ya leídos y no ejecutan queries. Por eso este módulo no
necesita Postgres — el listado paginado y la cascada de subcategoría, que sí lo necesitan, se
cubren en `tests/test_cromo_servicios_sin_odf_real_db.py`.

Los valores de los casos son reales de dev (`ElRincon842_Pilar`/`OLT2_Pilar`, 618 servicios;
`SW_4_ElRincon842_Pilar`), no inventados.
"""

from __future__ import annotations

import pytest

from core.services.cromo.servicios_sin_odf import (
    CATEGORIA_EQUIPO_DOMICILIO_CLIENTE,
    CATEGORIA_OLT_PON_COMPARTIDO,
    CATEGORIA_SIN_SENAL_PROV,
    CATEGORIA_SWITCH_COMPARTIDO_REVISAR,
    categorizar,
    categorizar_extremos,
)


@pytest.mark.parametrize(
    ("equipo", "nodo", "esperado"),
    [
        # ── OLT_PON_COMPARTIDO: prefijo "OLT" en `equipo`, gana sobre cualquier otra señal ──
        ("OLT2_Pilar", "ElRincon842_Pilar", CATEGORIA_OLT_PON_COMPARTIDO),  # caso real 618/1
        ("olt2_pilar", "ElRincon842_Pilar", CATEGORIA_OLT_PON_COMPARTIDO),  # minúsculas
        ("OlT2_Pilar", "ElRincon842_Pilar", CATEGORIA_OLT_PON_COMPARTIDO),  # mayús/minús mixtas
        ("OLTX", None, CATEGORIA_OLT_PON_COMPARTIDO),  # el prefijo es "OLT", no "OLT_"
        ("  OLT2_Pilar  ", None, CATEGORIA_OLT_PON_COMPARTIDO),  # espacios de sobra
        ("OLT1_Norte", "CLI_UnCliente", CATEGORIA_OLT_PON_COMPARTIDO),  # OLT gana sobre CLI_
        # ── EQUIPO_DOMICILIO_CLIENTE: prefijo "CLI_" en `nodo`, sólo si `equipo` no es OLT ──
        (None, "CLI_UnCliente", CATEGORIA_EQUIPO_DOMICILIO_CLIENTE),
        (None, "cli_uncliente", CATEGORIA_EQUIPO_DOMICILIO_CLIENTE),  # minúsculas
        ("SW_4_ElRincon842_Pilar", "CLI_UnCliente", CATEGORIA_EQUIPO_DOMICILIO_CLIENTE),
        (None, "  CLI_UnCliente  ", CATEGORIA_EQUIPO_DOMICILIO_CLIENTE),
        # ── SWITCH_COMPARTIDO_REVISAR: hay `equipo`, pero no es OLT y el nodo no es CLI_ ──
        ("SW_4_ElRincon842_Pilar", "ElRincon842_Pilar", CATEGORIA_SWITCH_COMPARTIDO_REVISAR),
        ("SW_3", "CLIENTE_algo", CATEGORIA_SWITCH_COMPARTIDO_REVISAR),  # CLIENTE_ NO es CLI_
        ("VOLTA_1", None, CATEGORIA_SWITCH_COMPARTIDO_REVISAR),  # "OLT" contenido, no prefijo
        ("SW_1", "XCLI_algo", CATEGORIA_SWITCH_COMPARTIDO_REVISAR),  # CLI_ no está al inicio
        # ── SIN_SENAL_PROV: sin `equipo` utilizable y sin nodo CLI_ ──
        (None, None, CATEGORIA_SIN_SENAL_PROV),
        (None, "ElRincon842_Pilar", CATEGORIA_SIN_SENAL_PROV),
        (None, "CLIENTE_algo", CATEGORIA_SIN_SENAL_PROV),  # CLIENTE_ NO es CLI_ y no hay equipo
        ("", None, CATEGORIA_SIN_SENAL_PROV),  # string vacío = sin señal, no "otro equipo"
        ("   ", "   ", CATEGORIA_SIN_SENAL_PROV),  # sólo espacios = sin señal
    ],
)
def test_categorizar_devuelve_la_categoria_esperada(equipo, nodo, esperado):
    categoria, subcategoria = categorizar(equipo, nodo)
    assert categoria == esperado
    # `categorizar()` NUNCA devuelve subcategoría: la cascada de SIN_SENAL_PROV es on-demand
    # (`subcategoria_sin_senal_prov`), jamás en el listado paginado.
    assert subcategoria is None


def test_categorizar_cubre_las_cuatro_categorias_posibles():
    """Guarda de completitud: la tabla de arriba ejercita los 4 resultados posibles, no 3."""
    obtenidas = {
        categorizar("OLT2_Pilar", None)[0],
        categorizar(None, "CLI_x")[0],
        categorizar("SW_1", None)[0],
        categorizar(None, None)[0],
    }
    assert obtenidas == {
        CATEGORIA_OLT_PON_COMPARTIDO,
        CATEGORIA_EQUIPO_DOMICILIO_CLIENTE,
        CATEGORIA_SWITCH_COMPARTIDO_REVISAR,
        CATEGORIA_SIN_SENAL_PROV,
    }


@pytest.mark.parametrize(
    ("extremos", "categoria_esperada", "nodo_esperado", "equipo_esperado", "indice_esperado"),
    [
        # Sin fila PROV en absoluto (los 4 servicios reales de dev sin `equipo`).
        ([], CATEGORIA_SIN_SENAL_PROV, None, None, None),
        # Un solo extremo: se usa tal cual.
        (
            [("OLT2_Pilar", "ElRincon842_Pilar")],
            CATEGORIA_OLT_PON_COMPARTIDO,
            "ElRincon842_Pilar",
            "OLT2_Pilar",
            0,
        ),
        # Dos extremos con categorías distintas (204 servicios reales en dev): gana el más
        # informativo, aunque sea el extremo 2 — si no, la sugerencia OLT nunca se ofrecería.
        (
            [("SW_4_ElRincon842_Pilar", "ElRincon842_Pilar"), ("OLT2_Pilar", "OtroNodo")],
            CATEGORIA_OLT_PON_COMPARTIDO,
            "OtroNodo",
            "OLT2_Pilar",
            1,
        ),
        # Mismo caso pero con el OLT en el extremo 1: mismo resultado, sin depender del orden.
        (
            [("OLT2_Pilar", "OtroNodo"), ("SW_4_ElRincon842_Pilar", "ElRincon842_Pilar")],
            CATEGORIA_OLT_PON_COMPARTIDO,
            "OtroNodo",
            "OLT2_Pilar",
            0,
        ),
        # CLI_ en el extremo 2 le gana a un switch genérico en el extremo 1.
        (
            [("SW_1", "NodoGenerico"), (None, "CLI_UnCliente")],
            CATEGORIA_EQUIPO_DOMICILIO_CLIENTE,
            "CLI_UnCliente",
            None,
            1,
        ),
        # Empate de categoría: gana el primer extremo, resultado determinista.
        (
            [("SW_1", "NodoUno"), ("SW_2", "NodoDos")],
            CATEGORIA_SWITCH_COMPARTIDO_REVISAR,
            "NodoUno",
            "SW_1",
            0,
        ),
        # Filas PROV presentes pero sin equipo utilizable en ningún extremo.
        ([(None, "NodoUno"), (None, "NodoDos")], CATEGORIA_SIN_SENAL_PROV, "NodoUno", None, 0),
    ],
)
def test_categorizar_extremos_elige_el_extremo_mas_informativo(
    extremos, categoria_esperada, nodo_esperado, equipo_esperado, indice_esperado
):
    categoria, subcategoria, nodo, equipo, indice = categorizar_extremos(extremos)
    assert categoria == categoria_esperada
    assert subcategoria is None
    assert nodo == nodo_esperado
    assert equipo == equipo_esperado
    assert indice == indice_esperado


def test_categorizar_extremos_devuelve_el_indice_del_ganador_no_su_valor_normalizado():
    """El índice existe porque `nodo`/`equipo` salen normalizados (`.strip()`) y los extremos de
    entrada traen el valor crudo: comparar por valor para saber quién ganó no es confiable."""
    extremos = [("SW_1", "NodoGenerico"), ("  OLT2_Pilar  ", "  OtroNodo  ")]
    _, _, nodo, equipo, indice = categorizar_extremos(extremos)

    assert indice == 1
    # El ganador viene normalizado y NO es igual al crudo, que es justo el punto.
    assert (equipo, nodo) == ("OLT2_Pilar", "OtroNodo")
    assert extremos[indice] == ("  OLT2_Pilar  ", "  OtroNodo  ")
    assert extremos[indice] != (equipo, nodo)


def test_categorizar_extremos_es_consistente_con_categorizar_para_un_extremo():
    """`categorizar_extremos` no reimplementa la regla: delega en `categorizar` por extremo."""
    for equipo, nodo in [
        ("OLT2_Pilar", "ElRincon842_Pilar"),
        (None, "CLI_x"),
        ("SW_1", "NodoGenerico"),
        (None, None),
    ]:
        assert categorizar_extremos([(equipo, nodo)])[:2] == categorizar(equipo, nodo)
