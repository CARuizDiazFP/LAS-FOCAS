# Nombre de archivo: test_botella_merge_service.py
# Ubicación de archivo: tests/test_botella_merge_service.py
# Descripción: Pruebas de la apropiación legado→Cromo de Botellas duplicadas — Cromo se conserva, la legado se elimina tras reasignar sus FKs al padre

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.services.botella_merge_service import ApropiacionBotellaError, apropiar_legado_a_cromo
from db.models.cromo import CromoBotella
from db.models.infra import Cable, Camara, CamaraAlias, CamaraEstado, CamaraEstadoAuditoria, Empalme, Ingreso


def _build_session(
    legado: Camara,
    cromo: CromoBotella,
    padre: Camara,
    *,
    botellas_legado_migradas: int = 0,
    cromo_reasignadas: int = 0,
    cables_migrados: tuple[int, int] = (0, 0),
    empalmes_migrados: int = 0,
    ingresos_migrados: int = 0,
    aliases_existentes_padre: list[str] | None = None,
) -> MagicMock:
    session = MagicMock()
    model_mocks: dict[object, MagicMock] = {}

    def mock_para(modelo: object) -> MagicMock:
        if modelo not in model_mocks:
            model_mocks[modelo] = MagicMock()
        return model_mocks[modelo]

    mock_para(Camara).filter.return_value.first.side_effect = [legado, padre]
    mock_para(Camara).filter.return_value.update.return_value = botellas_legado_migradas
    mock_para(CromoBotella).filter.return_value.first.return_value = cromo
    mock_para(CromoBotella).filter.return_value.update.return_value = cromo_reasignadas
    mock_para(Cable).filter.return_value.update.side_effect = list(cables_migrados)
    mock_para(Empalme).filter.return_value.update.return_value = empalmes_migrados
    mock_para(Ingreso).filter.return_value.update.return_value = ingresos_migrados
    mock_para(CamaraEstadoAuditoria).filter.return_value.update.return_value = 0

    alias_col_mock = MagicMock()
    alias_col_mock.filter.return_value.all.return_value = [
        (nombre,) for nombre in (aliases_existentes_padre or [])
    ]

    def query_side_effect(target: object, *_args: object) -> MagicMock:
        if target is CamaraAlias.alias_nombre:
            return alias_col_mock
        return mock_para(target)

    session.query.side_effect = query_side_effect
    session.model_mocks = model_mocks
    return session


def test_apropiar_falla_si_legado_no_existe() -> None:
    session = MagicMock()
    camara_mock = MagicMock()
    camara_mock.filter.return_value.first.return_value = None
    session.query.side_effect = lambda modelo, *a: camara_mock

    with pytest.raises(ApropiacionBotellaError, match="no encontrada"):
        apropiar_legado_a_cromo(session, legado_id=1, cromo_n_id=100, usuario="admin")


def test_apropiar_falla_si_legado_no_es_botella() -> None:
    legado = Camara(id=1, nombre="Cra Rivadavia 100 CF", camara_padre_id=None)
    session = MagicMock()
    camara_mock = MagicMock()
    camara_mock.filter.return_value.first.return_value = legado
    session.query.side_effect = lambda modelo, *a: camara_mock

    with pytest.raises(ApropiacionBotellaError, match="no es una Botella"):
        apropiar_legado_a_cromo(session, legado_id=1, cromo_n_id=100, usuario="admin")


def test_apropiar_falla_si_cromo_no_existe() -> None:
    legado = Camara(id=1, nombre="Bot 2", camara_padre_id=10)
    session = MagicMock()
    model_mocks: dict[object, MagicMock] = {}

    def mock_para(modelo):
        if modelo not in model_mocks:
            model_mocks[modelo] = MagicMock()
        return model_mocks[modelo]

    mock_para(Camara).filter.return_value.first.return_value = legado
    mock_para(CromoBotella).filter.return_value.first.return_value = None
    session.query.side_effect = lambda modelo, *a: mock_para(modelo)

    with pytest.raises(ApropiacionBotellaError, match="Cromo no encontrada"):
        apropiar_legado_a_cromo(session, legado_id=1, cromo_n_id=100, usuario="admin")


def test_apropiar_falla_si_cromo_pertenece_a_otro_padre() -> None:
    legado = Camara(id=1, nombre="Bot 2", camara_padre_id=10)
    cromo = CromoBotella(n_id=100, nombre="Bot 2", camara_id=99)  # padre distinto
    session = MagicMock()
    model_mocks: dict[object, MagicMock] = {}

    def mock_para(modelo):
        if modelo not in model_mocks:
            model_mocks[modelo] = MagicMock()
        return model_mocks[modelo]

    mock_para(Camara).filter.return_value.first.return_value = legado
    mock_para(CromoBotella).filter.return_value.first.return_value = cromo
    session.query.side_effect = lambda modelo, *a: mock_para(modelo)

    with pytest.raises(ApropiacionBotellaError, match="misma Cámara padre"):
        apropiar_legado_a_cromo(session, legado_id=1, cromo_n_id=100, usuario="admin")


@patch("core.services.botella_merge_service.aplicar_estado_a_grupo")
@patch("core.services.botella_merge_service.miembros_del_grupo")
def test_apropiar_reasigna_cables_empalmes_ingresos_auditoria_al_padre_antes_de_eliminar(mock_grupo, mock_aplicar) -> None:
    legado = Camara(id=1, nombre="Bot 2", camara_padre_id=10, estado=CamaraEstado.LIBRE)
    cromo = CromoBotella(n_id=100, nombre="Botella 2", camara_id=10, estado=CamaraEstado.LIBRE)
    padre = Camara(id=10, nombre="Cra Rivadavia 100 CF", estado=CamaraEstado.LIBRE)
    legado.aliases = []
    mock_grupo.return_value = [padre]

    session = _build_session(
        legado, cromo, padre,
        cables_migrados=(2, 1), empalmes_migrados=5, ingresos_migrados=3,
    )
    resultado = apropiar_legado_a_cromo(session, legado_id=1, cromo_n_id=100, usuario="admin")

    assert resultado.cables_migrados == 3  # 2 origen + 1 destino
    assert resultado.empalmes_migrados == 5
    assert resultado.ingresos_migrados == 3

    model_mocks = session.model_mocks
    model_mocks[Empalme].filter.return_value.update.assert_called_once_with(
        {Empalme.camara_id: padre.id}, synchronize_session=False
    )
    model_mocks[Ingreso].filter.return_value.update.assert_called_once_with(
        {Ingreso.camara_id: padre.id}, synchronize_session=False
    )
    session.delete.assert_any_call(legado)


@patch("core.services.botella_merge_service.aplicar_estado_a_grupo")
@patch("core.services.botella_merge_service.miembros_del_grupo")
def test_apropiar_reasigna_hijas_propias_de_la_legado_al_padre(mock_grupo, mock_aplicar) -> None:
    """Caso defensivo: una Botella legado no debería tener hijas propias (invariante de 2 niveles),
    pero hay filas reales que ya lo violan — se reasignan al padre igual, nunca se ignoran."""
    legado = Camara(id=1, nombre="Bot 2", camara_padre_id=10, estado=CamaraEstado.LIBRE)
    cromo = CromoBotella(n_id=100, nombre="Botella 2", camara_id=10, estado=CamaraEstado.LIBRE)
    padre = Camara(id=10, nombre="Cra Rivadavia 100 CF", estado=CamaraEstado.LIBRE)
    legado.aliases = []
    mock_grupo.return_value = [padre]

    session = _build_session(legado, cromo, padre, botellas_legado_migradas=1, cromo_reasignadas=1)
    resultado = apropiar_legado_a_cromo(session, legado_id=1, cromo_n_id=100, usuario="admin")

    assert resultado.botellas_legado_migradas == 1
    assert resultado.cromo_reasignadas == 1
    model_mocks = session.model_mocks
    model_mocks[Camara].filter.return_value.update.assert_called_once_with(
        {Camara.camara_padre_id: padre.id}, synchronize_session=False
    )
    model_mocks[CromoBotella].filter.return_value.update.assert_called_once_with(
        {CromoBotella.camara_id: padre.id}, synchronize_session=False
    )


@patch("core.services.botella_merge_service.aplicar_estado_a_grupo")
@patch("core.services.botella_merge_service.miembros_del_grupo")
def test_apropiar_elimina_fisicamente_la_legado(mock_grupo, mock_aplicar) -> None:
    legado = Camara(id=1, nombre="Bot 2", camara_padre_id=10, estado=CamaraEstado.LIBRE)
    cromo = CromoBotella(n_id=100, nombre="Botella 2", camara_id=10, estado=CamaraEstado.LIBRE)
    padre = Camara(id=10, nombre="Cra Rivadavia 100 CF", estado=CamaraEstado.LIBRE)
    legado.aliases = []
    mock_grupo.return_value = [padre]

    session = _build_session(legado, cromo, padre)
    apropiar_legado_a_cromo(session, legado_id=1, cromo_n_id=100, usuario="admin")

    session.delete.assert_any_call(legado)


@patch("core.services.botella_merge_service.aplicar_estado_a_grupo")
@patch("core.services.botella_merge_service.miembros_del_grupo")
def test_apropiar_registra_evento_de_auditoria_siempre(mock_grupo, mock_aplicar) -> None:
    legado = Camara(id=1, nombre="Bot 2", camara_padre_id=10, estado=CamaraEstado.LIBRE)
    cromo = CromoBotella(n_id=100, nombre="Botella 2", camara_id=10, estado=CamaraEstado.LIBRE)
    padre = Camara(id=10, nombre="Cra Rivadavia 100 CF", estado=CamaraEstado.LIBRE)
    legado.aliases = []
    mock_grupo.return_value = [padre]

    session = _build_session(legado, cromo, padre)
    apropiar_legado_a_cromo(session, legado_id=1, cromo_n_id=100, usuario="admin")

    mock_aplicar.assert_not_called()  # mismo estado, no dispara cascada
    evento = next(
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], CamaraEstadoAuditoria)
    )
    assert evento.camara_id == 10
    assert "Bot 2" in evento.motivo
    assert "apropiada" in evento.motivo
    assert evento.usuario == "admin"


@patch("core.services.botella_merge_service.aplicar_estado_a_grupo")
@patch("core.services.botella_merge_service.miembros_del_grupo")
def test_apropiar_propaga_estado_mas_restrictivo(mock_grupo, mock_aplicar) -> None:
    legado = Camara(id=1, nombre="Bot 2", camara_padre_id=10, estado=CamaraEstado.BANEADA)
    cromo = CromoBotella(n_id=100, nombre="Botella 2", camara_id=10, estado=CamaraEstado.LIBRE)
    padre = Camara(id=10, nombre="Cra Rivadavia 100 CF", estado=CamaraEstado.LIBRE)
    legado.aliases = []
    mock_grupo.return_value = [padre]  # el grupo del padre no incluye a la legado (no es self-FK)

    session = _build_session(legado, cromo, padre)
    resultado = apropiar_legado_a_cromo(session, legado_id=1, cromo_n_id=100, usuario="admin")

    assert resultado.estado_final == "BANEADA"
    mock_aplicar.assert_called_once()
    args, kwargs = mock_aplicar.call_args
    assert args[1] is padre
    assert args[2] == CamaraEstado.BANEADA
    assert kwargs["usuario"] == "admin"


@patch("core.services.botella_merge_service.aplicar_estado_a_grupo")
@patch("core.services.botella_merge_service.miembros_del_grupo")
def test_apropiar_no_crea_alias_automatico_con_nombre_de_legado(mock_grupo, mock_aplicar) -> None:
    """A diferencia de unificar_camaras (fusión de Cámaras), acá no se pidió crear un alias con el
    nombre propio de la legado eliminada — sólo se migran los alias que ya tenía."""
    legado = Camara(id=1, nombre="Bot 2", camara_padre_id=10, estado=CamaraEstado.LIBRE)
    cromo = CromoBotella(n_id=100, nombre="Botella 2", camara_id=10, estado=CamaraEstado.LIBRE)
    padre = Camara(id=10, nombre="Cra Rivadavia 100 CF", estado=CamaraEstado.LIBRE)
    legado.aliases = []
    mock_grupo.return_value = [padre]

    session = _build_session(legado, cromo, padre)
    apropiar_legado_a_cromo(session, legado_id=1, cromo_n_id=100, usuario="admin")

    assert not any(isinstance(call.args[0], CamaraAlias) for call in session.add.call_args_list)


@patch("core.services.botella_merge_service.aplicar_estado_a_grupo")
@patch("core.services.botella_merge_service.miembros_del_grupo")
def test_apropiar_migra_alias_existentes_de_la_legado_sin_duplicar(mock_grupo, mock_aplicar) -> None:
    legado = Camara(id=1, nombre="Bot 2", camara_padre_id=10, estado=CamaraEstado.LIBRE)
    cromo = CromoBotella(n_id=100, nombre="Botella 2", camara_id=10, estado=CamaraEstado.LIBRE)
    padre = Camara(id=10, nombre="Cra Rivadavia 100 CF", estado=CamaraEstado.LIBRE)
    alias_unico = CamaraAlias(id=50, camara_id=1, alias_nombre="Bot 2 Vieja Nomenclatura")
    alias_duplicado = CamaraAlias(id=51, camara_id=1, alias_nombre="Alias Ya Existente")
    legado.aliases = [alias_unico, alias_duplicado]
    mock_grupo.return_value = [padre]

    session = _build_session(legado, cromo, padre, aliases_existentes_padre=["Alias Ya Existente"])
    resultado = apropiar_legado_a_cromo(session, legado_id=1, cromo_n_id=100, usuario="admin")

    assert alias_unico.camara_id == 10
    assert resultado.aliases_migrados == 1
    session.delete.assert_any_call(alias_duplicado)
