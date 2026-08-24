# Nombre de archivo: test_camara_estado_service.py
# Ubicación de archivo: tests/test_camara_estado_service.py
# Descripción: Pruebas de la cascada de estado Cámara/Botella (aplicar_estado_a_grupo, miembros_del_grupo)

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.services.camara_estado_service import (
    aplicar_estado_a_grupo,
    miembros_del_grupo,
    override_camara_estado_manual,
    CamaraEstadoContexto,
)
from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos


def _grupo(estado_padre=CamaraEstado.LIBRE, estado_bot1=CamaraEstado.LIBRE, estado_bot2=CamaraEstado.LIBRE):
    padre = Camara(id=1, nombre="Cra Test CF", estado=estado_padre, origen_datos=CamaraOrigenDatos.INFERIDO)
    bot1 = Camara(id=2, nombre="Cra Test Bot 2 CF", estado=estado_bot1, origen_datos=CamaraOrigenDatos.TRACKING)
    bot2 = Camara(id=3, nombre="Cra Test Bot 3 CF", estado=estado_bot2, origen_datos=CamaraOrigenDatos.TRACKING)
    padre.botellas = [bot1, bot2]
    return padre, bot1, bot2


def test_miembros_del_grupo_desde_la_raiz_incluye_toda_la_raiz_y_botellas() -> None:
    padre, bot1, bot2 = _grupo()
    miembros = miembros_del_grupo(padre)
    assert {m.id for m in miembros} == {1, 2, 3}


def test_miembros_del_grupo_desde_una_botella_resuelve_el_mismo_grupo() -> None:
    padre, bot1, bot2 = _grupo()
    miembros = miembros_del_grupo(bot1)
    assert {m.id for m in miembros} == {1, 2, 3}


def test_miembros_del_grupo_camara_sin_padre_ni_botellas_es_ella_misma() -> None:
    sola = Camara(id=42, nombre="Cra Aislada CF", estado=CamaraEstado.LIBRE)
    assert miembros_del_grupo(sola) == [sola]


def test_aplicar_estado_a_grupo_banear_una_botella_banea_padre_y_hermana() -> None:
    """Cascada completa bidireccional: banear la botella 2 debe dejar BANEADA a la raíz Y a la
    botella 3 hermana — no sólo a la botella 2 que originó la acción."""
    padre, bot1, bot2 = _grupo()
    session = MagicMock()

    auditorias = aplicar_estado_a_grupo(
        session, bot1, CamaraEstado.BANEADA, usuario="test", motivo="prueba"
    )

    assert padre.estado == CamaraEstado.BANEADA
    assert bot1.estado == CamaraEstado.BANEADA
    assert bot2.estado == CamaraEstado.BANEADA
    assert {a.camara_id for a in auditorias} == {1, 2, 3}


def test_aplicar_estado_a_grupo_banear_la_camara_banea_todas_las_botellas() -> None:
    """Dirección opuesta: banear la cámara padre directamente también cascada hacia abajo a TODAS
    sus botellas — decisión de negocio explícita (seguridad de campo: acceso a la cámara física
    pone en riesgo a todas las botellas dentro, no sólo a una)."""
    padre, bot1, bot2 = _grupo()
    session = MagicMock()

    aplicar_estado_a_grupo(session, padre, CamaraEstado.BANEADA, usuario="test", motivo="prueba")

    assert bot1.estado == CamaraEstado.BANEADA
    assert bot2.estado == CamaraEstado.BANEADA


def test_aplicar_estado_a_grupo_no_audita_miembros_que_ya_estaban_en_el_estado() -> None:
    padre, bot1, bot2 = _grupo(estado_padre=CamaraEstado.BANEADA, estado_bot1=CamaraEstado.LIBRE, estado_bot2=CamaraEstado.BANEADA)
    session = MagicMock()

    auditorias = aplicar_estado_a_grupo(session, bot1, CamaraEstado.BANEADA, usuario="test", motivo="prueba")

    # Sólo bot1 cambió (LIBRE->BANEADA); padre y bot2 ya estaban BANEADA, no generan auditoría nueva.
    assert {a.camara_id for a in auditorias} == {2}


def test_aplicar_estado_a_grupo_grupo_entero_ya_en_estado_no_hace_nada() -> None:
    padre, bot1, bot2 = _grupo(
        estado_padre=CamaraEstado.BANEADA, estado_bot1=CamaraEstado.BANEADA, estado_bot2=CamaraEstado.BANEADA
    )
    session = MagicMock()

    auditorias = aplicar_estado_a_grupo(session, padre, CamaraEstado.BANEADA, usuario="test", motivo="prueba")

    assert auditorias == []
    session.flush.assert_not_called()
    session.query.assert_not_called()  # sin miembros modificados, tampoco se toca CromoBotella


def test_aplicar_estado_a_grupo_propaga_a_cromo_botella_vinculada() -> None:
    """Hallazgo real (2026-08-12): 295 `CromoBotella` quedaron con estado stale porque
    `aplicar_estado_a_grupo` nunca las tocaba — sólo escribía `Camara.estado`. Cada miembro
    modificado del grupo debe sincronizar sus Botellas Cromo propias con el mismo estado mapeado."""
    padre, bot1, bot2 = _grupo()
    session = MagicMock()

    aplicar_estado_a_grupo(session, padre, CamaraEstado.BANEADA, usuario="test", motivo="prueba")

    assert any(call.args and call.args[0] is CromoBotella for call in session.query.call_args_list)
    update_kwargs = session.query.return_value.filter.return_value.update.call_args[0][0]
    assert update_kwargs[CromoBotella.estado] == CamaraEstado.BANEADA


def test_aplicar_estado_a_grupo_no_propaga_a_miembro_sin_cambios() -> None:
    """Sólo los miembros efectivamente modificados sincronizan sus CromoBotella — uno que ya estaba
    en el estado destino no necesita tocarse (sus Botellas ya deberían estar en sync)."""
    padre, bot1, bot2 = _grupo(estado_padre=CamaraEstado.BANEADA, estado_bot1=CamaraEstado.LIBRE, estado_bot2=CamaraEstado.BANEADA)
    session = MagicMock()

    aplicar_estado_a_grupo(session, bot1, CamaraEstado.BANEADA, usuario="test", motivo="prueba")

    ids_filtrados = session.query.return_value.filter.call_args[0][0]
    # sólo bot1 (id=2) cambió — padre y bot2 ya estaban BANEADA.
    assert list(ids_filtrados.right.value) == [2]


def test_mapeo_estado_cromo_mapea_estados_sin_equivalente_propio() -> None:
    from core.services.camara_estado_service import MAPEO_ESTADO_CROMO

    assert MAPEO_ESTADO_CROMO[CamaraEstado.DETECTADA] == CamaraEstado.OCUPADA
    assert MAPEO_ESTADO_CROMO[CamaraEstado.PENDIENTE_REVISION] == CamaraEstado.NO_OPERATIVA
    assert MAPEO_ESTADO_CROMO[CamaraEstado.LIBRE] == CamaraEstado.LIBRE


def test_aplicar_estado_a_grupo_contexto_solo_en_el_objetivo_directo() -> None:
    """`estado_sugerido`/`incidentes_activos_ids` sólo describen la acción sobre el objetivo directo
    (`camara`) — las filas de auditoría de los demás miembros del grupo no deben llevar ese contexto,
    que no les pertenece."""
    padre, bot1, bot2 = _grupo()
    session = MagicMock()

    auditorias = aplicar_estado_a_grupo(
        session,
        bot1,
        CamaraEstado.BANEADA,
        usuario="test",
        motivo="prueba",
        estado_sugerido=CamaraEstado.BANEADA,
        incidentes_activos_ids=[11, 12],
    )

    auditoria_directa = next(a for a in auditorias if a.camara_id == bot1.id)
    otras = [a for a in auditorias if a.camara_id != bot1.id]

    assert auditoria_directa.estado_sugerido == CamaraEstado.BANEADA
    assert auditoria_directa.incidentes_activos == [11, 12]
    assert all(a.estado_sugerido is None and a.incidentes_activos is None for a in otras)


def test_override_camara_estado_manual_grupo_mixto_fila_puntual_en_destino() -> None:
    """Test de regresión: override sobre grupo mixto donde la fila puntual ya está en el estado
    destino pero una hermana no. Debe resultar en changed=True y cascada correcta.

    Caso de bug real: alguien intenta banear una fila que ya está BANEADA (por ejemplo, un alias
    del Excel que ya fue baneado en una corrida anterior). Sin el fix, la función retornaba
    changed=False sin sincronizar hermanas — violando el invariante de cascada."""
    padre, bot1, bot2 = _grupo(
        estado_padre=CamaraEstado.LIBRE,
        estado_bot1=CamaraEstado.BANEADA,  # bot1 ya está en destino
        estado_bot2=CamaraEstado.LIBRE,    # bot2 NO está en destino
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.first.side_effect = lambda: bot1

    # Crear un contexto válido para el override
    contexto_mock = CamaraEstadoContexto(
        camara_id=bot1.id,
        estado_actual=CamaraEstado.BANEADA,
        estado_sugerido=CamaraEstado.BANEADA,
        tiene_baneo_activo=False,
        tiene_ingreso_activo=False,
        inconsistente=False,
        incidentes_activos=[],
        ticket_baneo=None,
    )

    with patch("core.services.camara_estado_service.get_camara_estado_contexto", return_value=contexto_mock):
        resultado = override_camara_estado_manual(
            session,
            camara_id=2,  # bot1.id
            nuevo_estado=CamaraEstado.BANEADA,
            usuario="test",
            motivo="prueba",
        )

    # Verificar que changed=True (no False como pasaría con el bug)
    assert resultado.changed == True
    assert resultado.success == True
    # Verificar que la cascada se ejecutó: bot2 debe estar BANEADA ahora
    assert bot2.estado == CamaraEstado.BANEADA
    # Verificar que padre también fue actualizado por la cascada
    assert padre.estado == CamaraEstado.BANEADA


def test_override_camara_estado_manual_cromo_botella_desincronizada_no_corta() -> None:
    """Hallazgo de la revisión final del plan: el short-circuit sólo miraba `miembros_del_grupo`
    (legado). Si TODO el legado del grupo ya está en `nuevo_estado` pero una `CromoBotella` vinculada
    a la raíz sigue en otro estado, la función debía cortar en `changed=False` sin sincronizarla —
    exactamente el invariante que la cascada existe para garantizar. Con el fix, debe seguir de
    largo e invocar `aplicar_estado_a_grupo` (no cortar en el gate).

    Regresión encontrada en la re-review de ese mismo fix: `aplicar_estado_a_grupo` sólo sincroniza
    `CromoBotella` de miembros legado que efectivamente cambiaron — con el legado ya en destino, no
    hay ningún miembro que modificar y devuelve `auditorias=[]` (mockeado acá para simular
    exactamente ese caso). La función NO debe reportar `changed=True` cuando no hubo auditorías
    reales — sería un falso positivo (grupo "recién baneado" que ya estaba baneado)."""
    padre, bot1, bot2 = _grupo(
        estado_padre=CamaraEstado.BANEADA,
        estado_bot1=CamaraEstado.BANEADA,
        estado_bot2=CamaraEstado.BANEADA,
    )
    cromo_desincronizada = CromoBotella(n_id=100, estado=CamaraEstado.LIBRE)
    padre.cromo_botellas = [cromo_desincronizada]

    session = MagicMock()
    session.query.return_value.filter.return_value.first.side_effect = lambda: padre

    contexto_mock = CamaraEstadoContexto(
        camara_id=padre.id,
        estado_actual=CamaraEstado.BANEADA,
        estado_sugerido=CamaraEstado.BANEADA,
        tiene_baneo_activo=False,
        tiene_ingreso_activo=False,
        inconsistente=False,
        incidentes_activos=[],
        ticket_baneo=None,
    )

    with (
        patch("core.services.camara_estado_service.get_camara_estado_contexto", return_value=contexto_mock),
        patch("core.services.camara_estado_service.aplicar_estado_a_grupo", return_value=[]) as mock_aplicar,
    ):
        resultado = override_camara_estado_manual(
            session,
            camara_id=1,  # padre.id
            nuevo_estado=CamaraEstado.BANEADA,
            usuario="test",
            motivo="prueba",
        )

    # El gate no cortó (mock_aplicar fue invocado), pero como no produjo auditorías reales,
    # changed debe ser False — NO True. Éste es el fix de esta tarea: antes, cruzar el gate
    # bastaba para reportar changed=True sin importar si aplicar_estado_a_grupo hizo algo.
    assert resultado.changed == False
    assert resultado.success == True
    mock_aplicar.assert_called_once()


def test_override_camara_estado_manual_legado_y_cromo_en_destino_no_cambia() -> None:
    """Caso contrario al anterior: legado Y CromoBotella ya en el estado esperado por
    `MAPEO_ESTADO_CROMO` → sigue cortando en `changed=False`, cero llamadas a `aplicar_estado_a_grupo`."""
    padre, bot1, bot2 = _grupo(
        estado_padre=CamaraEstado.BANEADA,
        estado_bot1=CamaraEstado.BANEADA,
        estado_bot2=CamaraEstado.BANEADA,
    )
    cromo_sincronizada = CromoBotella(n_id=101, estado=CamaraEstado.BANEADA)
    padre.cromo_botellas = [cromo_sincronizada]

    session = MagicMock()
    session.query.return_value.filter.return_value.first.side_effect = lambda: padre

    contexto_mock = CamaraEstadoContexto(
        camara_id=padre.id,
        estado_actual=CamaraEstado.BANEADA,
        estado_sugerido=CamaraEstado.BANEADA,
        tiene_baneo_activo=False,
        tiene_ingreso_activo=False,
        inconsistente=False,
        incidentes_activos=[],
        ticket_baneo=None,
    )

    with (
        patch("core.services.camara_estado_service.get_camara_estado_contexto", return_value=contexto_mock),
        patch("core.services.camara_estado_service.aplicar_estado_a_grupo") as mock_aplicar,
    ):
        resultado = override_camara_estado_manual(
            session,
            camara_id=1,  # padre.id
            nuevo_estado=CamaraEstado.BANEADA,
            usuario="test",
            motivo="prueba",
        )

    assert resultado.changed == False
    assert resultado.success == True
    mock_aplicar.assert_not_called()


def test_override_camara_estado_manual_grupo_entero_en_destino_no_cambia() -> None:
    """Test de regresión: override sobre grupo donde TODOS los miembros ya están en el estado
    destino. Debe resultar en changed=False y NO generar auditoría nueva.

    Verifica que el fix no causa cambios innecesarios cuando el grupo está sincronizado."""
    padre, bot1, bot2 = _grupo(
        estado_padre=CamaraEstado.BANEADA,
        estado_bot1=CamaraEstado.BANEADA,
        estado_bot2=CamaraEstado.BANEADA,
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.first.side_effect = lambda: bot1

    contexto_mock = CamaraEstadoContexto(
        camara_id=bot1.id,
        estado_actual=CamaraEstado.BANEADA,
        estado_sugerido=CamaraEstado.BANEADA,
        tiene_baneo_activo=False,
        tiene_ingreso_activo=False,
        inconsistente=False,
        incidentes_activos=[],
        ticket_baneo=None,
    )

    with patch("core.services.camara_estado_service.get_camara_estado_contexto", return_value=contexto_mock):
        resultado = override_camara_estado_manual(
            session,
            camara_id=2,  # bot1.id
            nuevo_estado=CamaraEstado.BANEADA,
            usuario="test",
            motivo="prueba",
        )

    # Verificar que changed=False (grupo ya estaba sincronizado)
    assert resultado.changed == False
    assert resultado.success == True
    # Estados deben permanecer sin cambios
    assert padre.estado == CamaraEstado.BANEADA
    assert bot1.estado == CamaraEstado.BANEADA
    assert bot2.estado == CamaraEstado.BANEADA
