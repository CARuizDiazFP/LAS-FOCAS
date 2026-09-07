# Nombre de archivo: test_camara_ingest_service.py
# Ubicación de archivo: tests/test_camara_ingest_service.py
# Descripción: Pruebas de la ingesta masiva de cámaras desde Excel — matcher extendido, sin creación, sin-match, asociación manual

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.services.camara_estado_service import ActualizacionEstadoResultado
from core.services.camara_ingest_service import (
    ORIGEN_EXCEL_CAMARAS,
    NombreSinMatch,
    _procesar_ingesta_camaras_en_sesion,
    asociar_nombres_a_camara,
)
from core.services.cromo.camara_botella_busqueda import ResultadoBusquedaExtendida
from db.models.infra import Camara, CamaraAlias, CamaraEstado, IngresoSinMatch
from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError


def _session_sin_match(existing: IngresoSinMatch | None) -> MagicMock:
    """Sesión mock para `_procesar_ingesta_camaras_en_sesion` cuando el único query esperado es la
    búsqueda de idempotencia de `_registrar_sin_match` (`IngresoSinMatch.filter(...).first()`)."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = existing

    ids = iter(range(900, 999))

    def add_side_effect(obj):
        if isinstance(obj, IngresoSinMatch) and obj.id is None:
            obj.id = next(ids)

    session.add.side_effect = add_side_effect
    return session


def _session_asociacion(camara, casos, alias_lookup_results) -> MagicMock:
    """Sesión mock para `asociar_nombres_a_camara`: enruta `session.query(Model)` según el modelo
    consultado. `alias_lookup_results` se consume en orden, un elemento por `IngresoSinMatch`
    procesado en el loop (cada iteración hace su propio `session.query(CamaraAlias)`)."""
    session = MagicMock()
    alias_iter = iter(alias_lookup_results)

    def query_side_effect(model):
        mock_q = MagicMock()
        if model is Camara:
            mock_q.filter.return_value.first.return_value = camara
        elif model is IngresoSinMatch:
            mock_q.filter.return_value.all.return_value = casos
        elif model is CamaraAlias:
            mock_q.filter.return_value.first.side_effect = lambda: next(alias_iter)
        return mock_q

    session.query.side_effect = query_side_effect
    return session


# =============================================================================
# _procesar_ingesta_camaras_en_sesion
# =============================================================================


@patch("core.services.cromo.camara_botella_busqueda.buscar_camara_o_botella_cromo")
def test_alias_sin_match_no_crea_camara_y_registra_ingreso_sin_match(mock_buscar) -> None:
    mock_buscar.return_value = ResultadoBusquedaExtendida(
        camara=None, nombre_norm="cra rara 123", fuente=None, botella=None
    )
    session = _session_sin_match(existing=None)

    resultado = _procesar_ingesta_camaras_en_sesion(session, ["Cra Rara 123"], "motivo test", "admin")

    assert len(resultado.sin_match) == 1
    assert resultado.sin_match[0].nombre == "Cra Rara 123"
    assert resultado.errores == []

    # Guard explícito: la creación de Camara está eliminada del flujo — ni una sola instancia debe
    # llegar a session.add(), ni siquiera dentro del camino "sin match".
    added = [call.args[0] for call in session.add.call_args_list]
    assert not any(isinstance(obj, Camara) for obj in added)
    assert sum(isinstance(obj, IngresoSinMatch) for obj in added) == 1


@patch("core.services.cromo.camara_botella_busqueda.buscar_camara_o_botella_cromo")
def test_alias_sin_match_repetido_reusa_caso_existente_sin_duplicar(mock_buscar) -> None:
    mock_buscar.return_value = ResultadoBusquedaExtendida(
        camara=None, nombre_norm="cra rara 123", fuente=None, botella=None
    )
    existente = IngresoSinMatch(
        id=555, texto_original="Cra Rara 123", origen=ORIGEN_EXCEL_CAMARAS, revisado=False
    )
    session = _session_sin_match(existing=existente)

    resultado = _procesar_ingesta_camaras_en_sesion(session, ["Cra Rara 123"], "motivo test", "admin")

    assert resultado.sin_match == [NombreSinMatch(caso_id=555, nombre="Cra Rara 123")]
    added_ingresos = [call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], IngresoSinMatch)]
    assert added_ingresos == []  # no duplica fila


@patch("core.services.camara_ingest_service.override_camara_estado_manual")
@patch("core.services.cromo.camara_botella_busqueda.buscar_camara_o_botella_cromo")
def test_alias_matchea_banea_grupo_nuevo(mock_buscar, mock_ban) -> None:
    camara = Camara(id=10, nombre="Cra Test CF", camara_padre_id=None)
    mock_buscar.return_value = ResultadoBusquedaExtendida(
        camara=camara, nombre_norm="cra test", fuente="camara", botella=None
    )
    mock_ban.return_value = ActualizacionEstadoResultado(success=True, camara_id=10, changed=True)
    session = MagicMock()

    resultado = _procesar_ingesta_camaras_en_sesion(session, ["Cra Test"], "motivo test", "admin")

    assert resultado.grupos_baneados == 1
    assert resultado.grupos_ya_baneados == 0
    assert resultado.sin_match == []
    assert resultado.errores == []
    mock_ban.assert_called_once_with(
        session, 10, CamaraEstado.BANEADA, usuario="admin", motivo="motivo test"
    )


@patch("core.services.camara_ingest_service.override_camara_estado_manual")
@patch("core.services.cromo.camara_botella_busqueda.buscar_camara_o_botella_cromo")
def test_ambiguous_search_error_se_trata_como_sin_match(mock_buscar, mock_ban) -> None:
    mock_buscar.side_effect = AmbiguousSearchError("Cra Test", 2, ["Cra Test 1", "Cra Test 2"])
    session = _session_sin_match(existing=None)

    resultado = _procesar_ingesta_camaras_en_sesion(session, ["Cra Test"], "motivo test", "admin")

    assert len(resultado.sin_match) == 1
    assert resultado.errores == []
    mock_ban.assert_not_called()


@patch("core.services.camara_ingest_service.override_camara_estado_manual")
@patch("core.services.cromo.camara_botella_busqueda.buscar_camara_o_botella_cromo")
def test_dos_alias_del_mismo_grupo_no_duplican_el_conteo(mock_buscar, mock_ban) -> None:
    raiz_id = 5
    bot2 = Camara(id=10, nombre="Cra Test Bot 2 CF", camara_padre_id=raiz_id)
    bot3 = Camara(id=11, nombre="Cra Test Bot 3 CF", camara_padre_id=raiz_id)
    mock_buscar.side_effect = [
        ResultadoBusquedaExtendida(camara=bot2, nombre_norm="x1", fuente="camara", botella=None),
        ResultadoBusquedaExtendida(camara=bot3, nombre_norm="x2", fuente="camara", botella=None),
    ]
    mock_ban.return_value = ActualizacionEstadoResultado(success=True, camara_id=10, changed=True)
    session = MagicMock()

    resultado = _procesar_ingesta_camaras_en_sesion(
        session, ["Bot 2 Cra Test", "Bot 3 Cra Test"], "motivo test", "admin"
    )

    assert resultado.grupos_baneados == 1  # no 2: mismo raiz_id en ambas llamadas
    assert mock_ban.call_count == 2  # cada botella se banea individualmente igual


@patch("core.services.camara_ingest_service.override_camara_estado_manual")
@patch("core.services.cromo.camara_botella_busqueda.buscar_camara_o_botella_cromo")
def test_alias_matchea_grupo_ya_baneado(mock_buscar, mock_ban) -> None:
    camara = Camara(id=10, nombre="Cra Test CF", camara_padre_id=None)
    mock_buscar.return_value = ResultadoBusquedaExtendida(
        camara=camara, nombre_norm="cra test", fuente="camara", botella=None
    )
    mock_ban.return_value = ActualizacionEstadoResultado(success=True, camara_id=10, changed=False)
    session = MagicMock()

    resultado = _procesar_ingesta_camaras_en_sesion(session, ["Cra Test"], "motivo test", "admin")

    assert resultado.grupos_ya_baneados == 1
    assert resultado.grupos_baneados == 0


@patch("core.services.camara_ingest_service.override_camara_estado_manual")
@patch("core.services.cromo.camara_botella_busqueda.buscar_camara_o_botella_cromo")
def test_excepcion_inesperada_en_un_alias_no_detiene_el_lote(mock_buscar, mock_ban) -> None:
    camara_ok = Camara(id=20, nombre="Cra OK CF", camara_padre_id=None)
    mock_buscar.side_effect = [
        RuntimeError("boom"),
        ResultadoBusquedaExtendida(camara=camara_ok, nombre_norm="ok", fuente="camara", botella=None),
    ]
    mock_ban.return_value = ActualizacionEstadoResultado(success=True, camara_id=20, changed=True)
    session = MagicMock()

    resultado = _procesar_ingesta_camaras_en_sesion(
        session, ["Cra Rota", "Cra OK"], "motivo test", "admin"
    )

    assert len(resultado.errores) == 1
    assert "Cra Rota" in resultado.errores[0]
    assert "boom" in resultado.errores[0]
    assert resultado.grupos_baneados == 1  # el resto del lote sigue procesándose


# =============================================================================
# asociar_nombres_a_camara
# =============================================================================


def test_asociar_nombres_a_camara_no_encontrada() -> None:
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None

    with patch("core.services.camara_ingest_service.override_camara_estado_manual") as mock_ban:
        resultado = asociar_nombres_a_camara(
            session, caso_ids=[1], camara_id=999, motivo="m", usuario="admin"
        )

    assert resultado.ok is False
    assert resultado.error == "Cámara no encontrada"
    mock_ban.assert_not_called()


def test_asociar_nombres_a_camara_crea_alias_marca_revisado_banea_una_sola_vez() -> None:
    camara = Camara(id=7, nombre="Cra Test CF", estado=CamaraEstado.LIBRE)
    caso1 = IngresoSinMatch(id=101, texto_original="Alias Uno", origen=ORIGEN_EXCEL_CAMARAS, revisado=False)
    caso2 = IngresoSinMatch(id=102, texto_original="Alias Dos", origen=ORIGEN_EXCEL_CAMARAS, revisado=False)
    session = _session_asociacion(camara, [caso1, caso2], alias_lookup_results=[None, None])

    ban_result = ActualizacionEstadoResultado(success=True, camara_id=7, changed=True)
    with patch(
        "core.services.camara_ingest_service.override_camara_estado_manual", return_value=ban_result
    ) as mock_ban:
        resultado = asociar_nombres_a_camara(
            session, caso_ids=[101, 102], camara_id=7, motivo="m", usuario="admin"
        )

    assert resultado.ok is True
    assert resultado.alias_creados == 2
    assert resultado.alias_preexistentes == 0
    assert resultado.casos_marcados == 2
    assert caso1.revisado is True
    assert caso2.revisado is True
    assert resultado.baneo_aplicado is True
    mock_ban.assert_called_once()

    alias_creados = [call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], CamaraAlias)]
    assert {a.alias_nombre for a in alias_creados} == {"Alias Uno", "Alias Dos"}
    assert all(a.camara_id == 7 for a in alias_creados)


def test_asociar_nombres_a_camara_idempotente_alias_ya_apunta_a_la_misma_camara() -> None:
    camara = Camara(id=7, nombre="Cra Test CF", estado=CamaraEstado.LIBRE)
    caso = IngresoSinMatch(id=101, texto_original="Alias Uno", origen=ORIGEN_EXCEL_CAMARAS, revisado=False)
    alias_existente = CamaraAlias(id=5, camara_id=7, alias_nombre="Alias Uno")
    session = _session_asociacion(camara, [caso], alias_lookup_results=[alias_existente])

    ban_result = ActualizacionEstadoResultado(success=True, camara_id=7, changed=False)
    with patch("core.services.camara_ingest_service.override_camara_estado_manual", return_value=ban_result):
        resultado = asociar_nombres_a_camara(
            session, caso_ids=[101], camara_id=7, motivo="m", usuario="admin"
        )

    assert resultado.alias_preexistentes == 1
    assert resultado.alias_creados == 0
    assert resultado.casos_marcados == 1
    assert caso.revisado is True
    assert resultado.conflictos == []

    alias_creados = [call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], CamaraAlias)]
    assert alias_creados == []  # no se crea un CamaraAlias nuevo, se reusa el existente


def test_asociar_nombres_a_camara_conflicto_alias_apunta_a_otra_camara() -> None:
    camara = Camara(id=7, nombre="Cra Test CF", estado=CamaraEstado.LIBRE)
    otra_camara = Camara(id=99, nombre="Cra Otra CF")
    caso = IngresoSinMatch(id=101, texto_original="Alias Uno", origen=ORIGEN_EXCEL_CAMARAS, revisado=False)
    alias_existente = CamaraAlias(id=5, camara_id=99, alias_nombre="Alias Uno")
    alias_existente.camara = otra_camara
    session = _session_asociacion(camara, [caso], alias_lookup_results=[alias_existente])

    ban_result = ActualizacionEstadoResultado(success=True, camara_id=7, changed=True)
    with patch("core.services.camara_ingest_service.override_camara_estado_manual", return_value=ban_result):
        resultado = asociar_nombres_a_camara(
            session, caso_ids=[101], camara_id=7, motivo="m", usuario="admin"
        )

    assert len(resultado.conflictos) == 1
    conflicto = resultado.conflictos[0]
    assert conflicto.caso_id == 101
    assert conflicto.nombre == "Alias Uno"
    assert conflicto.camara_actual_id == 99
    assert conflicto.camara_actual_nombre == "Cra Otra CF"
    assert caso.revisado is False  # no se marca revisado ante conflicto
    assert resultado.casos_marcados == 0
