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

    service = ProtectionService(session)
    resultado = service._camara_tiene_otro_baneo_activo(bot1.id, excluir_incidente_id=1)

    assert resultado is otro_incidente


def test_camara_tiene_otro_baneo_activo_sin_servicios_en_el_grupo_devuelve_none() -> None:
    padre, bot1, bot2 = _grupo()  # ningún miembro tiene empalmes

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = bot1

    service = ProtectionService(session)
    resultado = service._camara_tiene_otro_baneo_activo(bot1.id, excluir_incidente_id=1)

    assert resultado is None


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
