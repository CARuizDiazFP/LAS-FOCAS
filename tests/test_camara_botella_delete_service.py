# Nombre de archivo: test_camara_botella_delete_service.py
# Ubicación de archivo: tests/test_camara_botella_delete_service.py
# Descripción: Pruebas de la eliminación permanente de Cámaras/Botellas vacías, bloqueo si tienen datos reales y registro automático de exclusión Cromo

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.services.camara_botella_delete_service import (
    EliminacionBloqueadaError,
    eliminar_botella,
    eliminar_camara,
    eliminar_y_excluir_grupo_cromo,
)
from db.models.cromo import CromoBotella, CromoBotellaAlias, CromoCable, CromoFusion
from db.models.infra import Cable, Camara, Empalme, Ingreso


def _mock_para(model_mocks: dict, modelo: object) -> MagicMock:
    if modelo not in model_mocks:
        model_mocks[modelo] = MagicMock()
    return model_mocks[modelo]


def _session_vacia() -> tuple[MagicMock, dict]:
    """Sesión donde CUALQUIER `.first()`/`.all()` sobre Cable/Empalme/Ingreso/CromoCable/
    CromoFusion/CromoBotellaAlias no encuentra nada — el estado "todo limpio" por defecto,
    los tests sólo sobreescriben lo que necesitan bloquear."""
    session = MagicMock()
    model_mocks: dict[object, MagicMock] = {}
    for modelo in (Cable, Empalme, Ingreso, CromoCable, CromoFusion, CromoBotellaAlias):
        _mock_para(model_mocks, modelo).filter.return_value.first.return_value = None
    # Default para eliminar_y_excluir_grupo_cromo (bulk delete) — 0 filas afectadas salvo que el
    # test lo sobreescriba.
    _mock_para(model_mocks, CromoCable).filter.return_value.delete.return_value = 0
    _mock_para(model_mocks, CromoFusion).filter.return_value.delete.return_value = 0
    # eliminar_camara SIEMPRE consulta ambas listas de hijos — default "sin hijos" salvo que el
    # test lo sobreescriba explícitamente.
    _mock_para(model_mocks, Camara).filter.return_value.all.return_value = []
    _mock_para(model_mocks, CromoBotella).filter.return_value.all.return_value = []
    session.query.side_effect = lambda modelo, *a: _mock_para(model_mocks, modelo)
    session.model_mocks = model_mocks
    return session, model_mocks


# ── eliminar_botella — origen='cromo' ─────────────────────────────────────────


def test_eliminar_botella_origen_invalido():
    session, _ = _session_vacia()
    with pytest.raises(EliminacionBloqueadaError, match="Origen inválido"):
        eliminar_botella(session, origen="rara", id=1, usuario="admin")


def test_eliminar_botella_cromo_no_existe():
    session, model_mocks = _session_vacia()
    _mock_para(model_mocks, CromoBotella).filter.return_value.first.return_value = None
    with pytest.raises(EliminacionBloqueadaError, match="No existe una Botella Cromo"):
        eliminar_botella(session, origen="cromo", id=999, usuario="admin")


def test_eliminar_botella_cromo_bloqueada_por_cable_cromo():
    session, model_mocks = _session_vacia()
    _mock_para(model_mocks, CromoBotella).filter.return_value.first.return_value = CromoBotella(n_id=100, camara_id=None)
    _mock_para(model_mocks, CromoCable).filter.return_value.first.return_value = CromoCable(n_id=51, extremo_a_n_id=100)

    with pytest.raises(EliminacionBloqueadaError) as excinfo:
        eliminar_botella(session, origen="cromo", id=100, usuario="admin")

    assert "cables Cromo" in excinfo.value.bloqueos[0].razon
    session.delete.assert_not_called()


def test_eliminar_botella_cromo_bloqueada_por_fusion():
    session, model_mocks = _session_vacia()
    _mock_para(model_mocks, CromoBotella).filter.return_value.first.return_value = CromoBotella(n_id=100, camara_id=None)
    _mock_para(model_mocks, CromoFusion).filter.return_value.first.return_value = CromoFusion(n_id=90, botella_n_id=100)

    with pytest.raises(EliminacionBloqueadaError) as excinfo:
        eliminar_botella(session, origen="cromo", id=100, usuario="admin")

    assert "fusiones" in excinfo.value.bloqueos[0].razon
    session.delete.assert_not_called()


def test_eliminar_botella_cromo_bloqueada_por_ser_destino_de_otro_alias():
    session, model_mocks = _session_vacia()
    _mock_para(model_mocks, CromoBotella).filter.return_value.first.return_value = CromoBotella(n_id=100, camara_id=None)
    _mock_para(model_mocks, CromoBotellaAlias).filter.return_value.first.return_value = CromoBotellaAlias(
        id_cromo_origen=50, id_cromo_destino=100, accion="fusionar"
    )

    with pytest.raises(EliminacionBloqueadaError) as excinfo:
        eliminar_botella(session, origen="cromo", id=100, usuario="admin")

    assert "destino de otra fila de alias" in excinfo.value.bloqueos[0].razon
    session.delete.assert_not_called()


def test_eliminar_botella_cromo_limpia_crea_alias_nuevo_sin_camara_padre():
    session, model_mocks = _session_vacia()
    cromo = CromoBotella(n_id=100, camara_id=None)
    _mock_para(model_mocks, CromoBotella).filter.return_value.first.return_value = cromo

    resultado = eliminar_botella(session, origen="cromo", id=100, usuario="admin")

    assert resultado.alias_registrado is True
    assert resultado.camara_padre_eliminada is None
    session.delete.assert_called_once_with(cromo)
    alias_creado = next(c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], CromoBotellaAlias))
    assert alias_creado.id_cromo_origen == 100
    assert alias_creado.accion == "ignorar"
    assert alias_creado.id_cromo_destino is None


def test_eliminar_botella_cromo_actualiza_alias_existente_in_place():
    session, model_mocks = _session_vacia()
    cromo = CromoBotella(n_id=100, camara_id=None)
    _mock_para(model_mocks, CromoBotella).filter.return_value.first.return_value = cromo
    alias_existente = CromoBotellaAlias(id_cromo_origen=100, id_cromo_destino=555, accion="fusionar")
    # MagicMock no distingue el filtro real: el primer .first() es el chequeo de bloqueo
    # (id_cromo_destino==100, debe dar "no bloqueado"), el segundo es el lookup del upsert
    # (id_cromo_origen==100, debe encontrar la fila existente) — mismo orden que el código real.
    _mock_para(model_mocks, CromoBotellaAlias).filter.return_value.first.side_effect = [None, alias_existente]

    eliminar_botella(session, origen="cromo", id=100, usuario="admin")

    assert alias_existente.accion == "ignorar"
    assert alias_existente.id_cromo_destino is None
    assert not any(isinstance(c.args[0], CromoBotellaAlias) for c in session.add.call_args_list)


def test_eliminar_botella_cromo_limpia_con_padre_que_sobrevive_por_otros_datos():
    session, model_mocks = _session_vacia()
    cromo = CromoBotella(n_id=100, camara_id=10)
    _mock_para(model_mocks, CromoBotella).filter.return_value.first.return_value = cromo
    padre = Camara(id=10, nombre="Padre", camara_padre_id=None)
    _mock_para(model_mocks, Camara).filter.return_value.first.return_value = padre
    _mock_para(model_mocks, Camara).filter.return_value.all.return_value = []
    # El padre tiene un Ingreso real propio -> no se puede borrar.
    _mock_para(model_mocks, Ingreso).filter.return_value.first.return_value = Ingreso(id=1, camara_id=10)

    resultado = eliminar_botella(session, origen="cromo", id=100, usuario="admin")

    assert resultado.camara_padre_eliminada is None
    session.delete.assert_called_once_with(cromo)  # sólo la botella, nunca el padre


def test_eliminar_botella_cromo_limpia_con_padre_que_queda_vacio_tambien_se_borra():
    session, model_mocks = _session_vacia()
    cromo = CromoBotella(n_id=100, camara_id=10)
    _mock_para(model_mocks, CromoBotella).filter.return_value.first.return_value = cromo
    padre = Camara(id=10, nombre="Padre", camara_padre_id=None)
    _mock_para(model_mocks, Camara).filter.return_value.first.return_value = padre
    _mock_para(model_mocks, Camara).filter.return_value.all.return_value = []

    resultado = eliminar_botella(session, origen="cromo", id=100, usuario="admin")

    assert resultado.camara_padre_eliminada == 10
    session.delete.assert_any_call(cromo)
    session.delete.assert_any_call(padre)


# ── eliminar_botella — origen='legado' ────────────────────────────────────────


def test_eliminar_botella_legado_no_existe():
    session, model_mocks = _session_vacia()
    _mock_para(model_mocks, Camara).filter.return_value.first.return_value = None
    with pytest.raises(EliminacionBloqueadaError, match="No existe"):
        eliminar_botella(session, origen="legado", id=5, usuario="admin")


def test_eliminar_botella_legado_no_es_botella():
    session, model_mocks = _session_vacia()
    raiz = Camara(id=5, nombre="Raiz", camara_padre_id=None)
    _mock_para(model_mocks, Camara).filter.return_value.first.return_value = raiz
    with pytest.raises(EliminacionBloqueadaError, match="no es una Botella"):
        eliminar_botella(session, origen="legado", id=5, usuario="admin")


@pytest.mark.parametrize(
    ("modelo_bloqueante", "kwargs", "fragmento"),
    [
        (Cable, {"origen_camara_id": 5}, "cables"),
        (Empalme, {"camara_id": 5}, "empalmes"),
        (Ingreso, {"camara_id": 5}, "ingresos"),
    ],
)
def test_eliminar_botella_legado_bloqueada_por_datos_reales(modelo_bloqueante, kwargs, fragmento):
    session, model_mocks = _session_vacia()
    legado = Camara(id=5, nombre="Bot 2", camara_padre_id=10)
    _mock_para(model_mocks, Camara).filter.return_value.first.return_value = legado
    _mock_para(model_mocks, modelo_bloqueante).filter.return_value.first.return_value = modelo_bloqueante(**kwargs)

    with pytest.raises(EliminacionBloqueadaError) as excinfo:
        eliminar_botella(session, origen="legado", id=5, usuario="admin")

    assert fragmento in excinfo.value.bloqueos[0].razon
    session.delete.assert_not_called()


def test_eliminar_botella_legado_limpia_borra_padre_vacio():
    session, model_mocks = _session_vacia()
    legado = Camara(id=5, nombre="Bot 2", camara_padre_id=10)
    padre = Camara(id=10, nombre="Padre", camara_padre_id=None)

    def query_camara(*_a):
        return _mock_para(model_mocks, Camara)

    _mock_para(model_mocks, Camara).filter.return_value.first.side_effect = [legado, padre]
    _mock_para(model_mocks, Camara).filter.return_value.all.return_value = []

    resultado = eliminar_botella(session, origen="legado", id=5, usuario="admin")

    assert resultado.alias_registrado is False
    assert resultado.camara_padre_eliminada == 10
    session.delete.assert_any_call(legado)
    session.delete.assert_any_call(padre)


# ── eliminar_camara ────────────────────────────────────────────────────────


def test_eliminar_camara_no_existe():
    session, model_mocks = _session_vacia()
    _mock_para(model_mocks, Camara).filter.return_value.first.return_value = None
    with pytest.raises(EliminacionBloqueadaError, match="No existe"):
        eliminar_camara(session, camara_id=1, usuario="admin")


def test_eliminar_camara_rechaza_si_es_una_botella():
    session, model_mocks = _session_vacia()
    _mock_para(model_mocks, Camara).filter.return_value.first.return_value = Camara(
        id=1, nombre="Bot 2", camara_padre_id=10
    )
    with pytest.raises(EliminacionBloqueadaError, match="no una Cámara raíz"):
        eliminar_camara(session, camara_id=1, usuario="admin")


def test_eliminar_camara_sin_hijos_limpia():
    session, model_mocks = _session_vacia()
    raiz = Camara(id=1, nombre="Raiz", camara_padre_id=None)
    _mock_para(model_mocks, Camara).filter.return_value.first.return_value = raiz
    _mock_para(model_mocks, Camara).filter.return_value.all.return_value = []

    resultado = eliminar_camara(session, camara_id=1, usuario="admin")

    assert resultado.botellas_legado_eliminadas == 0
    assert resultado.botellas_cromo_eliminadas == 0
    session.delete.assert_called_once_with(raiz)


def test_eliminar_camara_con_hijos_legado_y_cromo_limpios():
    session, model_mocks = _session_vacia()
    raiz = Camara(id=1, nombre="Raiz", camara_padre_id=None)
    hijo_legado = Camara(id=2, nombre="Bot 1", camara_padre_id=1)
    cromo_1 = CromoBotella(n_id=200, camara_id=1)

    _mock_para(model_mocks, Camara).filter.return_value.first.return_value = raiz
    _mock_para(model_mocks, Camara).filter.return_value.all.return_value = [hijo_legado]
    _mock_para(model_mocks, CromoBotella).filter.return_value.all.return_value = [cromo_1]

    resultado = eliminar_camara(session, camara_id=1, usuario="admin")

    assert resultado.botellas_legado_eliminadas == 1
    assert resultado.botellas_cromo_eliminadas == 1
    assert resultado.aliases_registrados == 1
    session.delete.assert_any_call(hijo_legado)
    session.delete.assert_any_call(cromo_1)
    session.delete.assert_any_call(raiz)
    alias_creado = next(c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], CromoBotellaAlias))
    assert alias_creado.id_cromo_origen == 200


def test_eliminar_camara_aborta_todo_si_un_hijo_esta_bloqueado():
    session, model_mocks = _session_vacia()
    raiz = Camara(id=1, nombre="Raiz", camara_padre_id=None)
    hijo_legado = Camara(id=2, nombre="Bot 1", camara_padre_id=1)

    _mock_para(model_mocks, Camara).filter.return_value.first.return_value = raiz
    _mock_para(model_mocks, Camara).filter.return_value.all.return_value = [hijo_legado]
    _mock_para(model_mocks, CromoBotella).filter.return_value.all.return_value = []
    # _bloqueo_camara corre primero para el hijo, después para la raíz — el primer .first() de
    # Ingreso corresponde al hijo (bloqueado), el segundo a la raíz (limpia).
    _mock_para(model_mocks, Ingreso).filter.return_value.first.side_effect = [Ingreso(id=1, camara_id=2), None]
    # (Cable/Empalme heredan el default "sin bloqueo" de _session_vacia; sólo Ingreso bloquea acá.)

    with pytest.raises(EliminacionBloqueadaError) as excinfo:
        eliminar_camara(session, camara_id=1, usuario="admin")

    assert len(excinfo.value.bloqueos) == 1
    assert excinfo.value.bloqueos[0].id == 2
    session.delete.assert_not_called()
    session.add.assert_not_called()


def test_eliminar_camara_reporta_multiples_bloqueos_simultaneos():
    session, model_mocks = _session_vacia()
    raiz = Camara(id=1, nombre="Raiz", camara_padre_id=None)
    hijo_legado = Camara(id=2, nombre="Bot 1", camara_padre_id=1)

    cromo_hijo = CromoBotella(n_id=200, camara_id=1)
    _mock_para(model_mocks, Camara).filter.return_value.first.return_value = raiz
    _mock_para(model_mocks, Camara).filter.return_value.all.return_value = [hijo_legado]
    _mock_para(model_mocks, CromoBotella).filter.return_value.all.return_value = [cromo_hijo]
    # El hijo legado bloquea por Cable (1er .first() = hijo; 2do = raíz, limpia); el hijo cromo
    # bloquea por CromoFusion (única llamada, un solo hijo cromo, la raíz no chequea CromoFusion).
    _mock_para(model_mocks, Cable).filter.return_value.first.side_effect = [Cable(id=9, origen_camara_id=2), None]
    _mock_para(model_mocks, CromoFusion).filter.return_value.first.return_value = CromoFusion(n_id=9, botella_n_id=200)

    with pytest.raises(EliminacionBloqueadaError) as excinfo:
        eliminar_camara(session, camara_id=1, usuario="admin")

    ids_bloqueados = {b.id for b in excinfo.value.bloqueos}
    assert ids_bloqueados == {2, 200}
    session.delete.assert_not_called()


def test_eliminar_camara_bloqueada_por_datos_propios_de_la_raiz_sin_hijos():
    session, model_mocks = _session_vacia()
    raiz = Camara(id=1, nombre="Raiz", camara_padre_id=None)
    _mock_para(model_mocks, Camara).filter.return_value.first.return_value = raiz
    _mock_para(model_mocks, Camara).filter.return_value.all.return_value = []
    _mock_para(model_mocks, CromoBotella).filter.return_value.all.return_value = []
    _mock_para(model_mocks, Empalme).filter.return_value.first.return_value = Empalme(id=1, camara_id=1)

    with pytest.raises(EliminacionBloqueadaError) as excinfo:
        eliminar_camara(session, camara_id=1, usuario="admin")

    assert excinfo.value.bloqueos[0].origen == "camara"
    assert excinfo.value.bloqueos[0].id == 1
    session.delete.assert_not_called()


# ── eliminar_y_excluir_grupo_cromo ────────────────────────────────────────────
# Camino deliberadamente forzado (botón de grupo del visor de duplicados): a diferencia de
# eliminar_botella, NUNCA bloquea por cables/fusiones reales asociados.


def test_eliminar_grupo_cromo_falla_si_lista_vacia():
    session, _ = _session_vacia()
    with pytest.raises(EliminacionBloqueadaError, match="No se indicó ninguna"):
        eliminar_y_excluir_grupo_cromo(session, ids_cromo=[], usuario="admin")


def test_eliminar_grupo_cromo_borra_pese_a_tener_cables_y_fusiones_reales():
    session, model_mocks = _session_vacia()
    botella_100 = CromoBotella(n_id=100, camara_id=None)
    botella_200 = CromoBotella(n_id=200, camara_id=None)
    _mock_para(model_mocks, CromoBotella).filter.return_value.all.return_value = [botella_100, botella_200]
    _mock_para(model_mocks, CromoCable).filter.return_value.delete.return_value = 3
    _mock_para(model_mocks, CromoFusion).filter.return_value.delete.return_value = 2

    resultado = eliminar_y_excluir_grupo_cromo(session, ids_cromo=[100, 200], usuario="admin")

    assert resultado.cables_eliminados == 3
    assert resultado.fusiones_eliminadas == 2
    assert resultado.botellas_eliminadas == [100, 200]
    assert resultado.aliases_registrados == 2
    session.delete.assert_any_call(botella_100)
    session.delete.assert_any_call(botella_200)


def test_eliminar_grupo_cromo_borra_cables_completos_sin_excluir_por_el_otro_extremo():
    """Confirmado con el usuario: si un CromoCable tiene un extremo en una botella eliminada y el
    otro en una que se conserva, el cable se borra igual (limpieza física completa, no quirúrgica).
    A nivel de mock: UN solo `.delete()` masivo sobre el filtro OR de ambos extremos, sin ninguna
    exclusión por-fila (el caso real de convivencia con una botella conservada se verifica contra
    datos reales, no con mocks — ver sección de Verificación del plan)."""
    session, model_mocks = _session_vacia()
    _mock_para(model_mocks, CromoCable).filter.return_value.delete.return_value = 1

    eliminar_y_excluir_grupo_cromo(session, ids_cromo=[100], usuario="admin")

    model_mocks[CromoCable].filter.return_value.delete.assert_called_once_with(synchronize_session=False)


def test_eliminar_grupo_cromo_registra_alias_ignorar_para_cada_n_id():
    session, model_mocks = _session_vacia()
    botella = CromoBotella(n_id=100, camara_id=None)
    _mock_para(model_mocks, CromoBotella).filter.return_value.all.return_value = [botella]

    eliminar_y_excluir_grupo_cromo(session, ids_cromo=[100], usuario="admin")

    alias_creado = next(c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], CromoBotellaAlias))
    assert alias_creado.id_cromo_origen == 100
    assert alias_creado.accion == "ignorar"
    assert alias_creado.id_cromo_destino is None


def test_eliminar_grupo_cromo_reporta_ids_no_encontrados_sin_abortar():
    session, model_mocks = _session_vacia()
    botella = CromoBotella(n_id=100, camara_id=None)
    _mock_para(model_mocks, CromoBotella).filter.return_value.all.return_value = [botella]

    resultado = eliminar_y_excluir_grupo_cromo(session, ids_cromo=[100, 999], usuario="admin")

    assert resultado.botellas_eliminadas == [100]
    assert resultado.no_encontradas == [999]


def test_eliminar_grupo_cromo_dedup_ids_repetidos():
    session, model_mocks = _session_vacia()
    botella = CromoBotella(n_id=100, camara_id=None)
    _mock_para(model_mocks, CromoBotella).filter.return_value.all.return_value = [botella]

    resultado = eliminar_y_excluir_grupo_cromo(session, ids_cromo=[100, 100], usuario="admin")

    assert resultado.ids_solicitados == [100]
    session.delete.assert_called_once_with(botella)
