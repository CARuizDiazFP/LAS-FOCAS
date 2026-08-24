# Nombre de archivo: camara_estado_service.py
# Ubicación de archivo: core/services/camara_estado_service.py
# Descripción: Servicio para contextualizar y auditar overrides manuales del estado de cámaras

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any

from sqlalchemy.orm import Session

from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado, CamaraEstadoAuditoria, IncidenteBaneo, Ingreso

logger = logging.getLogger("infra_camera_state")

# Mapa de estado Cámara -> CromoBotella: el `CHECK` de `cromo_botellas` sólo admite
# LIBRE/OCUPADA/BANEADA/NO_OPERATIVA (Cromo no tiene equivalente de DETECTADA/PENDIENTE_REVISION,
# workflows exclusivos del legado). Misma tabla que usa `scripts/cromo_backfill_camara_padre.py`
# para la carga inicial — vive acá porque `aplicar_estado_a_grupo` (abajo) también la necesita para
# mantener sincronizadas las Botellas Cromo en cada cambio de estado real, no sólo en el backfill.
MAPEO_ESTADO_CROMO: dict[CamaraEstado, CamaraEstado] = {
    CamaraEstado.LIBRE: CamaraEstado.LIBRE,
    CamaraEstado.OCUPADA: CamaraEstado.OCUPADA,
    CamaraEstado.BANEADA: CamaraEstado.BANEADA,
    CamaraEstado.NO_OPERATIVA: CamaraEstado.NO_OPERATIVA,
    CamaraEstado.DETECTADA: CamaraEstado.OCUPADA,
    CamaraEstado.PENDIENTE_REVISION: CamaraEstado.NO_OPERATIVA,
}


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


def miembros_del_grupo(camara: Camara) -> list[Camara]:
    """Cámara + todas sus Botellas hermanas (cascada completa bidireccional, Etapa Cámara/Botella).

    Si `camara` es una Botella (`camara_padre_id` seteado), se resuelve primero su cámara padre y se
    devuelve el grupo completo (padre + todas sus botellas, incluida `camara` misma)."""
    raiz = camara.camara_padre or camara
    return [raiz, *raiz.botellas]


def _collect_servicios_y_rutas(camara: Camara) -> tuple[set[str], set[int]]:
    """Servicios/rutas que tocan cualquier empalme del GRUPO (cámara + todas sus botellas) — no sólo
    los de `camara` directamente, para que el baneo/ingreso de una botella se refleje en la
    visibilidad de toda la cámara y viceversa."""
    servicios_ids: set[str] = set()
    rutas_ids: set[int] = set()

    for miembro in miembros_del_grupo(camara):
        for empalme in miembro.empalmes:
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


def _estado_sugerido(tiene_baneo_activo: bool, tiene_ingreso_activo: bool) -> CamaraEstado:
    """Ya no preserva `DETECTADA` (retirado del sistema, 2026-08-11 — el estado operable de
    Cámara/Botella se redujo a LIBRE/OCUPADA/BANEADA/NO_OPERATIVA, ver
    `scripts/retirar_estado_detectada.py`). Una fila legado que todavía tuviera `DETECTADA` cae al
    mismo cálculo que cualquier otro estado retirado: baneo activo gana, sino ingreso activo, sino
    LIBRE — nunca se preserva un estado fuera del vocabulario vigente."""
    if tiene_baneo_activo:
        return CamaraEstado.BANEADA
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

    ids_grupo = [miembro.id for miembro in miembros_del_grupo(camara)]
    tiene_ingreso_activo = (
        session.query(Ingreso.id)
        .filter(
            Ingreso.camara_id.in_(ids_grupo),
            Ingreso.fecha_fin == None,  # noqa: E711
        )
        .first()
        is not None
    )

    estado_actual = camara.estado or CamaraEstado.LIBRE
    tiene_baneo_activo = len(incidentes_activos_db) > 0
    estado_sugerido = _estado_sugerido(tiene_baneo_activo, tiene_ingreso_activo)
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


def aplicar_estado_a_grupo(
    session: Session,
    camara: Camara,
    nuevo_estado: CamaraEstado,
    *,
    usuario: str,
    motivo: str,
    estado_sugerido: CamaraEstado | None = None,
    incidentes_activos_ids: list[int] | None = None,
) -> list[CamaraEstadoAuditoria]:
    """Aplica `nuevo_estado` a `camara` Y a TODO su grupo (cámara padre + todas las botellas
    hermanas) — cascada completa bidireccional (Etapa Cámara/Botella): banear cualquier botella banea
    también a la cámara y a sus hermanas; banear la cámara banea a todas sus botellas.

    Es el único lugar del código que debe escribir `Camara.estado` directamente.
    `override_camara_estado_manual` (este mismo archivo, usado por el override admin/import Excel) y
    `create_ban`/`lift_ban` (`core/services/protection_service.py`, el "Protocolo de Protección")
    llaman a esta función en vez de asignar `camara.estado = X` a mano — así CUALQUIER camino de
    escritura (protección por servicio, override manual, código futuro) queda con la cascada correcta
    sin tener que auditar cada punto de escritura por separado. Sin esto, banear una botella por Excel
    o por el modal admin de un click deja a su cámara padre mostrándose libre mientras la botella
    hermana está inaccesible — el hueco de seguridad de campo real que motivó este diseño.

    Registra una fila de auditoría (`CamaraEstadoAuditoria`) por cada miembro efectivamente
    modificado (estado distinto al que ya tenía) — sólo la fila del miembro `camara` (el objetivo
    directo de la acción) lleva `estado_sugerido`/`incidentes_activos_ids`, si se pasan; esos campos
    describen el contexto de la acción original, no de sus hermanas.

    Devuelve las filas de auditoría creadas (una por miembro modificado, puede ser lista vacía si el
    grupo entero ya estaba en `nuevo_estado`).

    **Propaga a `CromoBotella` vinculada** (2026-08-12, cierra un gap real encontrado en producción:
    295 `CromoBotella` quedaron con `estado='OCUPADA'`/`'BANEADA'` mucho después de que su Cámara
    padre volviera a `LIBRE` — porque `CromoBotella.estado` era una foto fijada sólo al momento del
    backfill, y ningún cambio posterior de `Camara.estado` la tocaba). Cada miembro efectivamente
    modificado del grupo actualiza también sus `CromoBotella` propias (`camara_id`), vía
    `MAPEO_ESTADO_CROMO` — así un baneo/liberación real deja sincronizadas ambas tablas sin
    necesidad de una corrida manual de resync.
    """
    ahora = datetime.now(timezone.utc)
    auditorias: list[CamaraEstadoAuditoria] = []
    ids_miembros_modificados: list[int] = []

    for miembro in miembros_del_grupo(camara):
        if miembro.estado == nuevo_estado:
            continue
        es_objetivo_directo = miembro.id == camara.id
        auditoria = CamaraEstadoAuditoria(
            camara_id=miembro.id,
            usuario=usuario,
            motivo=motivo,
            estado_anterior=miembro.estado,
            estado_nuevo=nuevo_estado,
            estado_sugerido=estado_sugerido if es_objetivo_directo else None,
            incidentes_activos=incidentes_activos_ids if es_objetivo_directo else None,
        )
        session.add(auditoria)
        auditorias.append(auditoria)
        miembro.estado = nuevo_estado
        miembro.last_update = ahora
        ids_miembros_modificados.append(miembro.id)

    if auditorias:
        session.flush()
        logger.info(
            "action=aplicar_estado_a_grupo camara_id=%d nuevo_estado=%s usuario=%s miembros_modificados=%s",
            camara.id,
            nuevo_estado.value,
            usuario,
            [a.camara_id for a in auditorias],
        )
        estado_cromo = MAPEO_ESTADO_CROMO[nuevo_estado]
        cromo_actualizadas = (
            session.query(CromoBotella)
            .filter(CromoBotella.camara_id.in_(ids_miembros_modificados))
            .update({CromoBotella.estado: estado_cromo}, synchronize_session=False)
        )
        if cromo_actualizadas:
            logger.info(
                "action=aplicar_estado_a_grupo evento=cromo_botella_sincronizada estado_cromo=%s filas=%s",
                estado_cromo.value,
                cromo_actualizadas,
            )

    return auditorias


def override_camara_estado_manual(
    session: Session,
    camara_id: int,
    nuevo_estado: CamaraEstado,
    *,
    usuario: str,
    motivo: str,
) -> ActualizacionEstadoResultado:
    """Aplica un override manual sobre el estado de una cámara (y su grupo Cámara/Botella completo —
    ver `aplicar_estado_a_grupo`) y lo audita."""
    camara = session.query(Camara).filter(Camara.id == camara_id).first()
    if not camara:
        return ActualizacionEstadoResultado(success=False, error="Cámara no encontrada")

    contexto_actual = get_camara_estado_contexto(session, camara_id)
    if contexto_actual is None:
        return ActualizacionEstadoResultado(success=False, error="No se pudo obtener el contexto de la cámara")

    if all(m.estado == nuevo_estado for m in miembros_del_grupo(camara)):
        return ActualizacionEstadoResultado(
            success=True,
            camara_id=camara.id,
            changed=False,
            contexto=contexto_actual,
        )

    auditorias = aplicar_estado_a_grupo(
        session,
        camara,
        nuevo_estado,
        usuario=usuario,
        motivo=motivo,
        estado_sugerido=contexto_actual.estado_sugerido,
        incidentes_activos_ids=[incidente.id for incidente in contexto_actual.incidentes_activos],
    )
    audit_id_directo = next((a.id for a in auditorias if a.camara_id == camara.id), None)

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
        audit_id=audit_id_directo,
        contexto=get_camara_estado_contexto(session, camara.id),
    )


def obtener_ultima_transicion_a_baneada(session: Session, camara_id: int) -> CamaraEstadoAuditoria | None:
    """Última fila de auditoría que transicionó `camara_id` A estado BANEADA (la más reciente).

    Hallazgo real (QA de cascada, 2026-08-10): `lift_ban` restauraba TODO el grupo a LIBRE/OCUPADA
    sin considerar que (a) el estado previo a ser baneado pudo ser DETECTADA, no LIBRE, y (b) un
    miembro pudo quedar BANEADA por un baneo independiente (override manual o herencia del backfill)
    anterior al incidente que se está levantando, sin ningún `IncidenteBaneo` que lo respalde — por lo
    que `_camara_tiene_otro_baneo_activo` (que sólo mira `IncidenteBaneo`) no lo detecta. Esta consulta
    permite reconstruir ambos casos a partir de la única fuente de verdad histórica: la auditoría.
    """
    return (
        session.query(CamaraEstadoAuditoria)
        .filter(
            CamaraEstadoAuditoria.camara_id == camara_id,
            CamaraEstadoAuditoria.estado_nuevo == CamaraEstado.BANEADA,
        )
        .order_by(CamaraEstadoAuditoria.created_at.desc())
        .first()
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
    "aplicar_estado_a_grupo",
    "get_camara_estado_contexto",
    "miembros_del_grupo",
    "obtener_ultima_transicion_a_baneada",
    "obtener_ultimo_motivo_baneo_manual",
    "override_camara_estado_manual",
]