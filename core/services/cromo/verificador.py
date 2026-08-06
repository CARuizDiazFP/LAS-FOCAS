# Nombre de archivo: verificador.py
# Ubicación de archivo: core/services/cromo/verificador.py
# Descripción: Consultas de sólo lectura sobre el inventario Cromo ya ingerido — qué servicios pasan por un cable/tubo/botella

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ObjetoNoEncontrado(RuntimeError):
    """El cable/tubo/botella consultado no existe en el inventario ya ingerido."""


@dataclass(slots=True)
class ServicioEncontrado:
    """Un servicio de `app.servicios` alcanzado a través de un pelo con match (`cromo_servicio_match`)."""

    servicio_id: int
    servicio_id_externo: str
    numero_primer_servicio: Optional[str]
    nombre_cliente: Optional[str]
    cliente: Optional[str]
    estado_servicio: Optional[str]
    categoria: Optional[int]
    tipo_servicio: Optional[str]
    pelo_n_id: int
    servicio_numero_match: str
    metodo: str


@dataclass(slots=True)
class ResultadoCable:
    cable_n_id: int
    nombre: Optional[str]
    capacidad: Optional[str]
    extremo_a_nombre: Optional[str]
    extremo_b_nombre: Optional[str]
    servicios: list[ServicioEncontrado]


@dataclass(slots=True)
class ResultadoTubo:
    tubo_n_id: int
    cable_n_id: Optional[int]  # None si el tubo sólo se conoce por referencia colgada (sin fila propia)
    orden: Optional[int]
    nombre_color: Optional[str]
    servicios: list[ServicioEncontrado]


@dataclass(slots=True)
class ResultadoBotella:
    botella_n_id: int
    nombre: Optional[str]
    clase: Optional[int]  # None si la botella sólo se conoce por referencia colgada (sin fila propia)
    localidad: Optional[str]
    servicios: list[ServicioEncontrado]


# Columnas de `app.servicios` + `cromo_pelos`/`cromo_servicio_match` comunes a las tres consultas,
# en el mismo orden que espera `_fila_a_servicio` — evita repetir el SELECT completo tres veces.
_COLUMNAS_SERVICIO = """
    s.id, s.servicio_id, s.numero_primer_servicio, s.nombre_cliente, s.cliente,
    s.estado_servicio, s.categoria, s.tipo_servicio, p.n_id, m.servicio_numero, m.metodo
"""

_SQL_CABLE_POR_N_ID = text(
    "SELECT n_id, nombre, capacidad, extremo_a_nombre, extremo_b_nombre "
    "FROM app.cromo_cables WHERE n_id = :n_id"
)

# Un cable/tubo/botella puede tener servicios matcheados aunque su fila propia todavía no se haya
# ingerido — es la misma "referencia colgada" que audita la fase de reconciliación (REF_COLGADA):
# un tubo/pelo puede bajar en una página de la Fase 3 (dentro de una botella) mientras el cable al
# que pertenece todavía no bajó en su propia página de la Fase 2. Confirmado con datos reales: dos
# cables con servicio matcheado en sus pelos, sin fila en `cromo_cables` (ver docs/Doc Privada/
# ingesta_cromo.md §13.3). Por eso el chequeo de "no encontrado" no se apoya sólo en la fila propia.
_SQL_EXISTE_CABLE_POR_PELOS = text("SELECT 1 FROM app.cromo_pelos WHERE cable_n_id = :cable_n_id LIMIT 1")
_SQL_EXISTE_TUBO_POR_PELOS = text("SELECT 1 FROM app.cromo_pelos WHERE tubo_n_id = :tubo_n_id LIMIT 1")
_SQL_EXISTE_BOTELLA_POR_CABLES = text(
    "SELECT 1 FROM app.cromo_cables WHERE extremo_a_n_id = :botella_n_id OR extremo_b_n_id = :botella_n_id LIMIT 1"
)

_SQL_SERVICIOS_POR_CABLE = text(
    f"""
    SELECT DISTINCT {_COLUMNAS_SERVICIO}
    FROM app.cromo_pelos p
    JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
    JOIN app.servicios s ON s.id = m.servicio_id
    WHERE p.cable_n_id = :cable_n_id
    ORDER BY s.id
    """
)

_SQL_TUBO_POR_N_ID = text(
    "SELECT n_id, cable_n_id, orden, nombre_color FROM app.cromo_tubos WHERE n_id = :n_id"
)

_SQL_SERVICIOS_POR_TUBO = text(
    f"""
    SELECT DISTINCT {_COLUMNAS_SERVICIO}
    FROM app.cromo_pelos p
    JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
    JOIN app.servicios s ON s.id = m.servicio_id
    WHERE p.tubo_n_id = :tubo_n_id
    ORDER BY s.id
    """
)

_SQL_BOTELLA_POR_N_ID = text(
    "SELECT n_id, nombre, clase, localidad FROM app.cromo_botellas WHERE n_id = :n_id"
)

_SQL_SERVICIOS_POR_BOTELLA = text(
    f"""
    SELECT DISTINCT {_COLUMNAS_SERVICIO}
    FROM app.cromo_cables c
    JOIN app.cromo_pelos p ON p.cable_n_id = c.n_id
    JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
    JOIN app.servicios s ON s.id = m.servicio_id
    WHERE c.extremo_a_n_id = :botella_n_id OR c.extremo_b_n_id = :botella_n_id
    ORDER BY s.id
    """
)


def _fila_a_servicio(fila: tuple) -> ServicioEncontrado:
    (
        servicio_id,
        servicio_id_externo,
        numero_primer_servicio,
        nombre_cliente,
        cliente,
        estado_servicio,
        categoria,
        tipo_servicio,
        pelo_n_id,
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


async def servicios_por_cable(sesion: AsyncSession, cable_n_id: int) -> ResultadoCable:
    """Servicios que pasan por un cable entero (cualquiera de sus tubos/pelos).

    "No encontrado" se decide por si el `cable_n_id` aparece en algún lado (fila propia en
    `cromo_cables` o al menos un pelo que lo referencia) — no sólo por la fila propia, que puede
    faltar por una referencia colgada real (ver `_SQL_EXISTE_CABLE_POR_PELOS`).
    """
    cable = (await sesion.execute(_SQL_CABLE_POR_N_ID, {"n_id": cable_n_id})).first()
    filas = (await sesion.execute(_SQL_SERVICIOS_POR_CABLE, {"cable_n_id": cable_n_id})).all()

    if cable is None and not filas:
        existe = (await sesion.execute(_SQL_EXISTE_CABLE_POR_PELOS, {"cable_n_id": cable_n_id})).first()
        if existe is None:
            raise ObjetoNoEncontrado(f"No existe un cable con n_id={cable_n_id} en el inventario ingerido.")

    return ResultadoCable(
        cable_n_id=cable_n_id,
        nombre=cable[1] if cable else None,
        capacidad=cable[2] if cable else None,
        extremo_a_nombre=cable[3] if cable else None,
        extremo_b_nombre=cable[4] if cable else None,
        servicios=[_fila_a_servicio(f) for f in filas],
    )


async def servicios_por_tubo(sesion: AsyncSession, tubo_n_id: int) -> ResultadoTubo:
    """Servicios que pasan por un tubo/buffer específico dentro de un cable.

    Mismo criterio de "no encontrado" tolerante a referencias colgadas que `servicios_por_cable`.
    """
    tubo = (await sesion.execute(_SQL_TUBO_POR_N_ID, {"n_id": tubo_n_id})).first()
    filas = (await sesion.execute(_SQL_SERVICIOS_POR_TUBO, {"tubo_n_id": tubo_n_id})).all()

    if tubo is None and not filas:
        existe = (await sesion.execute(_SQL_EXISTE_TUBO_POR_PELOS, {"tubo_n_id": tubo_n_id})).first()
        if existe is None:
            raise ObjetoNoEncontrado(f"No existe un tubo con n_id={tubo_n_id} en el inventario ingerido.")

    return ResultadoTubo(
        tubo_n_id=tubo_n_id,
        cable_n_id=tubo[1] if tubo else None,
        orden=tubo[2] if tubo else None,
        nombre_color=tubo[3] if tubo else None,
        servicios=[_fila_a_servicio(f) for f in filas],
    )


async def servicios_por_botella(sesion: AsyncSession, botella_n_id: int) -> ResultadoBotella:
    """Servicios que pasan por los cables que tienen esta botella como uno de sus extremos.

    No sigue fusiones dentro de la botella (capítulo 8.2 del diseño lo deja para un "impacto de tocar
    una botella" más amplio, fuera de esta etapa) — sólo resuelve la pregunta literal "qué servicios
    pasan por esta botella" vía los cables que la usan como extremo A o B. Mismo criterio de "no
    encontrado" tolerante a referencias colgadas que `servicios_por_cable`.
    """
    botella = (await sesion.execute(_SQL_BOTELLA_POR_N_ID, {"n_id": botella_n_id})).first()
    filas = (await sesion.execute(_SQL_SERVICIOS_POR_BOTELLA, {"botella_n_id": botella_n_id})).all()

    if botella is None and not filas:
        existe = (await sesion.execute(_SQL_EXISTE_BOTELLA_POR_CABLES, {"botella_n_id": botella_n_id})).first()
        if existe is None:
            raise ObjetoNoEncontrado(f"No existe una botella con n_id={botella_n_id} en el inventario ingerido.")

    return ResultadoBotella(
        botella_n_id=botella_n_id,
        nombre=botella[1] if botella else None,
        clase=botella[2] if botella else None,
        localidad=botella[3] if botella else None,
        servicios=[_fila_a_servicio(f) for f in filas],
    )


__all__ = [
    "ObjetoNoEncontrado",
    "ServicioEncontrado",
    "ResultadoCable",
    "ResultadoTubo",
    "ResultadoBotella",
    "servicios_por_cable",
    "servicios_por_tubo",
    "servicios_por_botella",
]
