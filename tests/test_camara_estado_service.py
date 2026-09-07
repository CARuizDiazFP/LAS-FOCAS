# Nombre de archivo: test_camara_estado_service.py
# Ubicación de archivo: tests/test_camara_estado_service.py
# Descripción: Pruebas de la cascada de estado Cámara/Botella (aplicar_estado_a_grupo, miembros_del_grupo)

from __future__ import annotations

import unittest
from typing import Any
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
        tiene_incidente_activo=False,
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
        tiene_incidente_activo=False,
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
        tiene_incidente_activo=False,
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
        tiene_incidente_activo=False,
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


class TestGetCamaraEstadoContexto(unittest.TestCase):
    """Cobertura nueva para `get_camara_estado_contexto` (Tarea 3, 2026-09-04) — hasta esta revisión
    la función no tenía NINGÚN test directo (sólo se la mockeaba desde otros módulos). Hallazgo real
    de esta tarea: `tiene_baneo_activo` sólo miraba `IncidenteBaneo`, nunca `Camara.estado ==
    BANEADA` — un baneo manual (override admin, sin incidente de protección asociado) quedaba
    invisible tanto para el badge web como para el listener de Slack de ingreso."""

    def _entity_name(self, entity: Any) -> str:
        name = getattr(entity, "__name__", "")
        if name:
            return name
        cls = getattr(entity, "class_", None)
        return getattr(cls, "__name__", "") if cls is not None else ""

    def _fake_session(
        self,
        camara: Any,
        capturar_filtros_ingreso: list | None = None,
        incidentes: list | None = None,
    ) -> Any:
        session = MagicMock()

        def _query(*entities):
            entity_name = self._entity_name(entities[0])
            query_mock = MagicMock()
            if entity_name == "Camara":
                query_mock.filter.return_value.first.return_value = camara
            elif entity_name == "Ingreso":
                def _filter(*args, **kwargs):
                    if capturar_filtros_ingreso is not None:
                        capturar_filtros_ingreso.extend(args)
                    inner = MagicMock()
                    inner.first.return_value = None
                    return inner
                query_mock.filter.side_effect = _filter
            elif entity_name == "IncidenteBaneo":
                query_mock.filter.return_value.order_by.return_value.all.return_value = incidentes or []
            return query_mock

        session.query.side_effect = _query
        return session

    def test_baneo_manual_de_una_botella_hermana_marca_tiene_baneo_activo(self) -> None:
        """Bug real (esta tarea): consultar el contexto de la cámara RAÍZ (estado LIBRE) mientras una
        Botella hermana está BANEADA manualmente (sin incidente) debía dar tiene_baneo_activo=True —
        antes daba False porque la función nunca miraba `Camara.estado`, sólo `IncidenteBaneo`."""
        from core.services.camara_estado_service import get_camara_estado_contexto

        padre, bot1, bot2 = _grupo(
            estado_padre=CamaraEstado.LIBRE, estado_bot1=CamaraEstado.BANEADA, estado_bot2=CamaraEstado.LIBRE
        )
        padre.empalmes = []
        session = self._fake_session(padre)

        contexto = get_camara_estado_contexto(session, padre.id)

        self.assertTrue(contexto.tiene_baneo_activo)
        self.assertEqual(contexto.incidentes_activos, [])

    def test_baneo_manual_de_la_camara_misma_marca_tiene_baneo_activo(self) -> None:
        from core.services.camara_estado_service import get_camara_estado_contexto

        padre, bot1, bot2 = _grupo(estado_padre=CamaraEstado.BANEADA)
        padre.empalmes = []
        session = self._fake_session(padre)

        contexto = get_camara_estado_contexto(session, padre.id)

        self.assertTrue(contexto.tiene_baneo_activo)

    def test_sin_baneo_manual_ni_incidente_da_false(self) -> None:
        from core.services.camara_estado_service import get_camara_estado_contexto

        padre, bot1, bot2 = _grupo()
        padre.empalmes = []
        session = self._fake_session(padre)

        contexto = get_camara_estado_contexto(session, padre.id)

        self.assertFalse(contexto.tiene_baneo_activo)

    def test_tiene_ingreso_activo_filtra_por_tipo_ingreso(self) -> None:
        """La query de `tiene_ingreso_activo` debe filtrar explícitamente `tipo == INGRESO` — sin
        esto, un `INTENTO_BLOQUEADO` (mismo `fecha_fin IS NULL`) contaría como ingreso activo real."""
        from core.services.camara_estado_service import get_camara_estado_contexto
        from db.models.infra import IngresoTipo

        padre, bot1, bot2 = _grupo()
        padre.empalmes = []
        filtros: list[Any] = []
        session = self._fake_session(padre, capturar_filtros_ingreso=filtros)

        contexto = get_camara_estado_contexto(session, padre.id)

        self.assertFalse(contexto.tiene_ingreso_activo)
        tipo_filtrado = any(
            getattr(getattr(expr, "left", None), "key", None) == "tipo"
            and getattr(expr, "right", None) is not None
            and expr.right.value == IngresoTipo.INGRESO
            for expr in filtros
        )
        self.assertTrue(tipo_filtrado, "Se esperaba un filtro Ingreso.tipo == IngresoTipo.INGRESO")

    def test_baneo_manual_sin_incidente_da_tiene_incidente_activo_false(self) -> None:
        """`tiene_incidente_activo` (campo nuevo, revisión final 2026-09-04) preserva el significado
        ORIGINAL de `tiene_baneo_activo` previo a esta tarea: debe ser `False` para un grupo baneado
        SÓLO manualmente (sin `IncidenteBaneo`), aunque `tiene_baneo_activo` (el signal amplio, que
        SÍ cuenta el baneo manual) sea `True` — `baneos_grupos_service.py` depende de esta distinción
        para no bloquear la liberación masiva de un grupo así."""
        from core.services.camara_estado_service import get_camara_estado_contexto

        padre, bot1, bot2 = _grupo(estado_padre=CamaraEstado.BANEADA)
        padre.empalmes = []
        session = self._fake_session(padre)

        contexto = get_camara_estado_contexto(session, padre.id)

        self.assertTrue(contexto.tiene_baneo_activo)
        self.assertFalse(contexto.tiene_incidente_activo)

    def test_incidente_baneo_activo_da_tiene_incidente_activo_true(self) -> None:
        """Con un `IncidenteBaneo` activo real afectando al grupo, `tiene_incidente_activo` debe ser
        `True` (igual que `tiene_baneo_activo`) — contraparte del test anterior."""
        from types import SimpleNamespace

        from core.services.camara_estado_service import get_camara_estado_contexto

        padre, bot1, bot2 = _grupo()
        padre.empalmes = []
        incidente = SimpleNamespace(
            id=99,
            ticket_asociado="TCK-1",
            servicio_protegido_id="SRV1",
            ruta_protegida_id=None,
            fecha_inicio=None,
            motivo="corte de fibra",
            activo=True,
        )
        session = self._fake_session(padre, incidentes=[incidente])

        # `_collect_servicios_y_rutas` normalmente deriva servicios_ids de los empalmes reales del
        # grupo — acá no hace falta armar esa cadena completa (empalme->ruta->servicio) sólo para
        # forzar el camino "hay servicios_ids", así que se fuerza directamente el resultado.
        with patch(
            "core.services.camara_estado_service._collect_servicios_y_rutas",
            return_value=({"SRV1"}, set()),
        ):
            contexto = get_camara_estado_contexto(session, padre.id)

        self.assertTrue(contexto.tiene_incidente_activo)
        self.assertTrue(contexto.tiene_baneo_activo)
        self.assertEqual(len(contexto.incidentes_activos), 1)
