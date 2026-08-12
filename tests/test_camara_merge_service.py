# Nombre de archivo: test_camara_merge_service.py
# Ubicación de archivo: tests/test_camara_merge_service.py
# Descripción: Pruebas de la unificación de Cámaras raíz duplicadas — reparentado como Botella, migración de Botellas Cromo, alias, estado final

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.services.camara_merge_service import MergeCamarasError, unificar_camaras
from db.models.infra import Camara, CamaraAlias, CamaraEstado


def _sesion_con_camaras(principal: Camara, secundaria: Camara, *, alias_existente=None, cromo_migradas: int = 0) -> MagicMock:
    session = MagicMock()
    session.query.return_value.filter.return_value.first.side_effect = [principal, secundaria, alias_existente]
    session.query.return_value.filter.return_value.update.return_value = cromo_migradas
    return session


def test_unificar_camaras_falla_si_son_la_misma() -> None:
    session = MagicMock()
    with pytest.raises(MergeCamarasError, match="no pueden ser la misma"):
        unificar_camaras(session, principal_id=1, secundaria_id=1, usuario="test")
    session.query.assert_not_called()


def test_unificar_camaras_falla_si_principal_no_existe() -> None:
    session = MagicMock()
    session.query.return_value.filter.return_value.first.side_effect = [None]
    with pytest.raises(MergeCamarasError, match="principal no encontrada"):
        unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="test")


def test_unificar_camaras_falla_si_secundaria_no_existe() -> None:
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    session = MagicMock()
    session.query.return_value.filter.return_value.first.side_effect = [principal, None]
    with pytest.raises(MergeCamarasError, match="secundaria no encontrada"):
        unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="test")


@pytest.mark.parametrize("principal_padre,secundaria_padre", [(5, None), (None, 5)])
def test_unificar_camaras_falla_si_alguna_ya_es_botella(principal_padre, secundaria_padre) -> None:
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE, camara_padre_id=principal_padre)
    secundaria = Camara(id=2, nombre="Cra Secundaria CF", estado=CamaraEstado.LIBRE, camara_padre_id=secundaria_padre)
    session = MagicMock()
    session.query.return_value.filter.return_value.first.side_effect = [principal, secundaria]
    with pytest.raises(MergeCamarasError, match="Cámaras raíz"):
        unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="test")


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_reparenta_secundaria_y_sus_botellas(mock_grupo, mock_aplicar) -> None:
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="Cra Secundaria CF", estado=CamaraEstado.LIBRE)
    botella_de_secundaria = Camara(id=3, nombre="Cra Secundaria CF Bot 2", estado=CamaraEstado.LIBRE, camara_padre_id=2)
    secundaria.botellas = [botella_de_secundaria]
    mock_grupo.return_value = [principal]  # mismo estado, no dispara aplicar_estado_a_grupo

    session = _sesion_con_camaras(principal, secundaria)
    resultado = unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin")

    assert secundaria.camara_padre_id == 1
    assert botella_de_secundaria.camara_padre_id == 1
    assert resultado.botellas_legado_migradas == 1
    mock_aplicar.assert_not_called()  # el grupo ya estaba consistente (mismo estado)


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_migra_botellas_cromo(mock_grupo, mock_aplicar) -> None:
    principal = Camara(id=10, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=20, nombre="Cra Secundaria CF", estado=CamaraEstado.LIBRE)
    secundaria.botellas = []
    mock_grupo.return_value = [principal]

    session = _sesion_con_camaras(principal, secundaria, cromo_migradas=4)
    resultado = unificar_camaras(session, principal_id=10, secundaria_id=20, usuario="admin")

    assert resultado.botellas_cromo_migradas == 4


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_crea_alias_con_nombre_de_secundaria(mock_grupo, mock_aplicar) -> None:
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="Cra Secundaria Distinta CF", estado=CamaraEstado.LIBRE)
    secundaria.botellas = []
    mock_grupo.return_value = [principal]

    session = _sesion_con_camaras(principal, secundaria, alias_existente=None)
    resultado = unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin")

    assert resultado.alias_creado is True
    alias_agregado = session.add.call_args[0][0]
    assert isinstance(alias_agregado, CamaraAlias)
    assert alias_agregado.camara_id == 1
    assert alias_agregado.alias_nombre == "Cra Secundaria Distinta CF"


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_no_duplica_alias_ya_existente(mock_grupo, mock_aplicar) -> None:
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="Cra Secundaria Distinta CF", estado=CamaraEstado.LIBRE)
    secundaria.botellas = []
    mock_grupo.return_value = [principal]
    alias_existente = CamaraAlias(id=99, camara_id=1, alias_nombre="Cra Secundaria Distinta CF")

    session = _sesion_con_camaras(principal, secundaria, alias_existente=alias_existente)
    resultado = unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin")

    assert resultado.alias_creado is False
    session.add.assert_not_called()


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_no_crea_alias_si_los_nombres_coinciden(mock_grupo, mock_aplicar) -> None:
    principal = Camara(id=1, nombre="Cra Igual CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="cra igual cf", estado=CamaraEstado.LIBRE)  # sólo difiere en case
    secundaria.botellas = []
    mock_grupo.return_value = [principal]

    session = MagicMock()
    session.query.return_value.filter.return_value.first.side_effect = [principal, secundaria]
    session.query.return_value.filter.return_value.update.return_value = 0

    resultado = unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin")

    assert resultado.alias_creado is False
    session.add.assert_not_called()


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_aplica_estado_mas_restrictivo_del_grupo(mock_grupo, mock_aplicar) -> None:
    """El estado final del grupo (principal + su Botella recién reparentada) es el más restrictivo —
    mismo criterio que la cascada de baneo existente."""
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="Cra Secundaria CF", estado=CamaraEstado.BANEADA)
    secundaria.botellas = []
    # Tras el reparent, el grupo real sería [principal(LIBRE), secundaria(BANEADA)] — se simula acá.
    mock_grupo.return_value = [principal, secundaria]

    session = _sesion_con_camaras(principal, secundaria)
    resultado = unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin")

    assert resultado.estado_final == "BANEADA"
    mock_aplicar.assert_called_once()
    args, kwargs = mock_aplicar.call_args
    assert args[1] is principal
    assert args[2] == CamaraEstado.BANEADA
    assert kwargs["usuario"] == "admin"
