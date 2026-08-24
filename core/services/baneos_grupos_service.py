# Nombre de archivo: baneos_grupos_service.py
# Ubicación de archivo: core/services/baneos_grupos_service.py
# Descripción: Listado y liberación masiva de grupos baneados (Cámara padre + Botellas), agrupados por raíz

"""Listado de grupos baneados (Cámara padre raíz + sus Botellas legado/Cromo) para el panel de
administración, y la única acción masiva nueva del ticket: liberar (desbanear) varios grupos de una
— NO hay ningún borrado físico en este servicio ni en el resto del plan, el usuario aclaró
explícitamente que "Borrar" del pedido original es la misma acción que "Cambiar estado a Libre".

Reusa `get_camara_estado_contexto` (`core/services/camara_estado_service.py`) sólo para lo que
genuinamente describe: `tiene_baneo_activo`/`incidentes_activos`/`estado_sugerido`/`ticket_baneo`
— la trazabilidad real de si hay un incidente del Protocolo de Protección detrás del baneo, y a qué
estado debería volver el grupo si se libera. Deliberadamente NO reusa `contexto.inconsistente` para
nada de este módulo: ese campo compara `estado_actual` contra `estado_sugerido` (ver
`camara_estado_service.py`), y es `True` para casi cualquier baneo hecho por
`override_camara_estado_manual` sin `IncidenteBaneo` detrás — exactamente cómo banea la ingesta Excel
y la asociación manual (nunca crean `IncidenteBaneo`). Usarlo acá como badge de "grupo inconsistente"
sería ruido engañoso, no una señal real. `estado_mixto` (este módulo) es un concepto distinto y
nuevo: una botella hija en un estado distinto al de su raíz — posible legado de datos pre-fix de la
cascada (`override_camara_estado_manual`) o de un `lift_ban` parcial.

`liberar_grupos_masivo` recibe una `Session` ya abierta (no gestiona su propia `SessionLocal`) —
igual que `asociar_nombres_a_camara`: el endpoint que la llama abre/commitea/cierra una sola
transacción para todo el lote. La liberación es no-destructiva y barata (a diferencia de
merge/apropiar masivo, que usan sesión-por-item porque un fallo parcial ahí es irreversible), así que
no necesita ese patrón.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import logging
from typing import Any

from sqlalchemy.orm import Session

from core.services.camara_estado_service import get_camara_estado_contexto, override_camara_estado_manual
from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado, CamaraEstadoAuditoria

logger = logging.getLogger("baneos_grupos")


def _estado_str(estado: CamaraEstado | None) -> str:
    """Mismo fallback que el resto del código (`_serialize_camara_response` en `web/app/main.py`):
    una fila sin `estado` seteado se muestra como LIBRE, nunca como `None`/error."""
    return estado.value if estado else CamaraEstado.LIBRE.value


@dataclass(slots=True)
class BotellaBaneadaResumen:
    """Resumen de una Botella (legado o Cromo) hija de un grupo baneado."""

    origen: str  # "legado" | "cromo"
    id: int  # Camara.id (legado) o CromoBotella.n_id (cromo)
    nombre: str
    estado: str

    def to_dict(self) -> dict[str, Any]:
        return {"origen": self.origen, "id": self.id, "nombre": self.nombre, "estado": self.estado}


@dataclass(slots=True)
class GrupoBaneado:
    """Un grupo (Cámara padre raíz baneada + sus Botellas) para el listado administrativo."""

    camara_id: int
    nombre: str
    direccion: str | None
    fontine_id: str | None
    estado: str
    botellas: list[BotellaBaneadaResumen]
    botellas_count: int
    motivo: str | None
    usuario: str | None
    fecha: str | None  # ISO — último CamaraEstadoAuditoria con estado_nuevo=BANEADA para esta raíz
    tiene_baneo_activo: bool
    ticket_baneo: str | None
    incidentes_activos_ids: list[int]
    estado_mixto: bool  # alguna botella hija en un estado distinto al de la raíz
    puede_liberar: bool  # = not tiene_baneo_activo

    def to_dict(self) -> dict[str, Any]:
        return {
            "camara_id": self.camara_id,
            "nombre": self.nombre,
            "direccion": self.direccion,
            "fontine_id": self.fontine_id,
            "estado": self.estado,
            "botellas": [botella.to_dict() for botella in self.botellas],
            "botellas_count": self.botellas_count,
            "motivo": self.motivo,
            "usuario": self.usuario,
            "fecha": self.fecha,
            "tiene_baneo_activo": self.tiene_baneo_activo,
            "ticket_baneo": self.ticket_baneo,
            "incidentes_activos_ids": self.incidentes_activos_ids,
            "estado_mixto": self.estado_mixto,
            "puede_liberar": self.puede_liberar,
        }


@dataclass(slots=True)
class ResultadoGruposBaneados:
    total: int
    grupos: list[GrupoBaneado]

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "grupos": [grupo.to_dict() for grupo in self.grupos]}


@dataclass(slots=True)
class ResultadoLiberarGrupo:
    camara_id: int
    liberado: bool
    estado_final: str | None
    razon_omision: str | None  # None si liberado=True; ej. "bloqueado_por_incidente" si no

    def to_dict(self) -> dict[str, Any]:
        return {
            "camara_id": self.camara_id,
            "liberado": self.liberado,
            "estado_final": self.estado_final,
            "razon_omision": self.razon_omision,
        }


@dataclass(slots=True)
class ResultadoAccionGrupos:
    total_solicitados: int
    liberados: int
    omitidos: int
    detalle: list[ResultadoLiberarGrupo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_solicitados": self.total_solicitados,
            "liberados": self.liberados,
            "omitidos": self.omitidos,
            "detalle": [item.to_dict() for item in self.detalle],
        }


def listar_grupos_baneados(
    session: Session,
    *,
    q: str | None = None,
    limit: int | None = 25,
    offset: int = 0,
    incluir_contexto: bool = True,
) -> ResultadoGruposBaneados:
    """Lista Cámaras raíz baneadas (`camara_padre_id IS NULL`, `estado=BANEADA`) con sus Botellas
    hijas (legado + Cromo), paginadas por nombre.

    Sin N+1: como máximo 4 queries de listado (raíces, botellas legado, botellas Cromo, auditoría)
    sin importar cuántos grupos haya en la página, más una query de contexto por raíz sólo si
    `incluir_contexto=True` (`get_camara_estado_contexto` no tiene, hoy, una variante batch).

    `limit=None` no pagina — trae TODAS las raíces que matcheen el filtro (lo usa el reporte Excel
    completo de la Tarea 8, que no puede perder grupos por paginación). Con `limit=None` se ignora
    `offset` (nunca tendría sentido: no hay `.limit()` que "correr").
    """
    query = session.query(Camara).filter(
        Camara.camara_padre_id.is_(None),
        Camara.estado == CamaraEstado.BANEADA,
    )
    q_norm = q.strip() if q else ""
    if q_norm:
        query = query.filter(Camara.nombre.ilike(f"%{q_norm}%"))

    total = query.count()

    query = query.order_by(Camara.nombre)
    if limit is not None:
        query = query.offset(offset).limit(limit)
    raices = query.all()

    if not raices:
        return ResultadoGruposBaneados(total=total, grupos=[])

    ids_raices = [raiz.id for raiz in raices]

    legado_por_raiz: dict[int, list[Camara]] = defaultdict(list)
    for botella in session.query(Camara).filter(Camara.camara_padre_id.in_(ids_raices)).all():
        legado_por_raiz[botella.camara_padre_id].append(botella)

    cromo_por_raiz: dict[int, list[CromoBotella]] = defaultdict(list)
    for cromo_botella in session.query(CromoBotella).filter(CromoBotella.camara_id.in_(ids_raices)).all():
        cromo_por_raiz[cromo_botella.camara_id].append(cromo_botella)

    auditoria_por_raiz: dict[int, CamaraEstadoAuditoria] = {}
    auditorias = (
        session.query(CamaraEstadoAuditoria)
        .filter(
            CamaraEstadoAuditoria.camara_id.in_(ids_raices),
            CamaraEstadoAuditoria.estado_nuevo == CamaraEstado.BANEADA,
        )
        .order_by(CamaraEstadoAuditoria.created_at.desc())
        .all()
    )
    for auditoria in auditorias:
        # Ya viene ordenada por created_at desc — la primera fila vista para cada camara_id es la
        # más reciente, las siguientes (si hay más de una) se ignoran.
        auditoria_por_raiz.setdefault(auditoria.camara_id, auditoria)

    grupos: list[GrupoBaneado] = []
    for raiz in raices:
        estado_raiz = _estado_str(raiz.estado)

        botellas: list[BotellaBaneadaResumen] = [
            BotellaBaneadaResumen(origen="legado", id=botella.id, nombre=botella.nombre, estado=_estado_str(botella.estado))
            for botella in legado_por_raiz.get(raiz.id, [])
        ] + [
            BotellaBaneadaResumen(origen="cromo", id=cb.n_id, nombre=cb.nombre or "", estado=_estado_str(cb.estado))
            for cb in cromo_por_raiz.get(raiz.id, [])
        ]
        estado_mixto = any(botella.estado != estado_raiz for botella in botellas)

        auditoria = auditoria_por_raiz.get(raiz.id)
        motivo = auditoria.motivo if auditoria else None
        usuario = auditoria.usuario if auditoria else None
        fecha = auditoria.created_at.isoformat() if auditoria and auditoria.created_at else None

        tiene_baneo_activo = False
        ticket_baneo: str | None = None
        incidentes_activos_ids: list[int] = []
        puede_liberar = True

        if incluir_contexto:
            contexto = get_camara_estado_contexto(session, raiz.id)
            if contexto is not None:
                tiene_baneo_activo = contexto.tiene_baneo_activo
                ticket_baneo = contexto.ticket_baneo
                incidentes_activos_ids = [incidente.id for incidente in contexto.incidentes_activos]
                puede_liberar = not tiene_baneo_activo

        grupos.append(
            GrupoBaneado(
                camara_id=raiz.id,
                nombre=raiz.nombre,
                direccion=raiz.direccion,
                fontine_id=raiz.fontine_id,
                estado=estado_raiz,
                botellas=botellas,
                botellas_count=len(botellas),
                motivo=motivo,
                usuario=usuario,
                fecha=fecha,
                tiene_baneo_activo=tiene_baneo_activo,
                ticket_baneo=ticket_baneo,
                incidentes_activos_ids=incidentes_activos_ids,
                estado_mixto=estado_mixto,
                puede_liberar=puede_liberar,
            )
        )

    return ResultadoGruposBaneados(total=total, grupos=grupos)


def liberar_grupos_masivo(
    session: Session,
    camara_ids: list[int],
    *,
    usuario: str,
    motivo: str,
    forzar: bool = False,
) -> ResultadoAccionGrupos:
    """Libera (desbanea) varios grupos de una — la única acción masiva nueva del ticket, NO un
    borrado físico.

    Por cada `camara_id` recibido se resuelve su grupo (raíz = `camara_padre_id` si es una Botella,
    o el mismo id si ya es la raíz) y se libera una sola vez por raíz, aunque el caller haya pasado
    más de un id del mismo grupo (dedup silencioso — la Botella/raíz "de más" ni siquiera genera una
    fila en `detalle`, ver `ResultadoAccionGrupos.total_solicitados` vs. `len(detalle)`).

    Guard de incidente activo: si `get_camara_estado_contexto(...).tiene_baneo_activo` es `True` y
    `forzar=False`, el grupo se omite con `razon_omision="bloqueado_por_incidente"` y
    `override_camara_estado_manual` NUNCA se llama para ese grupo — evita levantar un baneo que el
    Protocolo de Protección todavía necesita.

    Con `forzar=True` sobre un grupo con incidente activo, el destino es SIEMPRE `LIBRE` — nunca
    `estado_sugerido` (que devolvería `BANEADA` de nuevo mientras el incidente siga activo, un
    no-op disfrazado de "forzado"). Sin incidente activo, el destino es `estado_sugerido` (puede ser
    `OCUPADA` si hay un ingreso activo, no `LIBRE` hardcodeado).
    """
    detalle: list[ResultadoLiberarGrupo] = []
    raices_procesadas: set[int] = set()

    for camara_id in camara_ids:
        camara = session.query(Camara).filter(Camara.id == camara_id).first()
        if camara is None:
            detalle.append(
                ResultadoLiberarGrupo(
                    camara_id=camara_id, liberado=False, estado_final=None, razon_omision="camara_no_encontrada"
                )
            )
            continue

        raiz_id = camara.camara_padre_id or camara.id
        if raiz_id in raices_procesadas:
            continue  # ya se resolvió este grupo por otro id del mismo request
        raices_procesadas.add(raiz_id)

        contexto = get_camara_estado_contexto(session, raiz_id)
        if contexto is None:
            detalle.append(
                ResultadoLiberarGrupo(
                    camara_id=raiz_id, liberado=False, estado_final=None, razon_omision="camara_no_encontrada"
                )
            )
            continue

        if contexto.tiene_baneo_activo and not forzar:
            detalle.append(
                ResultadoLiberarGrupo(
                    camara_id=raiz_id, liberado=False, estado_final=None, razon_omision="bloqueado_por_incidente"
                )
            )
            continue

        destino = contexto.estado_sugerido if not contexto.tiene_baneo_activo else CamaraEstado.LIBRE
        resultado = override_camara_estado_manual(session, raiz_id, destino, usuario=usuario, motivo=motivo)
        detalle.append(
            ResultadoLiberarGrupo(
                camara_id=raiz_id,
                liberado=resultado.success,
                estado_final=destino.value if resultado.success else None,
                razon_omision=None if resultado.success else (resultado.error or "error_desconocido"),
            )
        )

    liberados = sum(1 for item in detalle if item.liberado)
    logger.info(
        "action=liberar_grupos_masivo usuario=%s solicitados=%d liberados=%d omitidos=%d forzar=%s",
        usuario,
        len(camara_ids),
        liberados,
        len(detalle) - liberados,
        forzar,
    )
    return ResultadoAccionGrupos(
        total_solicitados=len(camara_ids),
        liberados=liberados,
        omitidos=len(detalle) - liberados,
        detalle=detalle,
    )


__all__ = [
    "BotellaBaneadaResumen",
    "GrupoBaneado",
    "ResultadoAccionGrupos",
    "ResultadoGruposBaneados",
    "ResultadoLiberarGrupo",
    "liberar_grupos_masivo",
    "listar_grupos_baneados",
]
