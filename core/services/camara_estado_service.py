# Nombre de archivo: camara_estado_service.py
# Ubicación de archivo: core/services/camara_estado_service.py
# Descripción: Servicio para contextualizar y auditar overrides manuales del estado de cámaras

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any

from sqlalchemy.orm import Session

from db.models.infra import Camara, CamaraEstado, CamaraEstadoAuditoria, IncidenteBaneo, Ingreso

logger = logging.getLogger("infra_camera_state")


@dataclass(slots=True)
class IncidenteActivoResumen:
    """Resumen serializable de un incidente activo que afecta a una cámara."""

    id: int
    ticket_asociado: str | None
    servicio_protegido_id: str
    ruta_protegida_id: int | None
    fecha_inicio: str | None
    motivo: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ticket_asociado": self.ticket_asociado,
            "servicio_protegido_id": self.servicio_protegido_id,
            "ruta_protegida_id": self.ruta_protegida_id,
            "fecha_inicio": self.fecha_inicio,
            "motivo": self.motivo,
        }


@dataclass(slots=True)
class CamaraEstadoContexto:
    """Contexto operativo del estado de una cámara."""

    camara_id: int
    estado_actual: CamaraEstado
    estado_sugerido: CamaraEstado
    tiene_baneo_activo: bool
    tiene_ingreso_activo: bool
    inconsistente: bool
    incidentes_activos: list[IncidenteActivoResumen]
    ticket_baneo: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "camara_id": self.camara_id,
            "estado_actual": self.estado_actual.value,
            "estado_sugerido": self.estado_sugerido.value,
            "tiene_baneo_activo": self.tiene_baneo_activo,
            "tiene_ingreso_activo": self.tiene_ingreso_activo,
            "inconsistente": self.inconsistente,
            "incidentes_activos": [incidente.to_dict() for incidente in self.incidentes_activos],
            "ticket_baneo": self.ticket_baneo,
        }


@dataclass(slots=True)
class ActualizacionEstadoResultado:
    """Resultado de un override manual del estado de una cámara."""

    success: bool
    camara_id: int | None = None
    error: str | None = None
    changed: bool = False
    audit_id: int | None = None
    contexto: CamaraEstadoContexto | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "camara_id": self.camara_id,
            "error": self.error,
            "changed": self.changed,
            "audit_id": self.audit_id,
            "contexto": self.contexto.to_dict() if self.contexto else None,
        }


def _collect_servicios_y_rutas(camara: Camara) -> tuple[set[str], set[int]]:
    servicios_ids: set[str] = set()
    rutas_ids: set[int] = set()

    for empalme in camara.empalmes:
        for ruta in empalme.rutas:
            rutas_ids.add(ruta.id)
            if ruta.servicio and ruta.servicio.servicio_id:
                servicios_ids.add(ruta.servicio.servicio_id)

    return servicios_ids, rutas_ids


def _incidente_afecta_camara(
    incidente: IncidenteBaneo,
    servicios_ids: set[str],
    rutas_ids: set[int],
) -> bool:
    if incidente.servicio_protegido_id not in servicios_ids:
        return False
    if incidente.ruta_protegida_id is None:
        return True
    return incidente.ruta_protegida_id in rutas_ids


def _estado_sugerido(
    estado_actual: CamaraEstado,
    tiene_baneo_activo: bool,
    tiene_ingreso_activo: bool,
) -> CamaraEstado:
    if tiene_baneo_activo:
        return CamaraEstado.BANEADA
    if estado_actual == CamaraEstado.DETECTADA:
        return CamaraEstado.DETECTADA
    if tiene_ingreso_activo:
        return CamaraEstado.OCUPADA
    return CamaraEstado.LIBRE


def get_camara_estado_contexto(session: Session, camara_id: int) -> CamaraEstadoContexto | None:
    """Obtiene el contexto de estado de una cámara."""
    camara = session.query(Camara).filter(Camara.id == camara_id).first()
    if not camara:
        return None

    servicios_ids, rutas_ids = _collect_servicios_y_rutas(camara)
    incidentes_activos_db: list[IncidenteBaneo] = []
    if servicios_ids:
        candidatos = (
            session.query(IncidenteBaneo)
            .filter(
                IncidenteBaneo.activo == True,
                IncidenteBaneo.servicio_protegido_id.in_(sorted(servicios_ids)),
            )
            .order_by(IncidenteBaneo.fecha_inicio.desc())
            .all()
        )
        incidentes_activos_db = [
            incidente for incidente in candidatos if _incidente_afecta_camara(incidente, servicios_ids, rutas_ids)
        ]

    tiene_ingreso_activo = (
        session.query(Ingreso.id)
        .filter(
            Ingreso.camara_id == camara.id,
            Ingreso.fecha_fin == None,  # noqa: E711
        )
        .first()
        is not None
    )

    estado_actual = camara.estado or CamaraEstado.LIBRE
    tiene_baneo_activo = len(incidentes_activos_db) > 0
    estado_sugerido = _estado_sugerido(estado_actual, tiene_baneo_activo, tiene_ingreso_activo)
    incidentes_activos = [
        IncidenteActivoResumen(
            id=incidente.id,
            ticket_asociado=incidente.ticket_asociado,
            servicio_protegido_id=incidente.servicio_protegido_id,
            ruta_protegida_id=incidente.ruta_protegida_id,
            fecha_inicio=incidente.fecha_inicio.isoformat() if incidente.fecha_inicio else None,
            motivo=incidente.motivo,
        )
        for incidente in incidentes_activos_db
    ]

    ticket_baneo = next(
        (incidente.ticket_asociado for incidente in incidentes_activos if incidente.ticket_asociado),
        None,
    )

    return CamaraEstadoContexto(
        camara_id=camara.id,
        estado_actual=estado_actual,
        estado_sugerido=estado_sugerido,
        tiene_baneo_activo=tiene_baneo_activo,
        tiene_ingreso_activo=tiene_ingreso_activo,
        inconsistente=estado_actual != estado_sugerido,
        incidentes_activos=incidentes_activos,
        ticket_baneo=ticket_baneo,
    )


def override_camara_estado_manual(
    session: Session,
    camara_id: int,
    nuevo_estado: CamaraEstado,
    *,
    usuario: str,
    motivo: str,
) -> ActualizacionEstadoResultado:
    """Aplica un override manual sobre el estado de una cámara y lo audita."""
    camara = session.query(Camara).filter(Camara.id == camara_id).first()
    if not camara:
        return ActualizacionEstadoResultado(success=False, error="Cámara no encontrada")

    contexto_actual = get_camara_estado_contexto(session, camara_id)
    if contexto_actual is None:
        return ActualizacionEstadoResultado(success=False, error="No se pudo obtener el contexto de la cámara")

    if camara.estado == nuevo_estado:
        return ActualizacionEstadoResultado(
            success=True,
            camara_id=camara.id,
            changed=False,
            contexto=contexto_actual,
        )

    auditoria = CamaraEstadoAuditoria(
        camara_id=camara.id,
        usuario=usuario,
        motivo=motivo,
        estado_anterior=camara.estado,
        estado_nuevo=nuevo_estado,
        estado_sugerido=contexto_actual.estado_sugerido,
        incidentes_activos=[incidente.id for incidente in contexto_actual.incidentes_activos],
    )
    session.add(auditoria)

    camara.estado = nuevo_estado
    camara.last_update = datetime.now(timezone.utc)
    session.flush()

    logger.info(
        "action=override_camara_estado camara_id=%d usuario=%s estado_anterior=%s estado_nuevo=%s incidentes_activos=%d",
        camara.id,
        usuario,
        contexto_actual.estado_actual.value,
        nuevo_estado.value,
        len(contexto_actual.incidentes_activos),
    )

    return ActualizacionEstadoResultado(
        success=True,
        camara_id=camara.id,
        changed=True,
        audit_id=auditoria.id,
        contexto=get_camara_estado_contexto(session, camara.id),
    )


def obtener_ultimo_motivo_baneo_manual(session: Session, camara_id: int) -> str | None:
    """Retorna el motivo del último cambio manual de estado a BANEADA para una cámara.

    Consulta ``app.camaras_estado_auditoria`` ordenando por ``created_at DESC``
    y retorna el campo ``motivo`` del registro más reciente cuyo ``estado_nuevo``
    sea ``BANEADA``.  Si no existe ningún registro, retorna ``None``.
    """
    registro = (
        session.query(CamaraEstadoAuditoria.motivo)
        .filter(
            CamaraEstadoAuditoria.camara_id == camara_id,
            CamaraEstadoAuditoria.estado_nuevo == CamaraEstado.BANEADA,
        )
        .order_by(CamaraEstadoAuditoria.created_at.desc())
        .first()
    )
    return registro[0] if registro else None


__all__ = [
    "ActualizacionEstadoResultado",
    "CamaraEstadoContexto",
    "IncidenteActivoResumen",
    "get_camara_estado_contexto",
    "obtener_ultimo_motivo_baneo_manual",
    "override_camara_estado_manual",
]