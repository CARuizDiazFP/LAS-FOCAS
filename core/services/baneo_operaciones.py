# Nombre de archivo: baneo_operaciones.py
# Ubicación de archivo: core/services/baneo_operaciones.py
# Descripción: Crear, levantar y listar baneos (commit/rollback, aviso Slack y serialización) compartido por el panel y la API

"""Operaciones de baneo movidas desde `web/app/routers/camaras.py` y `api/app/routes/infra.py`.

`crear_baneo_y_notificar` y `levantar_baneo_y_notificar` envuelven `create_ban`/`lift_ban` con el
commit o rollback y el aviso a Slack; `listar_incidentes_activos` serializa los incidentes activos.
El autor (`usuario_ejecutor`) lo decide cada app: sesión en el panel, body en la API.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from core.config import get_settings
from core.services.protection_service import (
    BanResult,
    LiftResult,
    ProtectionService,
    create_ban,
    get_incidentes_activos,
    lift_ban,
)
from db.models.infra import Camara, CamaraEstado
from modules.slack_baneo_notifier.eventos import notificar_evento_baneo

logger = logging.getLogger(__name__)

# Largos máximos de los campos del request (alineados con db/models/infra.py, IncidenteBaneo).
LARGO_TICKET = 64
LARGO_SERVICIO = 64
LARGO_USUARIO = 128
LARGO_MOTIVO = 512


def _avisar_slack(session: Session, evento: str, datos: dict[str, Any]) -> None:
    """Aviso a Slack del evento; un fallo se loguea y nunca cambia la respuesta."""
    try:
        notificar_evento_baneo(session, evento, datos, get_settings().slack.bot_token)
    except Exception as exc:
        logger.warning("Error enviando aviso Slack de baneo (%s): %s", evento, exc)


def crear_baneo_y_notificar(
    session: Session,
    *,
    ticket_asociado: str | None,
    servicio_afectado_id: str,
    servicio_protegido_id: str,
    ruta_protegida_id: int | None,
    motivo: str | None,
    usuario_ejecutor: str | None,
) -> BanResult:
    """Crea el baneo; si tuvo éxito hace commit y avisa a Slack, si no hace rollback."""
    result = create_ban(
        session,
        ticket_asociado=ticket_asociado,
        servicio_afectado_id=servicio_afectado_id,
        servicio_protegido_id=servicio_protegido_id,
        ruta_protegida_id=ruta_protegida_id,
        usuario_ejecutor=usuario_ejecutor,
        motivo=motivo,
    )
    if result.success:
        session.commit()
        datos = result.to_dict()
        datos["servicio_afectado_id"] = servicio_afectado_id
        datos["servicio_protegido_id"] = servicio_protegido_id
        datos["ticket_asociado"] = ticket_asociado
        datos["usuario_ejecutor"] = usuario_ejecutor
        datos["motivo"] = motivo
        _avisar_slack(session, "create", datos)
    else:
        session.rollback()
    return result


def levantar_baneo_y_notificar(
    session: Session,
    incidente_id: int,
    *,
    usuario_ejecutor: str | None,
    motivo_cierre: str | None,
) -> LiftResult:
    """Levanta el baneo; si tuvo éxito hace commit y avisa a Slack, si no hace rollback."""
    result = lift_ban(
        session,
        incidente_id,
        usuario_ejecutor=usuario_ejecutor,
        motivo_cierre=motivo_cierre,
    )
    if result.success:
        session.commit()
        datos = result.to_dict()
        datos["usuario_ejecutor"] = usuario_ejecutor
        datos["motivo_cierre"] = motivo_cierre
        _avisar_slack(session, "lift", datos)
    else:
        session.rollback()
    return result


def listar_incidentes_activos(session: Session) -> dict[str, Any]:
    """Incidentes de baneo activos con conteo de cámaras (totales y baneadas) y duración en horas."""
    incidentes = get_incidentes_activos(session)
    servicio = ProtectionService(session)
    total_camaras_baneadas = (
        session.query(Camara.id).filter(Camara.estado == CamaraEstado.BANEADA).count()
    )

    datos: list[dict[str, Any]] = []
    for inc in incidentes:
        camaras = servicio.get_camaras_for_servicio(inc.servicio_protegido_id, inc.ruta_protegida_id)
        duracion = inc.duracion_horas
        datos.append({
            "id": inc.id,
            "ticket_asociado": inc.ticket_asociado,
            "servicio_afectado_id": inc.servicio_afectado_id,
            "servicio_protegido_id": inc.servicio_protegido_id,
            "ruta_protegida_id": inc.ruta_protegida_id,
            "usuario_ejecutor": inc.usuario_ejecutor,
            "motivo": inc.motivo,
            "fecha_inicio": inc.fecha_inicio.isoformat() if inc.fecha_inicio else None,
            "activo": inc.activo,
            "duracion_horas": round(duracion, 1) if duracion is not None else None,
            "camaras_count": len(camaras),
            "camaras_baneadas_count": sum(1 for c in camaras if c.estado == CamaraEstado.BANEADA),
        })
    return {
        "status": "ok",
        "incidentes": datos,
        "total": len(datos),
        "total_camaras_baneadas": total_camaras_baneadas,
    }
