# Nombre de archivo: estado.py
# Ubicación de archivo: core/services/fo_monitor/estado.py
# Descripción: Lectura de resultados PRE/POST de una intervención y cálculo del semáforo por cable (compartido worker/web)

"""Estado consolidado de una intervención de FO Monitor.

- Último resultado por servicio y fase (orden `medido_at`, `id`): los reintentos y la
  reverificación se agregan como filas nuevas (append-only) y gana la más reciente.
- PRE válido: medido entre 15 min antes y 20 min después del ingreso (relevamiento Q28/Q78). Fuera
  de esa ventana el servicio queda sin línea base. Las intervenciones MANUAL no tienen ingreso:
  todo PRE es válido.
- POST efectivo: el más reciente entre POST y REVERIF (la reverificación confirma o desmiente una
  caída nueva antes de alertar).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from core.services.fo_monitor.semaforo import ResultadoSemaforo, calcular_semaforo
from db.models.fo_monitor import (
    FomonIntervencion,
    FomonIntervencionServicio,
    FomonReconocimiento,
    FomonResultado,
)

PRE_VALIDO_ANTES = timedelta(minutes=15)
PRE_VALIDO_DESPUES = timedelta(minutes=20)


@dataclass
class Medicion:
    estado: str
    medido_at: datetime
    extremo: Optional[str]
    motivo: Optional[str]
    consulta_id: int


@dataclass
class ServicioCable:
    servicio_pk: int
    servicio_id_externo: Optional[str]
    tipo_servicio: Optional[str]
    categoria: Optional[int]
    cliente: Optional[str]
    pre: Optional[Medicion] = None
    post: Optional[Medicion] = None
    reconocido: bool = False


@dataclass
class EstadoCable:
    cable_n_id: int
    nombre: Optional[str]
    clase: Optional[int]
    botella_n_id: Optional[int]
    es_objetivo: bool
    semaforo: ResultadoSemaforo
    servicios: list[ServicioCable] = field(default_factory=list)


def ultimos_por_fase(session: Session, intervencion_id: int) -> dict[str, dict[int, Medicion]]:
    filas = (
        session.query(FomonResultado)
        .filter(FomonResultado.intervencion_id == intervencion_id)
        .order_by(FomonResultado.medido_at, FomonResultado.id)
        .all()
    )
    salida: dict[str, dict[int, Medicion]] = {"PRE": {}, "POST": {}, "REVERIF": {}}
    for r in filas:
        salida[r.fase][r.servicio_pk] = Medicion(r.estado, r.medido_at, r.extremo, r.motivo, r.consulta_id)
    return salida


def pre_valido(intervencion: FomonIntervencion, medicion: Medicion) -> bool:
    if intervencion.origen == "MANUAL" or intervencion.fecha_ingreso is None:
        return True
    desde = intervencion.fecha_ingreso - PRE_VALIDO_ANTES
    hasta = intervencion.fecha_ingreso + PRE_VALIDO_DESPUES
    return desde <= medicion.medido_at <= hasta


def post_efectivo(por_fase: dict[str, dict[int, Medicion]]) -> dict[int, Medicion]:
    efectivo = dict(por_fase["POST"])
    for pk, m in por_fase["REVERIF"].items():
        previo = efectivo.get(pk)
        if previo is None or m.medido_at >= previo.medido_at:
            efectivo[pk] = m
    return efectivo


def estado_intervencion(session: Session, intervencion: FomonIntervencion) -> list[EstadoCable]:
    """Semáforo por cable. Mientras no haya POST, el color refleja el PRE (fase en curso)."""
    por_fase = ultimos_por_fase(session, intervencion.id)
    pre = {pk: m for pk, m in por_fase["PRE"].items() if pre_valido(intervencion, m)}
    # Una MANUAL cierra tras el PRE sin POST: CERRADA sola no implica fase POST (si no, todo quedaría
    # "sin dato"). Hay POST si hay resultados, si está en curso, o si cerró con egreso.
    hay_post = (
        bool(por_fase["POST"])
        or intervencion.estado == "POST_EN_CURSO"
        or (intervencion.estado == "CERRADA" and intervencion.fecha_egreso is not None)
    )
    post = post_efectivo(por_fase) if hay_post else None
    reconocidos = {
        r.servicio_pk
        for r in session.query(FomonReconocimiento.servicio_pk)
        .filter(FomonReconocimiento.intervencion_id == intervencion.id)
        .all()
    }
    todos_reconocidos = None in reconocidos  # reconocimiento sin servicio = toda la intervención

    filas = (
        session.query(FomonIntervencionServicio)
        .filter(FomonIntervencionServicio.intervencion_id == intervencion.id)
        .order_by(FomonIntervencionServicio.es_objetivo.desc(), FomonIntervencionServicio.cable_n_id)
        .all()
    )
    cables: dict[int, EstadoCable] = {}
    servicios_por_cable: dict[int, list[ServicioCable]] = {}
    for f in filas:
        if f.cable_n_id not in cables:
            cables[f.cable_n_id] = EstadoCable(
                cable_n_id=f.cable_n_id, nombre=f.cable_nombre, clase=f.cable_clase,
                botella_n_id=f.botella_n_id, es_objetivo=f.es_objetivo, semaforo=None,  # type: ignore[arg-type]
            )
            servicios_por_cable[f.cable_n_id] = []
        if f.servicio_pk is None:
            continue
        servicios_por_cable[f.cable_n_id].append(
            ServicioCable(
                servicio_pk=f.servicio_pk, servicio_id_externo=f.servicio_id_externo,
                tipo_servicio=f.tipo_servicio, categoria=f.categoria, cliente=f.cliente,
                pre=pre.get(f.servicio_pk), post=(post or {}).get(f.servicio_pk),
                reconocido=todos_reconocidos or f.servicio_pk in reconocidos,
            )
        )

    for cable_n_id, cable in cables.items():
        servicios = servicios_por_cable[cable_n_id]
        pks = [s.servicio_pk for s in servicios]
        cable.servicios = servicios
        cable.semaforo = calcular_semaforo(
            pks,
            {s.servicio_pk: s.pre.estado for s in servicios if s.pre},
            {s.servicio_pk: s.post.estado for s in servicios if s.post} if post is not None else None,
            reconocidos={s.servicio_pk for s in servicios if s.reconocido},
            sin_linea_base=intervencion.sin_linea_base,
        )
    return list(cables.values())
