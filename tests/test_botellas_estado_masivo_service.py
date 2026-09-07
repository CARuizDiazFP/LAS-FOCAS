# Nombre de archivo: test_botellas_estado_masivo_service.py
# Ubicación de archivo: tests/test_botellas_estado_masivo_service.py
# Descripción: Pruebas del cambio de estado masivo sobre Botellas de origen mixto (Cromo + legado)

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.services.botellas_estado_masivo_service import (
    EstadoMasivoError,
    ItemBotellaEstado,
    actualizar_estado_masivo,
)
from db.models.infra import Camara, CamaraEstado


def test_actualizar_estado_masivo_falla_sin_items() -> None:
    session = MagicMock()
    with pytest.raises(EstadoMasivoError, match="No se especificaron"):
        actualizar_estado_masivo(session, [], CamaraEstado.NO_OPERATIVA, usuario="admin", motivo="test")
    session.query.assert_not_called()


def test_actualizar_estado_masivo_falla_con_estado_no_admisible() -> None:
    """DETECTADA/PENDIENTE_REVISION siguen en el enum de Postgres por filas legado, pero ya no son
    asignables — mismo criterio que `update_camara_estado_web`."""
    session = MagicMock()
    with pytest.raises(EstadoMasivoError, match="Estado inválido"):
        actualizar_estado_masivo(
            session,
            [ItemBotellaEstado(origen="legado", id=1)],
            CamaraEstado.DETECTADA,
            usuario="admin",
            motivo="test",
        )
    session.query.assert_not_called()


def test_actualizar_estado_masivo_falla_con_origen_invalido() -> None:
    session = MagicMock()
    with pytest.raises(EstadoMasivoError, match="Origen inválido"):
        actualizar_estado_masivo(
            session,
            [ItemBotellaEstado(origen="otro", id=1)],
            CamaraEstado.NO_OPERATIVA,
            usuario="admin",
            motivo="test",
        )


@patch("core.services.botellas_estado_masivo_service.aplicar_estado_a_grupo")
def test_actualizar_estado_masivo_legado_dedupe_por_grupo(mock_aplicar) -> None:
    """Seleccionar dos miembros del mismo grupo (padre + su propia Botella) no debe cascadear el
    grupo dos veces."""
    padre = Camara(id=1, nombre="Cra Test CF", estado=CamaraEstado.LIBRE)
    botella = Camara(id=2, nombre="Cra Test CF Bot 2", estado=CamaraEstado.LIBRE, camara_padre_id=1)
    botella.camara_padre = padre
    mock_aplicar.return_value = [MagicMock(), MagicMock()]  # 2 filas modificadas

    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [padre, botella]

    resultado = actualizar_estado_masivo(
        session,
        [ItemBotellaEstado(origen="legado", id=1), ItemBotellaEstado(origen="legado", id=2)],
        CamaraEstado.NO_OPERATIVA,
        usuario="admin",
        motivo="test",
    )

    mock_aplicar.assert_called_once()
    args, kwargs = mock_aplicar.call_args
    assert args[1] is padre
    assert args[2] == CamaraEstado.NO_OPERATIVA
    assert kwargs["usuario"] == "admin"
    assert resultado.legado_actualizadas == 2
    assert resultado.no_encontrados == []


@patch("core.services.botellas_estado_masivo_service.aplicar_estado_a_grupo")
def test_actualizar_estado_masivo_legado_dos_grupos_distintos(mock_aplicar) -> None:
    padre1 = Camara(id=1, nombre="Cra Uno CF", estado=CamaraEstado.LIBRE)
    padre2 = Camara(id=2, nombre="Cra Dos CF", estado=CamaraEstado.LIBRE)
    mock_aplicar.return_value = [MagicMock()]  # 1 fila modificada por llamada

    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [padre1, padre2]

    resultado = actualizar_estado_masivo(
        session,
        [ItemBotellaEstado(origen="legado", id=1), ItemBotellaEstado(origen="legado", id=2)],
        CamaraEstado.BANEADA,
        usuario="admin",
        motivo="test",
    )

    assert mock_aplicar.call_count == 2
    assert resultado.legado_actualizadas == 2


@patch("core.services.botellas_estado_masivo_service.aplicar_estado_a_grupo")
def test_actualizar_estado_masivo_legado_reporta_no_encontrados(mock_aplicar) -> None:
    padre1 = Camara(id=1, nombre="Cra Uno CF", estado=CamaraEstado.LIBRE)
    mock_aplicar.return_value = []

    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [padre1]

    resultado = actualizar_estado_masivo(
        session,
        [ItemBotellaEstado(origen="legado", id=1), ItemBotellaEstado(origen="legado", id=999)],
        CamaraEstado.NO_OPERATIVA,
        usuario="admin",
        motivo="test",
    )

    assert resultado.no_encontrados == [ItemBotellaEstado(origen="legado", id=999)]


def test_actualizar_estado_masivo_cromo_update_masivo() -> None:
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [(10,), (20,)]
    session.query.return_value.filter.return_value.update.return_value = 2

    resultado = actualizar_estado_masivo(
        session,
        [ItemBotellaEstado(origen="cromo", id=10), ItemBotellaEstado(origen="cromo", id=20)],
        CamaraEstado.NO_OPERATIVA,
        usuario="admin",
        motivo="test",
    )

    assert resultado.cromo_actualizadas == 2
    assert resultado.no_encontrados == []


def test_actualizar_estado_masivo_cromo_reporta_no_encontrados_sin_update() -> None:
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []

    resultado = actualizar_estado_masivo(
        session,
        [ItemBotellaEstado(origen="cromo", id=999)],
        CamaraEstado.NO_OPERATIVA,
        usuario="admin",
        motivo="test",
    )

    assert resultado.cromo_actualizadas == 0
    assert resultado.no_encontrados == [ItemBotellaEstado(origen="cromo", id=999)]
    session.query.return_value.filter.return_value.update.assert_not_called()


def test_resultado_to_dict_serializa_no_encontrados() -> None:
    from core.services.botellas_estado_masivo_service import ResultadoEstadoMasivo

    resultado = ResultadoEstadoMasivo(
        estado_nuevo="NO_OPERATIVA",
        legado_actualizadas=1,
        cromo_actualizadas=2,
        no_encontrados=[ItemBotellaEstado(origen="cromo", id=999)],
    )

    assert resultado.to_dict() == {
        "estado_nuevo": "NO_OPERATIVA",
        "legado_actualizadas": 1,
        "cromo_actualizadas": 2,
        "no_encontrados": [{"origen": "cromo", "id": 999}],
    }
