# Nombre de archivo: test_ingreso_service.py
# Ubicación de archivo: tests/test_ingreso_service.py
# Descripción: Pruebas de registrar_movimiento_ingreso (creación de Ingreso / cierre NULL-safe de Egreso)

from __future__ import annotations

import operator
from datetime import datetime, timezone
from unittest.mock import MagicMock

from sqlalchemy.sql import operators as sa_operators
from sqlalchemy.sql.elements import Null

from core.services.ingreso_service import registrar_movimiento_ingreso
from db.models.cromo import CromoBotella
from db.models.infra import Camara, Ingreso


def _assert_filtro_null_safe(filtros, columna_attr: str, valor_esperado) -> None:
    """Verifica que, entre los filtros posicionales pasados a `session.query(...).filter(...)`, exista
    uno para `columna_attr` que sea NULL-safe respecto de `valor_esperado`:

    - Si `valor_esperado` es `None`, el filtro debe ser `columna.is_(None)` (operador `is_`, lado
      derecho `Null()`) — nunca `columna == None`, que en SQL genera `columna = NULL` y jamás matchea
      (ni siquiera contra otra fila con la columna en NULL).
    - Si `valor_esperado` no es `None`, el filtro debe comparar por igualdad contra ese valor exacto.
    """
    for expr in filtros:
        if getattr(getattr(expr, "left", None), "key", None) != columna_attr:
            continue
        if valor_esperado is None:
            assert expr.operator is sa_operators.is_, f"{columna_attr}: se esperaba IS NULL (NULL-safe)"
            assert isinstance(expr.right, Null), f"{columna_attr}: el lado derecho debería ser NULL"
        else:
            assert expr.right.value == valor_esperado, f"{columna_attr}: valor de filtro incorrecto"
            assert expr.operator in (operator.eq, sa_operators.is_), f"{columna_attr}: operador inesperado"
        return
    raise AssertionError(f"No se encontró un filtro para la columna '{columna_attr}'")


def _camara(camara_id: int = 10) -> Camara:
    return Camara(id=camara_id, nombre="Cra Test CF")


def _botella(n_id: int = 555) -> CromoBotella:
    return CromoBotella(n_id=n_id)


# --- (a) Ingreso: siempre crea fila nueva ---------------------------------------------------------


def test_ingreso_con_botella_crea_fila_con_cromo_botella_id_poblado() -> None:
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)

    resultado = registrar_movimiento_ingreso(
        session, camara=camara, botella=botella, tipo_movimiento="Ingreso", slack_user_id="U123"
    )

    assert isinstance(resultado, Ingreso)
    assert resultado.camara_id == 10
    assert resultado.cromo_botella_id == 555
    assert resultado.tecnico_id == "U123"
    assert resultado.fecha_inicio is not None
    assert resultado.fecha_fin is None
    session.add.assert_called_once_with(resultado)
    session.commit.assert_called_once()
    # Ingreso nunca busca reabrir/reutilizar filas existentes.
    session.query.assert_not_called()


def test_ingreso_sin_botella_deja_cromo_botella_id_en_none() -> None:
    session = MagicMock()
    camara = _camara()

    resultado = registrar_movimiento_ingreso(
        session, camara=camara, botella=None, tipo_movimiento="Ingreso", slack_user_id="U123"
    )

    assert resultado.cromo_botella_id is None
    assert resultado.fecha_fin is None
    session.add.assert_called_once_with(resultado)
    session.commit.assert_called_once()


# --- (b) Egreso con Ingreso abierto matcheando -----------------------------------------------------


def test_egreso_con_ingreso_abierto_matching_cierra_esa_fila_sin_crear_una_nueva() -> None:
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)
    ingreso_abierto = Ingreso(
        id=1,
        camara_id=10,
        cromo_botella_id=555,
        tecnico_id="U123",
        fecha_inicio=datetime(2026, 8, 30, tzinfo=timezone.utc),
        fecha_fin=None,
    )
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = ingreso_abierto

    resultado = registrar_movimiento_ingreso(
        session, camara=camara, botella=botella, tipo_movimiento="Egreso", slack_user_id="U123"
    )

    assert resultado is ingreso_abierto
    assert resultado.fecha_fin is not None
    session.add.assert_not_called()
    session.commit.assert_called_once()

    filtros = session.query.return_value.filter.call_args[0]
    _assert_filtro_null_safe(filtros, "tecnico_id", "U123")
    _assert_filtro_null_safe(filtros, "camara_id", 10)
    _assert_filtro_null_safe(filtros, "cromo_botella_id", 555)
    session.query.return_value.filter.return_value.order_by.assert_called_once()


# --- (c) Egreso sin Ingreso abierto matcheando -------------------------------------------------------


def test_egreso_sin_ingreso_abierto_matching_crea_fila_nueva_con_fecha_inicio_none() -> None:
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    resultado = registrar_movimiento_ingreso(
        session, camara=camara, botella=botella, tipo_movimiento="Egreso", slack_user_id="U123"
    )

    assert isinstance(resultado, Ingreso)
    assert resultado.camara_id == 10
    assert resultado.cromo_botella_id == 555
    assert resultado.tecnico_id == "U123"
    assert resultado.fecha_inicio is None  # deliberado: nunca fecha_inicio=fecha_fin (duración falsa de 0s)
    assert resultado.fecha_fin is not None
    session.add.assert_called_once_with(resultado)
    session.commit.assert_called_once()


# --- (d) Egreso sin slack_user_id no debe cerrar el ingreso de un técnico real ----------------------


def test_egreso_sin_slack_user_id_filtra_por_tecnico_id_is_null() -> None:
    """El query debe exigir `tecnico_id IS NULL` (NULL-safe) cuando `slack_user_id` es None — nunca
    omitir el criterio ni tratarlo como comodín que matchee cualquier técnico."""
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    registrar_movimiento_ingreso(
        session, camara=camara, botella=botella, tipo_movimiento="Egreso", slack_user_id=None
    )

    filtros = session.query.return_value.filter.call_args[0]
    _assert_filtro_null_safe(filtros, "tecnico_id", None)
