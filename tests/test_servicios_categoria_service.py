# Nombre de archivo: test_servicios_categoria_service.py
# Ubicación de archivo: tests/test_servicios_categoria_service.py
# Descripción: Pruebas del cambio de categoría (individual y masivo) sobre Servicio

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.services.servicios_categoria_service import (
    CategoriaInvalidaError,
    actualizar_categoria_masiva,
    validar_categoria,
)


@pytest.mark.parametrize("categoria", [0, 1, 3, 6])
def test_validar_categoria_acepta_rango_valido(categoria: int) -> None:
    validar_categoria(categoria)  # no debe lanzar


@pytest.mark.parametrize("categoria", [-1, 7, 100])
def test_validar_categoria_rechaza_fuera_de_rango(categoria: int) -> None:
    with pytest.raises(CategoriaInvalidaError, match="entre 0 y 6"):
        validar_categoria(categoria)


def test_actualizar_categoria_masiva_falla_sin_items() -> None:
    session = MagicMock()
    with pytest.raises(CategoriaInvalidaError, match="No se especificaron"):
        actualizar_categoria_masiva(session, [], 3)
    session.query.assert_not_called()


def test_actualizar_categoria_masiva_falla_con_categoria_invalida() -> None:
    session = MagicMock()
    with pytest.raises(CategoriaInvalidaError, match="entre 0 y 6"):
        actualizar_categoria_masiva(session, [1, 2], 9)
    session.query.assert_not_called()


def test_actualizar_categoria_masiva_reporta_no_encontrados_sin_abortar_el_resto() -> None:
    session = MagicMock()
    # Sólo los ids 1 y 2 existen realmente; 99 no.
    session.query.return_value.filter.return_value.all.return_value = [(1,), (2,)]
    session.query.return_value.filter.return_value.update.return_value = 2

    resultado = actualizar_categoria_masiva(session, [1, 2, 99], 5)

    assert resultado.categoria_nueva == 5
    assert resultado.actualizados == 2
    assert resultado.no_encontrados == [99]
    session.flush.assert_called_once()


def test_actualizar_categoria_masiva_todos_no_encontrados_no_llama_update() -> None:
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []

    resultado = actualizar_categoria_masiva(session, [111, 222], 2)

    assert resultado.actualizados == 0
    assert resultado.no_encontrados == [111, 222]
    session.query.return_value.filter.return_value.update.assert_not_called()


def test_resultado_categoria_masiva_to_dict() -> None:
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [(1,)]
    session.query.return_value.filter.return_value.update.return_value = 1

    resultado = actualizar_categoria_masiva(session, [1], 0)

    assert resultado.to_dict() == {"categoria_nueva": 0, "actualizados": 1, "no_encontrados": []}
