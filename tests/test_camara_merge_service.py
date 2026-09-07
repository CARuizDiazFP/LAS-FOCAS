# Nombre de archivo: test_camara_merge_service.py
# Ubicación de archivo: tests/test_camara_merge_service.py
# Descripción: Pruebas de la fusión Cámara-a-Cámara — migración de entidades heredables, alias, auditoría y borrado físico de la secundaria

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.services.camara_merge_service import (
    MergeCamarasError,
    ResultadoMergeCamaras,
    fusionar_grupo_camaras,
    unificar_camaras,
)
from db.models.infra import (
    Cable,
    Camara,
    CamaraAlias,
    CamaraEstado,
    CamaraEstadoAuditoria,
    Empalme,
    Ingreso,
)
from db.models.cromo import CromoBotella


def _build_session(
    principal: Camara,
    secundaria: Camara,
    *,
    cromo_migradas: int = 0,
    cables_migrados: tuple[int, int] = (0, 0),
    empalmes_migrados: int = 0,
    ingresos_migrados: int = 0,
    aliases_existentes_principal: list[str] | None = None,
) -> MagicMock:
    """Sesión mock que dispatchea `.query(Modelo)` a un sub-mock propio por modelo — el servicio
    ahora hace UPDATE masivo sobre 6 modelos distintos (antes sólo Camara/CromoBotella), así que la
    cadena genérica `.query().filter().first().side_effect=[...]` del test original ya no alcanza."""
    session = MagicMock()
    model_mocks: dict[object, MagicMock] = {}

    def mock_para(modelo: object) -> MagicMock:
        if modelo not in model_mocks:
            model_mocks[modelo] = MagicMock()
        return model_mocks[modelo]

    mock_para(Camara).filter.return_value.first.side_effect = [principal, secundaria]
    mock_para(CromoBotella).filter.return_value.update.return_value = cromo_migradas
    mock_para(Cable).filter.return_value.update.side_effect = list(cables_migrados)
    mock_para(Empalme).filter.return_value.update.return_value = empalmes_migrados
    mock_para(Ingreso).filter.return_value.update.return_value = ingresos_migrados
    mock_para(CamaraEstadoAuditoria).filter.return_value.update.return_value = 0

    alias_col_mock = MagicMock()
    alias_col_mock.filter.return_value.all.return_value = [
        (nombre,) for nombre in (aliases_existentes_principal or [])
    ]

    def query_side_effect(target: object, *_args: object) -> MagicMock:
        if target is CamaraAlias.alias_nombre:
            return alias_col_mock
        return mock_para(target)

    session.query.side_effect = query_side_effect
    session.model_mocks = model_mocks
    return session


def test_unificar_camaras_falla_si_son_la_misma() -> None:
    session = MagicMock()
    with pytest.raises(MergeCamarasError, match="no pueden ser la misma"):
        unificar_camaras(session, principal_id=1, secundaria_id=1, usuario="test")
    session.query.assert_not_called()


def test_unificar_camaras_falla_si_principal_no_existe() -> None:
    camara_mock = MagicMock()
    camara_mock.filter.return_value.first.side_effect = [None]
    session = MagicMock()
    session.query.side_effect = lambda modelo, *a: camara_mock
    with pytest.raises(MergeCamarasError, match="principal no encontrada"):
        unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="test")


def test_unificar_camaras_falla_si_secundaria_no_existe() -> None:
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    camara_mock = MagicMock()
    camara_mock.filter.return_value.first.side_effect = [principal, None]
    session = MagicMock()
    session.query.side_effect = lambda modelo, *a: camara_mock
    with pytest.raises(MergeCamarasError, match="secundaria no encontrada"):
        unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="test")


@pytest.mark.parametrize("principal_padre,secundaria_padre", [(5, None), (None, 5)])
def test_unificar_camaras_falla_si_alguna_ya_es_botella(principal_padre, secundaria_padre) -> None:
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE, camara_padre_id=principal_padre)
    secundaria = Camara(id=2, nombre="Cra Secundaria CF", estado=CamaraEstado.LIBRE, camara_padre_id=secundaria_padre)
    camara_mock = MagicMock()
    camara_mock.filter.return_value.first.side_effect = [principal, secundaria]
    session = MagicMock()
    session.query.side_effect = lambda modelo, *a: camara_mock
    with pytest.raises(MergeCamarasError, match="Cámaras raíz"):
        unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="test")


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_migra_botellas_legado_propias(mock_grupo, mock_aplicar) -> None:
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="Cra Secundaria CF", estado=CamaraEstado.LIBRE)
    botella_de_secundaria = Camara(id=3, nombre="Cra Secundaria CF Bot 2", estado=CamaraEstado.LIBRE, camara_padre_id=2)
    secundaria.botellas = [botella_de_secundaria]
    secundaria.aliases = []
    mock_grupo.return_value = [principal]

    session = _build_session(principal, secundaria)
    resultado = unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin")

    assert botella_de_secundaria.camara_padre_id == 1
    assert resultado.botellas_legado_migradas == 1
    mock_aplicar.assert_not_called()


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_migra_botellas_cromo(mock_grupo, mock_aplicar) -> None:
    principal = Camara(id=10, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=20, nombre="Cra Secundaria CF", estado=CamaraEstado.LIBRE)
    secundaria.botellas = []
    secundaria.aliases = []
    mock_grupo.return_value = [principal]

    session = _build_session(principal, secundaria, cromo_migradas=4)
    resultado = unificar_camaras(session, principal_id=10, secundaria_id=20, usuario="admin")

    assert resultado.botellas_cromo_migradas == 4


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_reasigna_cables_empalmes_ingresos_y_auditoria_antes_de_eliminar(mock_grupo, mock_aplicar) -> None:
    """Estas 4 reasignaciones son las críticas: sin ellas, `session.delete(secundaria)` dispararía
    cascadas destructivas reales (ON DELETE CASCADE de auditoría, cascade="all, delete-orphan" de
    Empalme/Ingreso) o dejaría Cables huérfanos (ondelete=SET NULL)."""
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="Cra Secundaria CF", estado=CamaraEstado.LIBRE)
    secundaria.botellas = []
    secundaria.aliases = []
    mock_grupo.return_value = [principal]

    session = _build_session(
        principal,
        secundaria,
        cables_migrados=(2, 1),
        empalmes_migrados=5,
        ingresos_migrados=3,
    )
    resultado = unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin")

    assert resultado.cables_migrados == 3  # 2 con origen en la secundaria + 1 con destino en ella
    assert resultado.empalmes_migrados == 5
    assert resultado.ingresos_migrados == 3

    model_mocks = session.model_mocks
    model_mocks[Empalme].filter.return_value.update.assert_called_once_with(
        {Empalme.camara_id: principal.id}, synchronize_session=False
    )
    model_mocks[Ingreso].filter.return_value.update.assert_called_once_with(
        {Ingreso.camara_id: principal.id}, synchronize_session=False
    )
    model_mocks[CamaraEstadoAuditoria].filter.return_value.update.assert_called_once_with(
        {CamaraEstadoAuditoria.camara_id: principal.id}, synchronize_session=False
    )
    # Verifica orden: la reasignación de auditoría debe ocurrir ANTES del delete físico.
    reasigna_auditoria = model_mocks[CamaraEstadoAuditoria].filter.return_value.update.call_args
    assert reasigna_auditoria is not None
    session.delete.assert_any_call(secundaria)


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_migra_alias_existentes_de_la_secundaria_sin_duplicar(mock_grupo, mock_aplicar) -> None:
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="Cra Secundaria CF", estado=CamaraEstado.LIBRE)
    secundaria.botellas = []
    alias_unico = CamaraAlias(id=10, camara_id=2, alias_nombre="Cra Vieja Nomenclatura")
    alias_duplicado = CamaraAlias(id=11, camara_id=2, alias_nombre="Alias Ya Existente")
    secundaria.aliases = [alias_unico, alias_duplicado]
    mock_grupo.return_value = [principal]

    session = _build_session(principal, secundaria, aliases_existentes_principal=["Alias Ya Existente"])
    resultado = unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin", guardar_alias=False)

    assert alias_unico.camara_id == 1
    assert resultado.aliases_migrados == 1
    session.delete.assert_any_call(alias_duplicado)


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_crea_alias_con_nombre_de_secundaria_por_defecto(mock_grupo, mock_aplicar) -> None:
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="Cra Secundaria Distinta CF", estado=CamaraEstado.LIBRE)
    secundaria.botellas = []
    secundaria.aliases = []
    mock_grupo.return_value = [principal]

    session = _build_session(principal, secundaria)
    resultado = unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin")

    assert resultado.alias_creado is True
    alias_agregado = next(
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], CamaraAlias)
    )
    assert alias_agregado.camara_id == 1
    assert alias_agregado.alias_nombre == "Cra Secundaria Distinta CF"


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_no_crea_alias_si_guardar_alias_false(mock_grupo, mock_aplicar) -> None:
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="Cra Secundaria Distinta CF", estado=CamaraEstado.LIBRE)
    secundaria.botellas = []
    secundaria.aliases = []
    mock_grupo.return_value = [principal]

    session = _build_session(principal, secundaria)
    resultado = unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin", guardar_alias=False)

    assert resultado.alias_creado is False
    assert not any(isinstance(call.args[0], CamaraAlias) for call in session.add.call_args_list)


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_no_crea_alias_si_los_nombres_coinciden(mock_grupo, mock_aplicar) -> None:
    principal = Camara(id=1, nombre="Cra Igual CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="cra igual cf", estado=CamaraEstado.LIBRE)  # sólo difiere en case
    secundaria.botellas = []
    secundaria.aliases = []
    mock_grupo.return_value = [principal]

    session = _build_session(principal, secundaria)
    resultado = unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin")

    assert resultado.alias_creado is False
    assert not any(isinstance(call.args[0], CamaraAlias) for call in session.add.call_args_list)


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_considera_estado_de_secundaria_aunque_no_integre_el_grupo(mock_grupo, mock_aplicar) -> None:
    """La secundaria se elimina — a diferencia del diseño anterior, nunca pasa a integrar el
    self-FK de la principal — así que su estado debe plegarse a mano en el cálculo del estado más
    restrictivo, no vía `miembros_del_grupo` (que sólo conoce a la principal y sus propias Botellas)."""
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="Cra Secundaria CF", estado=CamaraEstado.BANEADA)
    secundaria.botellas = []
    secundaria.aliases = []
    mock_grupo.return_value = [principal]  # el grupo real de la principal nunca incluye a la secundaria

    session = _build_session(principal, secundaria)
    resultado = unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin")

    assert resultado.estado_final == "BANEADA"
    mock_aplicar.assert_called_once()
    args, kwargs = mock_aplicar.call_args
    assert args[1] is principal
    assert args[2] == CamaraEstado.BANEADA
    assert kwargs["usuario"] == "admin"


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_registra_evento_de_fusion_siempre(mock_grupo, mock_aplicar) -> None:
    """Aunque el estado no cambie (y por lo tanto `aplicar_estado_a_grupo` no se llame), debe quedar
    un registro explícito de la fusión en el historial de la principal."""
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="Cra Secundaria CF", estado=CamaraEstado.LIBRE)
    secundaria.botellas = []
    secundaria.aliases = []
    mock_grupo.return_value = [principal]

    session = _build_session(principal, secundaria)
    unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin")

    mock_aplicar.assert_not_called()
    evento = next(
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], CamaraEstadoAuditoria)
    )
    assert evento.camara_id == 1
    assert "Cra Secundaria CF" in evento.motivo
    assert "fusionada" in evento.motivo
    assert evento.usuario == "admin"


@patch("core.services.camara_merge_service.aplicar_estado_a_grupo")
@patch("core.services.camara_merge_service.miembros_del_grupo")
def test_unificar_camaras_elimina_fisicamente_la_secundaria(mock_grupo, mock_aplicar) -> None:
    principal = Camara(id=1, nombre="Cra Principal CF", estado=CamaraEstado.LIBRE)
    secundaria = Camara(id=2, nombre="Cra Secundaria CF", estado=CamaraEstado.LIBRE)
    secundaria.botellas = []
    secundaria.aliases = []
    mock_grupo.return_value = [principal]

    session = _build_session(principal, secundaria)
    unificar_camaras(session, principal_id=1, secundaria_id=2, usuario="admin")

    session.delete.assert_any_call(secundaria)


def test_fusionar_grupo_camaras_falla_si_lista_vacia() -> None:
    session = MagicMock()
    with pytest.raises(MergeCamarasError, match="al menos una"):
        fusionar_grupo_camaras(session, principal_id=1, secundaria_ids=[], usuario="admin")


def test_fusionar_grupo_camaras_falla_si_principal_esta_en_secundarias() -> None:
    session = MagicMock()
    with pytest.raises(MergeCamarasError, match="no puede estar"):
        fusionar_grupo_camaras(session, principal_id=1, secundaria_ids=[2, 1], usuario="admin")


def test_fusionar_grupo_camaras_falla_si_secundarias_repetidas() -> None:
    session = MagicMock()
    with pytest.raises(MergeCamarasError, match="repetidos"):
        fusionar_grupo_camaras(session, principal_id=1, secundaria_ids=[2, 2, 3], usuario="admin")


@patch("core.services.camara_merge_service.unificar_camaras")
def test_fusionar_grupo_camaras_llama_unificar_por_cada_secundaria_y_expira_entre_cada_una(mock_unificar) -> None:
    session = MagicMock()
    mock_unificar.side_effect = [
        ResultadoMergeCamaras(1, 2, "Sec2", 1, 0, 0, 0, 0, 0, False, "LIBRE"),
        ResultadoMergeCamaras(1, 3, "Sec3", 0, 2, 1, 0, 0, 1, True, "BANEADA"),
    ]

    resultado = fusionar_grupo_camaras(session, principal_id=1, secundaria_ids=[2, 3], usuario="admin")

    assert mock_unificar.call_count == 2
    assert session.expire_all.call_count == 2
    assert resultado.secundarias_fusionadas == [2, 3]
    assert resultado.secundarias_nombres == ["Sec2", "Sec3"]
    assert resultado.botellas_legado_migradas == 1
    assert resultado.botellas_cromo_migradas == 2
    assert resultado.cables_migrados == 1
    assert resultado.aliases_creados == 1
    assert resultado.estado_final == "BANEADA"  # el de la ÚLTIMA llamada
    assert len(resultado.resultados_individuales) == 2


@patch("core.services.camara_merge_service.unificar_camaras")
def test_fusionar_grupo_camaras_propaga_merge_error_de_una_secundaria(mock_unificar) -> None:
    session = MagicMock()
    mock_unificar.side_effect = MergeCamarasError("Cámara secundaria no encontrada")
    with pytest.raises(MergeCamarasError):
        fusionar_grupo_camaras(session, principal_id=1, secundaria_ids=[2], usuario="admin")
