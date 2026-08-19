# Nombre de archivo: test_cromo_consolidacion_service.py
# Ubicación de archivo: tests/test_cromo_consolidacion_service.py
# Descripción: Pruebas de la consolidación manual de un grupo libre de Botellas Cromo duplicadas (+ opcionalmente legado)

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.services.botella_merge_service import ApropiacionBotellaError, ResultadoApropiacionBotella
from core.services.cromo.consolidacion_service import (
    ConsolidacionBotellaError,
    consolidar_grupo_botellas,
)
from db.models.cromo import CromoBotella, CromoBotellaAlias


def _build_session(
    *,
    destino: CromoBotella | None,
    destino_ya_marcado: CromoBotellaAlias | None = None,
    existentes_en_orden: list[CromoBotellaAlias | None] | None = None,
    dependientes: list[CromoBotellaAlias] | None = None,
) -> MagicMock:
    session = MagicMock()
    model_mocks: dict[object, MagicMock] = {}

    def mock_para(modelo: object) -> MagicMock:
        if modelo not in model_mocks:
            model_mocks[modelo] = MagicMock()
        return model_mocks[modelo]

    mock_para(CromoBotella).filter.return_value.first.return_value = destino
    # Orden real de llamadas del servicio: primero el chequeo "destino ya marcado", luego una por
    # cada origen (en el mismo orden que la lista de-dup que se le pasa).
    mock_para(CromoBotellaAlias).filter.return_value.first.side_effect = [destino_ya_marcado] + list(
        existentes_en_orden or []
    )
    mock_para(CromoBotellaAlias).filter.return_value.all.return_value = dependientes or []

    session.query.side_effect = lambda modelo, *a: mock_para(modelo)
    session.model_mocks = model_mocks
    return session


def test_consolidar_falla_si_no_hay_nada_para_hacer():
    session = MagicMock()
    with pytest.raises(ConsolidacionBotellaError, match="Nada para consolidar"):
        consolidar_grupo_botellas(session, ids_origen_cromo=[], id_destino_cromo=999, usuario="admin")


def test_consolidar_falla_si_destino_esta_en_los_origenes():
    session = MagicMock()
    with pytest.raises(ConsolidacionBotellaError, match="no puede ser también uno de los orígenes"):
        consolidar_grupo_botellas(session, ids_origen_cromo=[100, 999], id_destino_cromo=999, usuario="admin")


def test_consolidar_falla_si_destino_no_existe():
    session = _build_session(destino=None)
    with pytest.raises(ConsolidacionBotellaError, match="No existe una Botella Cromo"):
        consolidar_grupo_botellas(session, ids_origen_cromo=[100], id_destino_cromo=999, usuario="admin")


def test_consolidar_falla_si_destino_ya_esta_marcado_como_basura():
    destino = CromoBotella(n_id=999, nombre="Golden")
    marcado_previo = CromoBotellaAlias(id_cromo_origen=999, id_cromo_destino=1, accion="fusionar")
    session = _build_session(destino=destino, destino_ya_marcado=marcado_previo)

    with pytest.raises(ConsolidacionBotellaError, match="ya está marcado"):
        consolidar_grupo_botellas(session, ids_origen_cromo=[100], id_destino_cromo=999, usuario="admin")


def test_consolidar_crea_alias_nuevos_para_cada_origen():
    destino = CromoBotella(n_id=999, nombre="Golden")
    session = _build_session(destino=destino, existentes_en_orden=[None, None])

    resultado = consolidar_grupo_botellas(
        session, ids_origen_cromo=[100, 200], id_destino_cromo=999, usuario="admin"
    )

    assert resultado.alias_creados == 2
    assert resultado.alias_actualizados == 0
    assert resultado.alias_repuntados == []
    creados = [c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], CromoBotellaAlias)]
    assert {a.id_cromo_origen for a in creados} == {100, 200}
    assert all(a.id_cromo_destino == 999 and a.accion == "fusionar" for a in creados)
    assert all(a.creado_por == "admin" for a in creados)


def test_consolidar_repuntea_origen_ya_aliaseado_a_otro_destino_y_lo_reporta():
    destino = CromoBotella(n_id=999, nombre="Golden")
    alias_existente = CromoBotellaAlias(id_cromo_origen=100, id_cromo_destino=555, accion="fusionar")
    session = _build_session(destino=destino, existentes_en_orden=[alias_existente])

    resultado = consolidar_grupo_botellas(
        session, ids_origen_cromo=[100], id_destino_cromo=999, usuario="admin"
    )

    assert resultado.alias_creados == 0
    assert resultado.alias_actualizados == 1
    assert resultado.alias_repuntados == [{"origen": 100, "destino_anterior": 555, "destino_nuevo": 999}]
    assert alias_existente.id_cromo_destino == 999


def test_consolidar_recablea_alias_dependientes_para_no_dejar_cadena_rota():
    """A(100) -> B(200) ya existía (accion fusionar). Ahora se consolida [200] -> 999: la fila A->200
    debe recablearse directo a 999, o quedaría apuntando a un origen que dejó de ser destino real."""
    destino = CromoBotella(n_id=999, nombre="Golden")
    dependiente = CromoBotellaAlias(id_cromo_origen=100, id_cromo_destino=200, accion="fusionar")
    session = _build_session(destino=destino, existentes_en_orden=[None], dependientes=[dependiente])

    resultado = consolidar_grupo_botellas(
        session, ids_origen_cromo=[200], id_destino_cromo=999, usuario="admin"
    )

    assert resultado.alias_dependientes_recableados == 1
    assert dependiente.id_cromo_destino == 999


@patch("core.services.cromo.consolidacion_service.apropiar_legado_a_cromo")
def test_consolidar_migra_legado_y_agrega_sus_contadores(mock_apropiar):
    destino = CromoBotella(n_id=999, nombre="Golden")
    mock_apropiar.return_value = ResultadoApropiacionBotella(
        legado_id=1, legado_nombre="Bot 2", cromo_n_id=999, cromo_nombre="Golden",
        camara_padre_id=10, camara_padre_nombre="Padre", botellas_legado_migradas=0,
        cromo_reasignadas=0, cables_migrados=2, empalmes_migrados=1, ingresos_migrados=0,
        aliases_migrados=3, estado_final="LIBRE",
    )
    session = _build_session(destino=destino)

    resultado = consolidar_grupo_botellas(
        session, ids_origen_cromo=[], id_destino_cromo=999, ids_legado=[1], usuario="admin"
    )

    mock_apropiar.assert_called_once_with(session, legado_id=1, cromo_n_id=999, usuario="admin")
    assert resultado.legados_migrados == [1]
    assert resultado.cables_migrados == 2
    assert resultado.empalmes_migrados == 1
    assert resultado.camara_aliases_migrados == 3


@patch("core.services.cromo.consolidacion_service.apropiar_legado_a_cromo")
def test_consolidar_aborta_todo_si_un_legado_falla_por_padre_distinto(mock_apropiar):
    destino = CromoBotella(n_id=999, nombre="Golden")
    mock_apropiar.side_effect = ApropiacionBotellaError(
        "La Botella Cromo no pertenece a la misma Cámara padre que la Botella legado"
    )
    session = _build_session(destino=destino)

    with pytest.raises(ApropiacionBotellaError, match="misma Cámara padre"):
        consolidar_grupo_botellas(
            session, ids_origen_cromo=[], id_destino_cromo=999, ids_legado=[1], usuario="admin"
        )


def test_consolidar_ignora_nombre_en_blanco():
    # Nombre en blanco no cuenta como "algo para hacer" por sí solo, pero acompañado de un origen
    # real sí pasa la guarda de no-op — lo que se está probando acá es que el nombre en blanco
    # específicamente se ignora (no se pisa el nombre existente con espacios).
    destino = CromoBotella(n_id=999, nombre="Nombre Original")
    session = _build_session(destino=destino, existentes_en_orden=[None])

    resultado = consolidar_grupo_botellas(
        session, ids_origen_cromo=[100], id_destino_cromo=999, nombre_destino="   ", usuario="admin"
    )

    assert resultado.nombre_nuevo is None
    assert destino.nombre == "Nombre Original"


def test_consolidar_actualiza_nombre_destino_si_viene_no_vacio():
    destino = CromoBotella(n_id=999, nombre=None)
    session = _build_session(destino=destino)

    resultado = consolidar_grupo_botellas(
        session, ids_origen_cromo=[], id_destino_cromo=999, nombre_destino="  Nombre Nuevo  ", usuario="admin"
    )

    assert destino.nombre == "Nombre Nuevo"
    assert resultado.nombre_anterior is None
    assert resultado.nombre_nuevo == "Nombre Nuevo"


def test_consolidar_dedup_origenes_repetidos_no_duplica_alias():
    destino = CromoBotella(n_id=999, nombre="Golden")
    session = _build_session(destino=destino, existentes_en_orden=[None])

    resultado = consolidar_grupo_botellas(
        session, ids_origen_cromo=[100, 100], id_destino_cromo=999, usuario="admin"
    )

    assert resultado.alias_creados == 1
