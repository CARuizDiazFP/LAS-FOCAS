# Nombre de archivo: detalle.py
# Ubicación de archivo: core/services/cromo/detalle.py
# Descripción: Detalle jerárquico de UN cable (tubos/buffers → pelos → servicio matcheado), sin N+1

"""Resuelve "mostrame la jerarquía completa de este cable" (extremos, tubos/buffers y sus pelos, con
el servicio matcheado de cada pelo si existe) — distinto de `inventario.py` (listar/buscar cables) y
de `verificador.py` (qué servicios pasan por *este* cable, sin exponer tubos/pelos individuales).
Sólo lectura sobre las tablas `app.cromo_*` ya pobladas por la ingesta."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from core.services.cromo.verificador import ObjetoNoEncontrado, ServicioEncontrado


@dataclass(slots=True)
class PeloDetalle:
    n_id: int
    tubo_n_id: int
    numero_pelo: Optional[str]
    orden: Optional[int]
    color: Optional[str]
    tipo_asociacion: str
    servicio_raw: Optional[str]
    servicio_numero: Optional[str]
    vigente: bool
    # Verificación manual de campo (migración 20260825_01) — sin poblador automático todavía, ver
    # docstring de esa migración. `None` en toda fila hasta que exista un proceso que los setee.
    verificable: Optional[bool] = None
    status: Optional[str] = None
    fecha_hora_status: Optional[datetime] = None
    # Normalmente 0 o 1 — `cromo_servicio_match` no tiene restricción de unicidad por pelo (sólo por
    # (pelo_n_id, servicio_numero)), así que en teoría un pelo podría matchear más de un número.
    servicios: list[ServicioEncontrado] = field(default_factory=list)


@dataclass(slots=True)
class TuboDetalle:
    n_id: int
    orden: Optional[int]
    nombre_color: Optional[str]
    vigente: Optional[bool]  # None si es referencia colgada (ver tiene_fila_propia)
    tiene_fila_propia: bool  # False = el tubo sólo se conoce porque algún pelo lo referencia
    pelos: list[PeloDetalle] = field(default_factory=list)


@dataclass(slots=True)
class DetalleCable:
    n_id: int
    nombre: Optional[str]
    capacidad: Optional[str]
    capacidad_pelos: Optional[int]
    jerarquia: Optional[str]
    propietario: Optional[str]
    tendido: Optional[str]
    distancia_geo: Optional[Decimal]
    distancia_real: Optional[Decimal]
    id_legacy: Optional[str]
    notas: Optional[str]
    extremo_a_n_id: Optional[int]
    extremo_a_clase: Optional[int]
    extremo_a_legacy: Optional[str]
    extremo_a_nombre: Optional[str]
    extremo_b_n_id: Optional[int]
    extremo_b_clase: Optional[int]
    extremo_b_legacy: Optional[str]
    extremo_b_nombre: Optional[str]
    vigente: bool
    tubos: list[TuboDetalle] = field(default_factory=list)


# extremo_a_nombre/extremo_b_nombre vía JOIN a cromo_botellas, no las columnas crudas de cromo_cables
# (at.34/at.37 del payload Cromo) — hallazgo real (Etapa 9c): at.37 nunca existe, Cromo manda ambos
# nombres concatenados en at.34 únicamente. Ver el comentario extenso en inventario.py.
_SQL_CABLE_DETALLE = text(
    """
    SELECT c.n_id, c.nombre, c.capacidad, c.capacidad_pelos, c.jerarquia, c.propietario, c.tendido,
           c.distancia_geo, c.distancia_real, c.id_legacy, c.notas,
           c.extremo_a_n_id, c.extremo_a_clase, c.extremo_a_legacy,
           COALESCE(ba.nombre, c.extremo_a_nombre) AS extremo_a_nombre,
           c.extremo_b_n_id, c.extremo_b_clase, c.extremo_b_legacy,
           COALESCE(bb.nombre, c.extremo_b_nombre) AS extremo_b_nombre,
           c.vigente
    FROM app.cromo_cables c
    LEFT JOIN app.cromo_botellas ba ON ba.n_id = c.extremo_a_n_id
    LEFT JOIN app.cromo_botellas bb ON bb.n_id = c.extremo_b_n_id
    WHERE c.n_id = :n_id
    """
)

_SQL_TUBOS_DE_CABLE = text(
    """
    SELECT n_id, orden, nombre_color, vigente
    FROM app.cromo_tubos
    WHERE cable_n_id = :cable_n_id
    ORDER BY orden NULLS LAST, n_id
    """
)

# Una sola query para TODOS los pelos del cable (no una por tubo): evita N+1. LEFT JOIN doble porque
# no todo pelo tiene match, y no todo match tiene servicio_id resuelto (`m.servicio_id IS NULL` es un
# estado válido — número parseado que no matcheó contra `app.servicios`). Si un pelo tiene más de un
# match, aparece una fila por cada uno; se agrupa por `p.n_id` en Python.
_SQL_PELOS_DE_CABLE = text(
    """
    SELECT
        p.n_id, p.tubo_n_id, p.numero_pelo, p.orden, p.color, p.tipo_asociacion,
        p.servicio_raw, p.servicio_numero, p.vigente,
        s.id, s.servicio_id, s.numero_primer_servicio, s.nombre_cliente, s.cliente,
        s.estado_servicio, s.categoria, s.tipo_servicio, m.servicio_numero, m.metodo,
        p.verificable, p.status, p.fecha_hora_status
    FROM app.cromo_pelos p
    LEFT JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
    LEFT JOIN app.servicios s ON s.id = m.servicio_id
    WHERE p.cable_n_id = :cable_n_id
    ORDER BY p.orden NULLS LAST, p.n_id
    """
)


# Misma forma que _SQL_PELOS_DE_CABLE, acotada a un único tubo/buffer — para el comando de Slack
# "Info cable <nombre> B<N>" (modules/slack_baneo_notifier/cable_info.py), que necesita el listado
# completo de pelos de UN buffer puntual, no del cable entero.
_SQL_PELOS_DE_TUBO = text(
    """
    SELECT
        p.n_id, p.tubo_n_id, p.numero_pelo, p.orden, p.color, p.tipo_asociacion,
        p.servicio_raw, p.servicio_numero, p.vigente,
        s.id, s.servicio_id, s.numero_primer_servicio, s.nombre_cliente, s.cliente,
        s.estado_servicio, s.categoria, s.tipo_servicio, m.servicio_numero, m.metodo,
        p.verificable, p.status, p.fecha_hora_status
    FROM app.cromo_pelos p
    LEFT JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
    LEFT JOIN app.servicios s ON s.id = m.servicio_id
    WHERE p.tubo_n_id = :tubo_n_id
    ORDER BY p.orden NULLS LAST, p.n_id
    """
)


def _fila_a_servicio_opcional(fila: tuple, pelo_n_id: int) -> Optional[ServicioEncontrado]:
    if fila[0] is None:  # s.id
        return None
    (
        servicio_id,
        servicio_id_externo,
        numero_primer_servicio,
        nombre_cliente,
        cliente,
        estado_servicio,
        categoria,
        tipo_servicio,
        servicio_numero_match,
        metodo,
    ) = fila
    return ServicioEncontrado(
        servicio_id=servicio_id,
        servicio_id_externo=servicio_id_externo,
        numero_primer_servicio=numero_primer_servicio,
        nombre_cliente=nombre_cliente,
        cliente=cliente,
        estado_servicio=estado_servicio,
        categoria=categoria,
        tipo_servicio=tipo_servicio,
        pelo_n_id=pelo_n_id,
        servicio_numero_match=servicio_numero_match,
        metodo=metodo,
    )


async def obtener_detalle_cable(sesion: AsyncSession, n_id: int) -> DetalleCable:
    """Detalle jerárquico completo de un cable: metadata + tubos (ordenados) + pelos de cada tubo
    (ordenados) + servicio matcheado de cada pelo, si existe.

    Sólo 3 queries sin importar cuántos tubos/pelos tenga el cable (nunca N+1): cable, tubos del
    cable, y TODOS los pelos del cable con su match+servicio ya resuelto por LEFT JOIN — se agrupan en
    Python por `tubo_n_id`, no una query por tubo.

    Tolerante a referencia colgada, mismo criterio que `verificador.servicios_por_cable`: si la fila
    propia del cable no existe pero hay tubos o pelos que lo referencian, no es "no encontrado" — sólo
    la metadata del cable queda en `None`. Un tubo referenciado por un pelo pero sin fila propia en
    `cromo_tubos` aparece igual en la respuesta (`tiene_fila_propia=False`, `orden`/`nombre_color`/
    `vigente` en `None`) en vez de perderse silenciosamente.
    """
    cable = (await sesion.execute(_SQL_CABLE_DETALLE, {"n_id": n_id})).first()
    filas_tubos = (await sesion.execute(_SQL_TUBOS_DE_CABLE, {"cable_n_id": n_id})).all()
    filas_pelos = (await sesion.execute(_SQL_PELOS_DE_CABLE, {"cable_n_id": n_id})).all()

    if cable is None and not filas_tubos and not filas_pelos:
        raise ObjetoNoEncontrado(f"No existe un cable con n_id={n_id} en el inventario ingerido.")

    pelos_index: dict[int, PeloDetalle] = {}
    pelos_por_tubo: dict[int, list[PeloDetalle]] = {}
    for fila in filas_pelos:
        pelo_n_id = fila[0]
        pelo = pelos_index.get(pelo_n_id)
        if pelo is None:
            pelo = PeloDetalle(
                n_id=pelo_n_id,
                tubo_n_id=fila[1],
                numero_pelo=fila[2],
                orden=fila[3],
                color=fila[4],
                tipo_asociacion=fila[5],
                servicio_raw=fila[6],
                servicio_numero=fila[7],
                vigente=fila[8],
                verificable=fila[19],
                status=fila[20],
                fecha_hora_status=fila[21],
            )
            pelos_index[pelo_n_id] = pelo
            pelos_por_tubo.setdefault(pelo.tubo_n_id, []).append(pelo)
        servicio = _fila_a_servicio_opcional(fila[9:19], pelo_n_id)
        if servicio is not None:
            pelo.servicios.append(servicio)

    tubos: list[TuboDetalle] = []
    tubos_vistos: set[int] = set()
    for fila in filas_tubos:
        tubo_n_id = fila[0]
        tubos_vistos.add(tubo_n_id)
        tubos.append(
            TuboDetalle(
                n_id=tubo_n_id,
                orden=fila[1],
                nombre_color=fila[2],
                vigente=fila[3],
                tiene_fila_propia=True,
                pelos=pelos_por_tubo.get(tubo_n_id, []),
            )
        )
    for tubo_n_id, pelos in pelos_por_tubo.items():
        if tubo_n_id in tubos_vistos:
            continue
        tubos.append(
            TuboDetalle(
                n_id=tubo_n_id,
                orden=None,
                nombre_color=None,
                vigente=None,
                tiene_fila_propia=False,
                pelos=pelos,
            )
        )
    tubos.sort(key=lambda t: (t.orden is None, t.orden, t.n_id))

    return DetalleCable(
        n_id=n_id,
        nombre=cable[1] if cable else None,
        capacidad=cable[2] if cable else None,
        capacidad_pelos=cable[3] if cable else None,
        jerarquia=cable[4] if cable else None,
        propietario=cable[5] if cable else None,
        tendido=cable[6] if cable else None,
        distancia_geo=cable[7] if cable else None,
        distancia_real=cable[8] if cable else None,
        id_legacy=cable[9] if cable else None,
        notas=cable[10] if cable else None,
        extremo_a_n_id=cable[11] if cable else None,
        extremo_a_clase=cable[12] if cable else None,
        extremo_a_legacy=cable[13] if cable else None,
        extremo_a_nombre=cable[14] if cable else None,
        extremo_b_n_id=cable[15] if cable else None,
        extremo_b_clase=cable[16] if cable else None,
        extremo_b_legacy=cable[17] if cable else None,
        extremo_b_nombre=cable[18] if cable else None,
        vigente=cable[19] if cable else False,
        tubos=tubos,
    )


def pelos_de_tubo_sync(session: Session, tubo_n_id: int) -> list[PeloDetalle]:
    """Listado completo de los pelos de UN tubo/buffer (matcheados o no, con `servicio_raw` crudo
    siempre visible) — versión síncrona y acotada a un tubo de la misma query/agrupación que usa
    `obtener_detalle_cable` para el cable entero. Para el comando de Slack "Info cable <nombre> B<N>"
    (`modules/slack_baneo_notifier/cable_info.py`), que corre dentro de un callback síncrono de Slack
    Bolt y sólo necesita un buffer puntual, no el árbol completo del cable."""
    filas = session.execute(_SQL_PELOS_DE_TUBO, {"tubo_n_id": tubo_n_id}).all()

    pelos_index: dict[int, PeloDetalle] = {}
    pelos: list[PeloDetalle] = []
    for fila in filas:
        pelo_n_id = fila[0]
        pelo = pelos_index.get(pelo_n_id)
        if pelo is None:
            pelo = PeloDetalle(
                n_id=pelo_n_id,
                tubo_n_id=fila[1],
                numero_pelo=fila[2],
                orden=fila[3],
                color=fila[4],
                tipo_asociacion=fila[5],
                servicio_raw=fila[6],
                servicio_numero=fila[7],
                vigente=fila[8],
                verificable=fila[19],
                status=fila[20],
                fecha_hora_status=fila[21],
            )
            pelos_index[pelo_n_id] = pelo
            pelos.append(pelo)
        servicio = _fila_a_servicio_opcional(fila[9:19], pelo_n_id)
        if servicio is not None:
            pelo.servicios.append(servicio)

    return pelos


__all__ = ["PeloDetalle", "TuboDetalle", "DetalleCable", "obtener_detalle_cable", "pelos_de_tubo_sync"]
