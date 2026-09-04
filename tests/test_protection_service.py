# Nombre de archivo: test_protection_service.py
# Ubicación de archivo: tests/test_protection_service.py
# Descripción: Pruebas de la cascada Cámara/Botella en el Protocolo de Protección (create_ban, _camara_tiene_otro_baneo_activo, restauración)

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from core.services.protection_service import ProtectionService
from db.models.infra import (
    Camara,
    CamaraEstado,
    CamaraEstadoAuditoria,
    CamaraOrigenDatos,
    Empalme,
    IncidenteBaneo,
    Ingreso,
    IngresoTipo,
    RutaServicio,
    Servicio,
)


def _grupo():
    padre = Camara(id=1, nombre="Cra Test CF", estado=CamaraEstado.LIBRE, origen_datos=CamaraOrigenDatos.INFERIDO)
    bot1 = Camara(id=2, nombre="Cra Test Bot 2 CF", estado=CamaraEstado.LIBRE, origen_datos=CamaraOrigenDatos.TRACKING)
    bot2 = Camara(id=3, nombre="Cra Test Bot 3 CF", estado=CamaraEstado.LIBRE, origen_datos=CamaraOrigenDatos.TRACKING)
    padre.botellas = [bot1, bot2]
    return padre, bot1, bot2


def test_create_ban_banea_grupo_completo_cuando_empalme_resuelve_una_botella() -> None:
    """El empalme de la ruta protegida resuelve la BOTELLA (bot1) — `create_ban` debe dejar baneado
    también al padre y a la hermana bot2 (cascada completa bidireccional), no sólo a bot1."""
    padre, bot1, bot2 = _grupo()
    session = MagicMock()
    servicio = Servicio(id=10, servicio_id="52547")
    session.query.return_value.filter.return_value.first.return_value = servicio

    service = ProtectionService(session)

    with patch.object(ProtectionService, "get_camaras_for_servicio", return_value=[bot1]):
        resultado = service.create_ban(
            ticket_asociado="INC-1",
            servicio_afectado_id="99999",
            servicio_protegido_id="52547",
        )

    assert resultado.success is True
    assert padre.estado == CamaraEstado.BANEADA
    assert bot1.estado == CamaraEstado.BANEADA
    assert bot2.estado == CamaraEstado.BANEADA
    assert resultado.camaras_baneadas == 3
    assert resultado.camaras_ya_baneadas == 0


def test_create_ban_no_duplica_conteo_si_dos_empalmes_resuelven_al_mismo_grupo() -> None:
    """Si `get_camaras_for_servicio` resuelve dos empalmes distintos que caen en el MISMO grupo
    (ej. dos rutas tocan bot1 y bot2 de la misma cámara), el conteo no debe duplicar miembros."""
    padre, bot1, bot2 = _grupo()
    session = MagicMock()
    servicio = Servicio(id=10, servicio_id="52547")
    session.query.return_value.filter.return_value.first.return_value = servicio

    service = ProtectionService(session)

    with patch.object(ProtectionService, "get_camaras_for_servicio", return_value=[bot1, bot2]):
        resultado = service.create_ban(
            ticket_asociado="INC-1",
            servicio_afectado_id="99999",
            servicio_protegido_id="52547",
        )

    assert resultado.camaras_baneadas == 3  # padre + bot1 + bot2, no 4 ni 6


def test_create_ban_camaras_ya_baneadas_no_se_recuentan_como_nuevas() -> None:
    padre, bot1, bot2 = _grupo()
    padre.estado = CamaraEstado.BANEADA
    bot1.estado = CamaraEstado.BANEADA
    bot2.estado = CamaraEstado.BANEADA
    session = MagicMock()
    servicio = Servicio(id=10, servicio_id="52547")
    session.query.return_value.filter.return_value.first.return_value = servicio

    service = ProtectionService(session)

    with patch.object(ProtectionService, "get_camaras_for_servicio", return_value=[bot1]):
        resultado = service.create_ban(
            ticket_asociado="INC-1",
            servicio_afectado_id="99999",
            servicio_protegido_id="52547",
        )

    assert resultado.camaras_baneadas == 0
    assert resultado.camaras_ya_baneadas == 3


def test_camara_tiene_otro_baneo_activo_considera_el_grupo_completo() -> None:
    """El chequeo de 'otro baneo activo' debe mirar los empalmes de TODO el grupo (hermanas + padre),
    no sólo los de la fila puntual que se está evaluando — hallazgo real de la revisión adversarial:
    si los empalmes reales viven en una botella hermana, mirar sólo `camara.empalmes` no ve el otro
    incidente y `lift_ban` podría restaurar de más."""
    padre, bot1, bot2 = _grupo()

    servicio_bot2 = Servicio(id=20, servicio_id="88888")
    ruta_bot2 = RutaServicio(id=200, servicio_id=20)
    ruta_bot2.servicio = servicio_bot2
    empalme_bot2 = Empalme(id=300, camara_id=bot2.id)
    empalme_bot2.rutas = [ruta_bot2]
    bot2.empalmes = [empalme_bot2]

    otro_incidente = IncidenteBaneo(id=555, servicio_protegido_id="88888", servicio_afectado_id="x", activo=True)

    session = MagicMock()
    # 1ra .first(): resuelve la Camara por id (bot1); 2da .first(): resuelve el IncidenteBaneo.
    session.query.return_value.filter.return_value.first.side_effect = [bot1, otro_incidente]
    # Camino Cromo: sin aporte en este caso (el hallazgo viene por legacy, vía empalme de bot2).
    session.execute.return_value.all.return_value = []

    service = ProtectionService(session)
    resultado = service._camara_tiene_otro_baneo_activo(bot1.id, excluir_incidente_id=1)

    assert resultado is otro_incidente


def test_camara_tiene_otro_baneo_activo_sin_servicios_en_el_grupo_devuelve_none() -> None:
    padre, bot1, bot2 = _grupo()  # ningún miembro tiene empalmes

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = bot1
    session.execute.return_value.all.return_value = []  # Cromo tampoco aporta nada

    service = ProtectionService(session)
    resultado = service._camara_tiene_otro_baneo_activo(bot1.id, excluir_incidente_id=1)

    assert resultado is None


def test_camara_tiene_otro_baneo_activo_detecta_via_cromo_cuando_legacy_no_ve_nada() -> None:
    """Hueco cerrado por el Refactor de baneos (2026-08-23): antes de este fix, si el ÚNICO vínculo
    entre el grupo y el otro incidente activo era vía infraestructura Cromo (sin ningún empalme/ruta
    legacy que lo conectara), `_camara_tiene_otro_baneo_activo` no lo veía — `servicios_ids` se
    calculaba sólo desde `miembro.empalmes`, y acá ningún miembro del grupo tiene empalmes. Este test
    habría fallado (resultado None) antes del fix y pasa después, porque ahora también une
    `servicio_ids_por_camaras_sync`."""
    padre, bot1, bot2 = _grupo()  # ningún miembro tiene empalmes legacy

    otro_incidente = IncidenteBaneo(
        id=777, servicio_protegido_id="CROMO-ONLY", servicio_afectado_id="x", activo=True
    )

    session = MagicMock()
    session.query.return_value.filter.return_value.first.side_effect = [bot1, otro_incidente]
    # El camino Cromo (session.execute, dentro de servicio_ids_por_camaras_sync) SÍ ve el servicio
    # protegido por el otro incidente, aunque no haya ningún empalme legacy que lo conecte al grupo.
    session.execute.return_value.all.return_value = [("CROMO-ONLY",)]

    service = ProtectionService(session)
    resultado = service._camara_tiene_otro_baneo_activo(bot1.id, excluir_incidente_id=1)

    assert resultado is otro_incidente


def test_determinar_estado_restauracion_mantiene_baneo_independiente_anterior_al_incidente() -> None:
    """Hallazgo real (QA de cascada, 2026-08-10): una cámara puede quedar BANEADA por un motivo
    INDEPENDIENTE de este incidente (override manual, herencia del backfill de jerarquía
    Cámara/Botella) sin ningún `IncidenteBaneo` que lo respalde — `_camara_tiene_otro_baneo_activo` no
    lo detecta porque sólo mira esa tabla. Si la última transición a BANEADA es anterior al inicio de
    este incidente, no se debe restaurar: se mantiene BANEADA."""
    camara = Camara(id=9, nombre="Cra Test CF", estado=CamaraEstado.BANEADA)
    incidente = IncidenteBaneo(id=1, fecha_inicio=datetime(2026, 8, 10, 13, 37, 0, tzinfo=timezone.utc))
    transicion_previa = CamaraEstadoAuditoria(
        camara_id=9,
        estado_anterior=CamaraEstado.LIBRE,
        estado_nuevo=CamaraEstado.BANEADA,
        created_at=datetime(2026, 7, 27, 20, 48, 0, tzinfo=timezone.utc),
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = transicion_previa

    service = ProtectionService(session)
    resultado = service._determinar_estado_restauracion(camara, incidente)

    assert resultado == CamaraEstado.BANEADA


def test_determinar_estado_restauracion_ya_no_preserva_detectada() -> None:
    """DETECTADA fue retirado del sistema (2026-08-11) — una transición previa con
    estado_anterior=DETECTADA ya no se preserva, cae al mismo cálculo LIBRE/OCUPADA por defecto que
    cualquier otra transición sin motivo independiente de baneo."""
    camara = Camara(id=9, nombre="Cra Test CF", estado=CamaraEstado.BANEADA)
    incidente = IncidenteBaneo(id=1, fecha_inicio=datetime(2026, 8, 10, 13, 0, 0, tzinfo=timezone.utc))
    transicion = CamaraEstadoAuditoria(
        camara_id=9,
        estado_anterior=CamaraEstado.DETECTADA,
        estado_nuevo=CamaraEstado.BANEADA,
        created_at=datetime(2026, 8, 10, 13, 30, 0, tzinfo=timezone.utc),
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = transicion
    session.query.return_value.filter.return_value.first.return_value = None  # sin ingreso activo

    service = ProtectionService(session)
    resultado = service._determinar_estado_restauracion(camara, incidente)

    assert resultado == CamaraEstado.LIBRE


def test_determinar_estado_restauracion_transicion_del_propio_incidente_restaura_libre() -> None:
    """Si la última transición a BANEADA es POSTERIOR (o simultánea) al inicio del incidente que se
    levanta, es la que generó este mismo incidente — corresponde restaurar normalmente."""
    camara = Camara(id=9, nombre="Cra Test CF", estado=CamaraEstado.BANEADA)
    incidente = IncidenteBaneo(id=1, fecha_inicio=datetime(2026, 8, 10, 13, 37, 0, tzinfo=timezone.utc))
    transicion = CamaraEstadoAuditoria(
        camara_id=9,
        estado_anterior=CamaraEstado.LIBRE,
        estado_nuevo=CamaraEstado.BANEADA,
        created_at=datetime(2026, 8, 10, 13, 37, 6, tzinfo=timezone.utc),
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = transicion
    session.query.return_value.filter.return_value.first.return_value = None  # sin ingreso activo

    service = ProtectionService(session)
    resultado = service._determinar_estado_restauracion(camara, incidente)

    assert resultado == CamaraEstado.LIBRE


def test_determinar_estado_restauracion_sin_historial_usa_logica_por_defecto() -> None:
    """Sin fila de auditoría aplicable (dato legado o nunca auditado) se mantiene el comportamiento
    original: OCUPADA si hay ingreso activo, LIBRE en otro caso."""
    camara = Camara(id=9, nombre="Cra Test CF", estado=CamaraEstado.BANEADA)
    incidente = IncidenteBaneo(id=1, fecha_inicio=datetime(2026, 8, 10, 13, 0, 0, tzinfo=timezone.utc))
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    session.query.return_value.filter.return_value.first.return_value = None

    service = ProtectionService(session)
    resultado = service._determinar_estado_restauracion(camara, incidente)

    assert resultado == CamaraEstado.LIBRE


def test_determinar_estado_restauracion_filtra_tipo_ingreso_no_cuenta_intento_bloqueado() -> None:
    """Bug real (revisión final 2026-09-04, hallazgo I1): la query de "ingreso activo" debe filtrar
    `Ingreso.tipo == IngresoTipo.INGRESO` explícitamente — sin este filtro, un `INTENTO_BLOQUEADO`
    (mismo `fecha_fin IS NULL` por diseño, nunca se cierra con un Egreso) hacía que `lift_ban`
    restaurara la cámara a OCUPADA de forma permanente en vez de LIBRE. Mismo fix que ya tenían
    `camara_estado_service.get_camara_estado_contexto` e `ingreso_service.py`."""
    camara = Camara(id=9, nombre="Cra Test CF", estado=CamaraEstado.BANEADA)
    incidente = IncidenteBaneo(id=1, fecha_inicio=datetime(2026, 8, 10, 13, 0, 0, tzinfo=timezone.utc))

    filtros_ingreso: list = []

    def _query_side_effect(model, *_a):
        query_mock = MagicMock()
        if model is CamaraEstadoAuditoria:
            query_mock.filter.return_value.order_by.return_value.first.return_value = None
        elif model is Ingreso:
            def _filter(*args, **kwargs):
                filtros_ingreso.extend(args)
                inner = MagicMock()
                # Simula que, con el filtro tipo=INGRESO aplicado, la fila INTENTO_BLOQUEADO
                # existente NO matchea — no hay ningún ingreso REAL activo.
                inner.first.return_value = None
                return inner
            query_mock.filter.side_effect = _filter
        return query_mock

    session = MagicMock()
    session.query.side_effect = _query_side_effect

    service = ProtectionService(session)
    resultado = service._determinar_estado_restauracion(camara, incidente)

    assert resultado == CamaraEstado.LIBRE
    tipo_filtrado = any(
        getattr(getattr(expr, "left", None), "key", None) == "tipo"
        and getattr(expr, "right", None) is not None
        and expr.right.value == IngresoTipo.INGRESO
        for expr in filtros_ingreso
    )
    assert tipo_filtrado, "Se esperaba un filtro Ingreso.tipo == IngresoTipo.INGRESO"


# ── get_camaras_for_servicio — cobertura directa (Refactor baneos, 2026-08-23) ──────────────────
#
# Hasta este fix, todos los tests de este archivo mockeaban `get_camaras_for_servicio` entero vía
# `patch.object` (ver arriba) — el método en sí no tenía cobertura directa. Estos tests lo ejercitan
# de verdad, mockeando sólo `session.query`/`session.execute`, para cubrir la resolución mixta
# legacy+Cromo que agrega esta tarea.


def test_get_camaras_for_servicio_solo_legacy() -> None:
    """Camino legacy resuelve una cámara; Cromo no aporta ninguna nueva (camara_ids_por_servicio_sync,
    vía session.execute, no devuelve filas) — el resultado final es sólo la cámara legacy."""
    camara_legacy = Camara(id=1, nombre="Cra Legacy", estado=CamaraEstado.LIBRE)
    empalme = Empalme(id=10, camara_id=1)
    empalme.camara = camara_legacy
    ruta = RutaServicio(id=100, servicio_id=10, activa=True)
    ruta.empalmes = [empalme]

    servicio = Servicio(id=10, servicio_id="52547")
    servicio.rutas = [ruta]

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = servicio
    session.execute.return_value.all.return_value = []  # Cromo: sin camara_ids nuevos

    service = ProtectionService(session)
    resultado = service.get_camaras_for_servicio("52547")

    assert [c.id for c in resultado] == [1]


def test_get_camaras_for_servicio_solo_cromo() -> None:
    """El servicio no tiene rutas/empalmes legacy, pero Cromo (session.execute) resuelve un camara_id
    nuevo — antes de esta tarea, este caso devolvía `[]` (servicio no baneable)."""
    servicio = Servicio(id=20, servicio_id="88888")
    servicio.rutas = []

    camara_cromo = Camara(id=5, nombre="Cra Cromo", estado=CamaraEstado.LIBRE)

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = servicio
    session.execute.return_value.all.return_value = [(5,)]
    session.query.return_value.filter.return_value.all.return_value = [camara_cromo]

    service = ProtectionService(session)
    resultado = service.get_camaras_for_servicio("88888")

    assert [c.id for c in resultado] == [5]


def test_get_camaras_for_servicio_solapamiento_no_duplica() -> None:
    """La misma cámara resuelta por legacy Y por Cromo (mismo Camara.id) no debe aparecer dos veces
    — ni volver a consultarse por `Camara.id.in_(...)`, porque ya está en camaras_set."""
    camara_compartida = Camara(id=7, nombre="Cra Compartida", estado=CamaraEstado.LIBRE)
    empalme = Empalme(id=11, camara_id=7)
    empalme.camara = camara_compartida
    ruta = RutaServicio(id=101, servicio_id=30, activa=True)
    ruta.empalmes = [empalme]

    servicio = Servicio(id=30, servicio_id="12345")
    servicio.rutas = [ruta]

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = servicio
    session.execute.return_value.all.return_value = [(7,)]  # mismo id que ya resolvió legacy

    service = ProtectionService(session)
    resultado = service.get_camaras_for_servicio("12345")

    assert [c.id for c in resultado] == [7]
    # camara_ids_faltantes queda vacío (7 - {7} == set()) — nunca se llega a pedir Camara.id.in_(...)
    session.query.return_value.filter.return_value.all.assert_not_called()


def test_get_camaras_for_servicio_ruta_id_explicito_ignora_cromo() -> None:
    """Cuando se pasa ruta_id explícito, el camino Cromo se ignora completamente (concepto de ruta
    puntual que Cromo no modela) — camara_ids_por_servicio_sync ni siquiera debería ejecutarse."""
    camara_legacy = Camara(id=2, nombre="Cra Ruta", estado=CamaraEstado.LIBRE)
    empalme = Empalme(id=12, camara_id=2)
    empalme.camara = camara_legacy
    ruta = RutaServicio(id=102, servicio_id=40, activa=True)
    ruta.empalmes = [empalme]

    servicio = Servicio(id=40, servicio_id="99999")

    session = MagicMock()
    # 1ra .first(): resuelve el Servicio; 2da .first(): resuelve la RutaServicio.
    session.query.return_value.filter.return_value.first.side_effect = [servicio, ruta]

    service = ProtectionService(session)
    resultado = service.get_camaras_for_servicio("99999", ruta_id=102)

    assert [c.id for c in resultado] == [2]
    session.execute.assert_not_called()


def test_get_camaras_for_servicio_cromo_excluye_camara_id_null() -> None:
    """`CromoBotella.camara_id IS NULL` queda excluida: el SQL de `camara_ids_por_servicio_sync`
    filtra `IS NOT NULL` (verificado directamente sobre el texto de la consulta en
    test_cromo_verificador.py) — acá se confirma que, si Cromo sólo aporta un camara_id resuelto
    (nunca None, porque el filtro ya actuó en la DB), el flujo de `get_camaras_for_servicio` no
    intenta resolver ninguna cámara "fantasma" con id None."""
    servicio = Servicio(id=50, servicio_id="55555")
    servicio.rutas = []

    camara_cromo = Camara(id=8, nombre="Cra Cromo Resuelta", estado=CamaraEstado.LIBRE)

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = servicio
    # El filtro `IS NOT NULL` de la SQL real garantiza que esta fila nunca incluye None — la fake
    # session sólo puede simular el resultado YA filtrado, no el filtro en sí.
    session.execute.return_value.all.return_value = [(8,)]
    session.query.return_value.filter.return_value.all.return_value = [camara_cromo]

    service = ProtectionService(session)
    resultado = service.get_camaras_for_servicio("55555")

    assert [c.id for c in resultado] == [8]
    assert None not in [c.id for c in resultado]


# ── _reconciliar_hermanos_cerrados — hallazgo real, 2026-08-28 ─────────────────────────────────
#
# Dos incidentes (#41/#42) que protegían el MISMO servicio por rutas redundantes (Principal/Backup)
# se cerraron con 4 segundos de diferencia. El que cerró primero (#42) dejó sus 60 cámaras
# `mantenida_otro_baneo` porque #41 todavía estaba activo en ese instante — correcto en el momento,
# pero `lift_ban` de #41 sólo reevaluó las cámaras de SU PROPIA ruta, nunca las de #42 (ya cerrado).
# 74 cámaras/botellas reales quedaron BANEADA sin ningún incidente activo detrás (ver
# `docs/decisiones.md`, entrada 2026-08-28). Estos tests cubren el fix: `lift_ban` ahora reintenta la
# restauración de cualquier incidente hermano ya cerrado del mismo servicio.


def test_reconciliar_hermanos_cerrados_libera_camara_bloqueada_por_hermano_ya_cerrado() -> None:
    """Un hermano ya CERRADO había dejado una cámara pendiente porque, al momento de SU cierre, el
    incidente que estamos cerrando ahora todavía estaba activo. Al cerrar este último, la
    reconciliación debe terminar de liberarla."""
    camara = Camara(id=9, nombre="Cra Test CF", estado=CamaraEstado.BANEADA)
    hermano = IncidenteBaneo(
        id=42,
        servicio_protegido_id="112922",
        ruta_protegida_id=75,
        activo=False,
        fecha_inicio=datetime(2026, 8, 19, 11, 9, 0, tzinfo=timezone.utc),
    )
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [hermano]

    service = ProtectionService(session)
    with (
        patch.object(ProtectionService, "get_camaras_for_servicio", return_value=[camara]),
        patch.object(ProtectionService, "_camara_tiene_otro_baneo_activo", return_value=None),
        patch.object(ProtectionService, "_determinar_estado_restauracion", return_value=CamaraEstado.LIBRE),
    ):
        resultado = service._reconciliar_hermanos_cerrados("112922", incidente_excluido_id=41)

    assert camara.estado == CamaraEstado.LIBRE
    assert len(resultado) == 1
    assert resultado[0]["id"] == 9
    assert resultado[0]["accion"] == "restaurada_hermano"
    assert resultado[0]["incidente_hermano_id"] == 42


def test_reconciliar_hermanos_cerrados_no_toca_baneo_independiente() -> None:
    """Si `_determinar_estado_restauracion` dice que se mantiene BANEADA (motivo independiente,
    anterior al hermano), la reconciliación no debe tocarla."""
    camara = Camara(id=9, nombre="Cra Test CF", estado=CamaraEstado.BANEADA)
    hermano = IncidenteBaneo(id=42, servicio_protegido_id="112922", ruta_protegida_id=75, activo=False)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [hermano]

    service = ProtectionService(session)
    with (
        patch.object(ProtectionService, "get_camaras_for_servicio", return_value=[camara]),
        patch.object(ProtectionService, "_camara_tiene_otro_baneo_activo", return_value=None),
        patch.object(ProtectionService, "_determinar_estado_restauracion", return_value=CamaraEstado.BANEADA),
    ):
        resultado = service._reconciliar_hermanos_cerrados("112922", incidente_excluido_id=41)

    assert camara.estado == CamaraEstado.BANEADA
    assert resultado == []


def test_reconciliar_hermanos_cerrados_no_toca_si_otro_incidente_sigue_activo() -> None:
    """Si TODAVÍA hay un tercer incidente activo protegiendo el grupo, no se libera — y ni siquiera
    se llega a calcular el estado de restauración."""
    camara = Camara(id=9, nombre="Cra Test CF", estado=CamaraEstado.BANEADA)
    hermano = IncidenteBaneo(id=42, servicio_protegido_id="112922", ruta_protegida_id=75, activo=False)
    otro_activo = IncidenteBaneo(id=99, servicio_protegido_id="112922", activo=True)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [hermano]

    service = ProtectionService(session)
    with (
        patch.object(ProtectionService, "get_camaras_for_servicio", return_value=[camara]),
        patch.object(ProtectionService, "_camara_tiene_otro_baneo_activo", return_value=otro_activo),
        patch.object(ProtectionService, "_determinar_estado_restauracion") as mock_determinar,
    ):
        resultado = service._reconciliar_hermanos_cerrados("112922", incidente_excluido_id=41)

    mock_determinar.assert_not_called()
    assert camara.estado == CamaraEstado.BANEADA
    assert resultado == []


def test_reconciliar_hermanos_cerrados_sin_hermanos_no_hace_nada() -> None:
    """Sin incidentes hermanos cerrados para el mismo servicio, no se resuelve ninguna cámara —
    `get_camaras_for_servicio` ni siquiera debería invocarse."""
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []

    service = ProtectionService(session)
    with patch.object(ProtectionService, "get_camaras_for_servicio") as mock_get:
        resultado = service._reconciliar_hermanos_cerrados("112922", incidente_excluido_id=41)

    mock_get.assert_not_called()
    assert resultado == []


def test_lift_ban_incluye_restauraciones_de_hermanos_cerrados() -> None:
    """`lift_ban` debe invocar la reconciliación de hermanos y sumar sus resultados al conteo final
    — sin esto, el fix de `_reconciliar_hermanos_cerrados` quedaría escrito pero nunca ejecutado."""
    incidente = IncidenteBaneo(
        id=41,
        servicio_protegido_id="112922",
        ruta_protegida_id=78,
        activo=True,
        fecha_inicio=datetime(2026, 8, 19, 11, 0, 0, tzinfo=timezone.utc),
    )
    session = MagicMock()
    service = ProtectionService(session)

    restaurada_hermano = {
        "id": 100,
        "nombre": "Cra Hermano",
        "estado_anterior": "BANEADA",
        "estado_nuevo": "LIBRE",
        "accion": "restaurada_hermano",
        "incidente_hermano_id": 42,
    }

    with (
        patch.object(ProtectionService, "get_incidente_by_id", return_value=incidente),
        patch.object(ProtectionService, "get_camaras_for_servicio", return_value=[]),
        patch.object(
            ProtectionService, "_reconciliar_hermanos_cerrados", return_value=[restaurada_hermano]
        ) as mock_reconciliar,
    ):
        resultado = service.lift_ban(41, usuario_ejecutor="admin2")

    mock_reconciliar.assert_called_once_with("112922", 41, usuario_ejecutor="admin2")
    assert resultado.success is True
    assert resultado.camaras_restauradas == 1
    assert restaurada_hermano in resultado.camaras_afectadas
    assert incidente.activo is False
