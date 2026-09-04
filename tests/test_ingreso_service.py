# Nombre de archivo: test_ingreso_service.py
# Ubicación de archivo: tests/test_ingreso_service.py
# Descripción: Pruebas de registrar_movimiento_ingreso/registrar_intento_bloqueado (creación de Ingreso, cierre NULL-safe de Egreso, Intento bloqueado por baneo)

from __future__ import annotations

import operator
from datetime import datetime, timezone
from unittest.mock import MagicMock

from sqlalchemy.sql import operators as sa_operators
from sqlalchemy.sql.elements import Null

from core.services.ingreso_service import registrar_intento_bloqueado, registrar_movimiento_ingreso
from db.models.cromo import CromoBotella
from db.models.infra import Camara, Ingreso, IngresoTipo


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


def _assert_filtro_igualdad(filtros, columna_attr: str, valor_esperado) -> None:
    """Verifica un filtro de igualdad simple (no NULL-safe) — usado para `tipo`, que nunca es None."""
    for expr in filtros:
        if getattr(getattr(expr, "left", None), "key", None) != columna_attr:
            continue
        assert expr.right.value == valor_esperado, f"{columna_attr}: valor de filtro incorrecto"
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
        session, camara=camara, botella=botella, tipo_movimiento="Ingreso", tecnico_nombre="Rider Fernández"
    )

    assert isinstance(resultado, Ingreso)
    assert resultado.camara_id == 10
    assert resultado.cromo_botella_id == 555
    assert resultado.tecnico_id == "Rider Fernández"
    assert resultado.tipo == IngresoTipo.INGRESO
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
        session, camara=camara, botella=None, tipo_movimiento="Ingreso", tecnico_nombre="Rider Fernández"
    )

    assert resultado.cromo_botella_id is None
    assert resultado.tipo == IngresoTipo.INGRESO
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
        tecnico_id="Rider Fernández",
        tipo=IngresoTipo.INGRESO,
        fecha_inicio=datetime(2026, 8, 30, tzinfo=timezone.utc),
        fecha_fin=None,
    )
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = ingreso_abierto

    resultado = registrar_movimiento_ingreso(
        session, camara=camara, botella=botella, tipo_movimiento="Egreso", tecnico_nombre="Rider Fernández"
    )

    assert resultado is ingreso_abierto
    assert resultado.fecha_fin is not None
    session.add.assert_not_called()
    session.commit.assert_called_once()

    filtros = session.query.return_value.filter.call_args[0]
    _assert_filtro_null_safe(filtros, "tecnico_id", "Rider Fernández")
    _assert_filtro_null_safe(filtros, "camara_id", 10)
    _assert_filtro_null_safe(filtros, "cromo_botella_id", 555)
    # "ABIERTO" — sin este filtro, un Ingreso ya cerrado (fecha_fin no nula) sería candidato a
    # "cerrarse" de nuevo, pisando su fecha_fin real con la de este movimiento.
    _assert_filtro_null_safe(filtros, "fecha_fin", None)
    # Sin este filtro, un Intento bloqueado (mismo fecha_fin IS NULL) podría cerrarse como si fuera
    # un Ingreso real — ver registrar_intento_bloqueado() más abajo.
    _assert_filtro_igualdad(filtros, "tipo", IngresoTipo.INGRESO)
    session.query.return_value.filter.return_value.order_by.assert_called_once()


# --- (c) Egreso sin Ingreso abierto matcheando -------------------------------------------------------


def test_egreso_sin_ingreso_abierto_matching_crea_fila_nueva_con_fecha_inicio_none() -> None:
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    resultado = registrar_movimiento_ingreso(
        session, camara=camara, botella=botella, tipo_movimiento="Egreso", tecnico_nombre="Rider Fernández"
    )

    assert isinstance(resultado, Ingreso)
    assert resultado.camara_id == 10
    assert resultado.cromo_botella_id == 555
    assert resultado.tecnico_id == "Rider Fernández"
    assert resultado.tipo == IngresoTipo.EGRESO
    assert resultado.fecha_inicio is None  # deliberado: nunca fecha_inicio=fecha_fin (duración falsa de 0s)
    assert resultado.fecha_fin is not None
    session.add.assert_called_once_with(resultado)
    session.commit.assert_called_once()

    filtros = session.query.return_value.filter.call_args[0]
    _assert_filtro_null_safe(filtros, "fecha_fin", None)


# --- (d) Egreso sin tecnico_nombre no debe cerrar el ingreso de un técnico real ----------------------


def test_egreso_sin_tecnico_nombre_filtra_por_tecnico_id_is_null() -> None:
    """El query debe exigir `tecnico_id IS NULL` (NULL-safe) cuando `tecnico_nombre` es None — nunca
    omitir el criterio ni tratarlo como comodín que matchee cualquier técnico."""
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    registrar_movimiento_ingreso(
        session, camara=camara, botella=botella, tipo_movimiento="Egreso", tecnico_nombre=None
    )

    filtros = session.query.return_value.filter.call_args[0]
    _assert_filtro_null_safe(filtros, "tecnico_id", None)
    _assert_filtro_null_safe(filtros, "fecha_fin", None)


# --- (e) Intento bloqueado (Tarea 4, 2026-09-04) ----------------------------------------------------


def test_registrar_intento_bloqueado_crea_fila_tipo_intento_sin_egreso() -> None:
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)

    resultado = registrar_intento_bloqueado(
        session, camara=camara, botella=botella, tecnico_nombre="Rider Fernández"
    )

    assert isinstance(resultado, Ingreso)
    assert resultado.camara_id == 10
    assert resultado.cromo_botella_id == 555
    assert resultado.tecnico_id == "Rider Fernández"
    assert resultado.tipo == IngresoTipo.INTENTO_BLOQUEADO
    assert resultado.fecha_inicio is not None
    assert resultado.fecha_fin is None
    session.add.assert_called_once_with(resultado)
    session.commit.assert_called_once()
    # Nunca busca reabrir/cerrar una fila existente — un intento bloqueado es siempre una fila nueva.
    session.query.assert_not_called()


def test_registrar_intento_bloqueado_sin_botella_deja_cromo_botella_id_en_none() -> None:
    session = MagicMock()
    camara = _camara()

    resultado = registrar_intento_bloqueado(session, camara=camara, botella=None, tecnico_nombre=None)

    assert resultado.cromo_botella_id is None
    assert resultado.tecnico_id is None
    assert resultado.tipo == IngresoTipo.INTENTO_BLOQUEADO


# --- (f) slack_user_id: matching ampliado para cerrar filas viejas con id crudo (I2, 2026-09-04) ---


def test_egreso_cierra_ingreso_abierto_con_tecnico_id_igual_al_slack_user_id_crudo() -> None:
    """Bug real (hallazgo I2, revisión final): una fila escrita ANTES del deploy de la resolución de
    nombre tiene `tecnico_id` = el ID crudo de Slack (nunca hubo `resolver_nombre_tecnico` para
    escribirla). El Egreso del mismo técnico, DESPUÉS del deploy, resuelve `tecnico_nombre` a un
    nombre humano — deben matchear igual (vía `slack_user_id`, el id crudo de este mismo evento) o
    la fila vieja queda abierta para siempre y se crea una fila EGRESO huérfana de más."""
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)
    ingreso_abierto_viejo = Ingreso(
        id=1,
        camara_id=10,
        cromo_botella_id=555,
        tecnico_id="U03DPFK0Q69",  # fila pre-fix: id crudo de Slack, nunca resuelto
        tipo=IngresoTipo.INGRESO,
        fecha_inicio=datetime(2026, 8, 30, tzinfo=timezone.utc),
        fecha_fin=None,
    )
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = ingreso_abierto_viejo

    resultado = registrar_movimiento_ingreso(
        session,
        camara=camara,
        botella=botella,
        tipo_movimiento="Egreso",
        tecnico_nombre="rider.fernandez",
        slack_user_id="U03DPFK0Q69",
    )

    assert resultado is ingreso_abierto_viejo
    assert resultado.fecha_fin is not None
    session.add.assert_not_called()

    filtros = session.query.return_value.filter.call_args[0]
    tecnico_filtro = next(
        expr for expr in filtros if getattr(getattr(expr, "left", None), "key", None) == "tecnico_id"
    )
    # Debe ser un IN (matchea CUALQUIERA de los dos valores), no una igualdad simple contra uno solo.
    assert set(tecnico_filtro.right.value) == {"rider.fernandez", "U03DPFK0Q69"}


def test_egreso_sin_slack_user_id_sigue_usando_igualdad_simple_contra_tecnico_nombre() -> None:
    """Sin `slack_user_id` (default `None`, callers que no lo conocen), el filtro debe seguir siendo
    una igualdad simple contra `tecnico_nombre` — comportamiento sin cambios."""
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    registrar_movimiento_ingreso(
        session, camara=camara, botella=botella, tipo_movimiento="Egreso", tecnico_nombre="Rider Fernández"
    )

    filtros = session.query.return_value.filter.call_args[0]
    _assert_filtro_null_safe(filtros, "tecnico_id", "Rider Fernández")


def test_egreso_tecnico_nombre_y_slack_user_id_iguales_no_genera_in_redundante() -> None:
    """Si `tecnico_nombre` y `slack_user_id` terminan siendo el mismo valor (ej.
    `resolver_nombre_tecnico` cayó al id crudo porque `users.info` falló), el filtro debe seguir
    siendo una igualdad simple, no un IN de un solo elemento."""
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    registrar_movimiento_ingreso(
        session,
        camara=camara,
        botella=botella,
        tipo_movimiento="Egreso",
        tecnico_nombre="U03DPFK0Q69",
        slack_user_id="U03DPFK0Q69",
    )

    filtros = session.query.return_value.filter.call_args[0]
    _assert_filtro_null_safe(filtros, "tecnico_id", "U03DPFK0Q69")


def test_egreso_tecnico_nombre_y_slack_user_id_ambos_none_exige_is_null_no_comodin() -> None:
    """NULL-safe explícito con `slack_user_id=None` también pasado: ambos `None` debe seguir
    exigiendo `tecnico_id IS NULL`, nunca tratarse como comodín que matchee cualquier técnico."""
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    registrar_movimiento_ingreso(
        session,
        camara=camara,
        botella=botella,
        tipo_movimiento="Egreso",
        tecnico_nombre=None,
        slack_user_id=None,
    )

    filtros = session.query.return_value.filter.call_args[0]
    _assert_filtro_null_safe(filtros, "tecnico_id", None)


def test_ingreso_con_slack_user_id_escribe_tecnico_id_como_nombre_resuelto_no_id_crudo() -> None:
    """Aunque se pase `slack_user_id`, una fila NUEVA de Ingreso siempre escribe `tecnico_id` =
    `tecnico_nombre` (el nombre YA resuelto) — `slack_user_id` sólo sirve para ENCONTRAR una fila a
    cerrar en el camino de Egreso, nunca se persiste."""
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)

    resultado = registrar_movimiento_ingreso(
        session,
        camara=camara,
        botella=botella,
        tipo_movimiento="Ingreso",
        tecnico_nombre="rider.fernandez",
        slack_user_id="U03DPFK0Q69",
    )

    assert resultado.tecnico_id == "rider.fernandez"


def test_egreso_huerfano_nuevo_escribe_tecnico_id_como_nombre_resuelto() -> None:
    """Misma garantía que el test anterior, para la fila EGRESO huérfana (sin match) que crea el
    camino de Egreso."""
    session = MagicMock()
    camara = _camara()
    botella = _botella(n_id=555)
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    resultado = registrar_movimiento_ingreso(
        session,
        camara=camara,
        botella=botella,
        tipo_movimiento="Egreso",
        tecnico_nombre="rider.fernandez",
        slack_user_id="U03DPFK0Q69",
    )

    assert resultado.tecnico_id == "rider.fernandez"
