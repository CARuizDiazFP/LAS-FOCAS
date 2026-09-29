# Nombre de archivo: cable_consultas.py
# Ubicación de archivo: core/services/cable_consultas.py
# Descripción: Consultas por nombre de cable para la API v1: resolución del cable, servicios que pasan y pelos por buffer

"""Cable → Servicios / Pelos por buffer, para integraciones interáreas (`/api/v1/cables/...`).

Sólo lectura sobre el inventario Cromo ya ingerido. Reutiliza las mismas funciones que sirven al
Verificador y a los comandos de Slack "Servicios <cable>" / "Info cable X BN", para que las tres
superficies respondan lo mismo:

- servicios únicos: `verificador.servicios_unicos_por_cable` (un servicio por fila aunque ocupe
  varios pelos);
- pelos por buffer: `detalle.obtener_detalle_cable` (3 queries, sin N+1).

El número de buffer se expone 1-indexado, como lo cuenta el técnico y como lo usan los comandos de
Slack (`cromo_tubos.orden` arranca en 0 en los datos reales).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.detalle import obtener_detalle_cable
from core.services.cromo.verificador import servicios_unicos_por_cable


@dataclass(frozen=True)
class CableIdentificado:
    n_id: int
    nombre: Optional[str]
    capacidad: Optional[str]
    extremo_a: Optional[str]
    extremo_b: Optional[str]


# Mismo criterio que `modules/slack_baneo_notifier/cable_info.py::buscar_cable_por_n_id_o_nombre` y
# que `web/app/main.py::_resolver_cable_por_texto` (que la API no puede importar: `web/app` y
# `api/app` son apps FastAPI distintas): n_id exacto si el texto es puramente numérico, si no nombre
# exacto case-insensitive. Sólo cables vigentes. Los extremos se nombran como en `detalle.py`
# (Botella u ODF, lo que corresponda).
_SQL_RESOLVER_CABLE_POR_N_ID = text(
    """
    SELECT c.n_id, c.nombre, c.capacidad,
           COALESCE(ba.nombre, oa.nombre, c.extremo_a_nombre),
           COALESCE(bb.nombre, ob.nombre, c.extremo_b_nombre)
    FROM app.cromo_cables c
    LEFT JOIN app.cromo_botellas ba ON ba.n_id = c.extremo_a_n_id
    LEFT JOIN app.cromo_botellas bb ON bb.n_id = c.extremo_b_n_id
    LEFT JOIN app.cromo_odfs oa ON oa.n_id = c.extremo_a_n_id
    LEFT JOIN app.cromo_odfs ob ON ob.n_id = c.extremo_b_n_id
    WHERE c.vigente AND c.n_id = :n_id
    """
)
_SQL_RESOLVER_CABLE_POR_NOMBRE = text(
    """
    SELECT c.n_id, c.nombre, c.capacidad,
           COALESCE(ba.nombre, oa.nombre, c.extremo_a_nombre),
           COALESCE(bb.nombre, ob.nombre, c.extremo_b_nombre)
    FROM app.cromo_cables c
    LEFT JOIN app.cromo_botellas ba ON ba.n_id = c.extremo_a_n_id
    LEFT JOIN app.cromo_botellas bb ON bb.n_id = c.extremo_b_n_id
    LEFT JOIN app.cromo_odfs oa ON oa.n_id = c.extremo_a_n_id
    LEFT JOIN app.cromo_odfs ob ON ob.n_id = c.extremo_b_n_id
    WHERE c.vigente AND lower(c.nombre) = lower(:nombre)
    ORDER BY c.n_id
    """
)


async def resolver_cable(session: AsyncSession, texto: str) -> list[CableIdentificado]:
    """0 = no existe, 1 = resuelto, 2+ = ambiguo (hay nombres duplicados reales, ej. "F-LEM-11-A").

    Un texto numérico se prueba primero como `cable_id` y, si no existe, como nombre: hay cables
    vigentes con nombre puramente numérico (3 en dev el 2026-09-29) que de otro modo serían
    inalcanzables por nombre.
    """

    limpio = texto.strip()
    if not limpio:
        return []
    filas = []
    if limpio.isdigit():
        filas = (await session.execute(_SQL_RESOLVER_CABLE_POR_N_ID, {"n_id": int(limpio)})).all()
    if not filas:
        filas = (await session.execute(_SQL_RESOLVER_CABLE_POR_NOMBRE, {"nombre": limpio})).all()
    return [CableIdentificado(*fila) for fila in filas]


# ── Servicios de un cable ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ServicioEnCable:
    servicio_id: str  # ID vigente
    cliente: Optional[str]
    estado_servicio: Optional[str]
    tipo_servicio: Optional[str]
    cantidad_pelos: int
    buffers: list[int]  # 1-indexados, los que ocupa en este cable


_SQL_BUFFER_DE_PELOS = text(
    """
    SELECT p.n_id, t.orden
    FROM app.cromo_pelos p
    LEFT JOIN app.cromo_tubos t ON t.n_id = p.tubo_n_id
    WHERE p.cable_n_id = :cable_n_id
    """
)


async def servicios_de_cable(session: AsyncSession, cable_n_id: int) -> list[ServicioEnCable]:
    resultado = await servicios_unicos_por_cable(session, cable_n_id)
    orden_por_pelo = dict((await session.execute(_SQL_BUFFER_DE_PELOS, {"cable_n_id": cable_n_id})).all())
    servicios = []
    for s in resultado.servicios:
        buffers = sorted({orden_por_pelo[p] + 1 for p in s.pelos_n_ids if orden_por_pelo.get(p) is not None})
        servicios.append(
            ServicioEnCable(
                servicio_id=s.servicio_id_externo,
                cliente=s.nombre_cliente or s.cliente,
                estado_servicio=s.estado_servicio,
                tipo_servicio=s.tipo_servicio,
                cantidad_pelos=s.cantidad_pelos,
                buffers=buffers,
            )
        )
    servicios.sort(key=lambda s: (s.buffers[0] if s.buffers else 10**6, s.servicio_id))
    return servicios


# ── Pelos por buffer ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PeloEnBuffer:
    numero: Optional[str]
    color: Optional[str]
    estado: str  # "ocupado" | "libre"
    servicio_id: Optional[str]  # ID vigente del servicio matcheado
    cliente: Optional[str]
    estado_servicio: Optional[str]
    descripcion: Optional[str]  # texto crudo de Cromo del pelo


@dataclass(frozen=True)
class BufferDeCable:
    numero: Optional[int]  # 1-indexado; None si el tubo sólo se conoce por referencia colgada
    color: Optional[str]
    pelos: list[PeloEnBuffer]


async def pelos_por_buffer(
    session: AsyncSession, cable_n_id: int, *, buffer: Optional[int] = None
) -> list[BufferDeCable]:
    """Pelos vigentes del cable agrupados por buffer, en el orden físico (buffer y pelo)."""

    detalle = await obtener_detalle_cable(session, cable_n_id)
    buffers: list[BufferDeCable] = []
    for tubo in detalle.tubos:
        if tubo.vigente is False:
            continue
        numero = tubo.orden + 1 if tubo.orden is not None else None
        if buffer is not None and numero != buffer:
            continue
        pelos = []
        for pelo in sorted(tubo.pelos, key=lambda p: (p.orden is None, p.orden, p.n_id)):
            if not pelo.vigente:
                continue
            s = pelo.servicios[0] if pelo.servicios else None
            pelos.append(
                PeloEnBuffer(
                    numero=pelo.numero_pelo,
                    color=pelo.color,
                    estado="ocupado" if s else "libre",
                    servicio_id=s.servicio_id_externo if s else None,
                    cliente=(s.nombre_cliente or s.cliente) if s else None,
                    estado_servicio=s.estado_servicio if s else None,
                    descripcion=pelo.servicio_raw,
                )
            )
        buffers.append(BufferDeCable(numero=numero, color=tubo.nombre_color, pelos=pelos))
    return buffers
