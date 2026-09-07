# Nombre de archivo: inventario.py
# Ubicación de archivo: core/services/cromo/inventario.py
# Descripción: Inventario navegable (búsqueda + paginación) sobre el inventario Cromo ya ingerido (Etapa 8b)

"""Resuelve "listame/buscame cables", distinto de `verificador.py` ("qué servicios pasan por
*este* cable puntual"). Sólo lectura sobre las tablas `app.cromo_*` ya pobladas por la ingesta."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(slots=True)
class CableInventario:
    n_id: int
    nombre: Optional[str]
    capacidad: Optional[str]
    capacidad_pelos: Optional[int]
    jerarquia: Optional[str]
    propietario: Optional[str]
    extremo_a_nombre: Optional[str]
    extremo_b_nombre: Optional[str]
    vigente: bool
    cantidad_servicios: int


@dataclass(slots=True)
class ResultadoBusquedaCables:
    total: int
    limit: int
    offset: int
    cables: list[CableInventario]


# CAST(...) explícito: sin él, cuando los 4 parámetros son NULL a la vez (sin ningún filtro puesto),
# asyncpg no puede inferir su tipo en la primera preparación del statement y tira
# `AmbiguousParameterError: could not determine data type of parameter $1` — hallazgo real al probar
# el inventario sin filtros contra el contenedor real (Etapa 8b). El atajo `:param::tipo` de Postgres
# no sirve acá: SQLAlchemy interpreta mal el `::` pegado al bind parameter (`:param` seguido de `:`).
#
# El filtro `servicio` usa `c.n_id IN (subquery)` **sin correlacionar** con `c` (Etapa 9) — no
# `EXISTS (... WHERE p.cable_n_id = c.n_id)`. Este WHERE se evalúa dos veces por request (COUNT +
# SELECT paginado) sobre las 30.000+ filas candidatas, antes de LIMIT/OFFSET. Un EXISTS correlacionado
# obliga a Postgres a re-ejecutar el join pelos⋈match⋈servicios una vez por fila candidata; al no
# correlacionar, Postgres puede resolverlo como "hashed subplan": el join corre una sola vez por
# statement (arma un set de cable_n_id en memoria), y cada fila hace un lookup O(1). No es el mismo
# patrón que el subselect correlacionado de `cantidad_servicios` de abajo — ese sí es correcto porque
# corre sólo sobre las ≤200 filas ya paginadas, no sobre las candidatas antes de paginar.
# `extremo_a_nombre`/`extremo_b_nombre` desnormalizados en `cromo_cables` vienen de `at.34`/`at.37` del
# payload de Cromo — hallazgo real (Etapa 9c, contra `lasfocasdev-postgres`): `at.37` NUNCA existe
# (0/32.782 cables), Cromo manda AMBOS nombres concatenados en el único atributo `at.34`
# ("LEGACY_A: dirección_A  LEGACY_B: dirección_B"). El JOIN a `cromo_botellas` por `extremo_a_n_id`/
# `extremo_b_n_id` sí da el nombre real y ya separado de cada botella (14.049 cables recuperables sólo
# para extremo B). `COALESCE` cae al valor crudo de `cromo_cables` únicamente si la botella todavía no
# bajó (referencia colgada, mismo criterio tolerante que `verificador.py`).
#
# Un extremo puede terminar en una ODF (`app.cromo_odfs`, clase 69) en vez de una Botella — tabla
# separada desde el submódulo ODFs (2026-08-28), que no existía cuando se escribió el JOIN de arriba.
# Bug real encontrado con datos de dev: 3.447 cables con extremo A y 3.695 con extremo B resuelven a
# una ODF, no a una Botella — sin este segundo JOIN, `ba`/`bb` da NULL, el nombre crudo también suele
# venir vacío (Cromo no lo manda para ODFs), y el extremo se muestra en blanco/"—" en el frontend.
_FILTROS_SQL = """
    WHERE (CAST(:q AS text) IS NULL OR c.nombre ILIKE CAST(:q AS text))
      AND (CAST(:jerarquia AS text) IS NULL OR c.jerarquia ILIKE CAST(:jerarquia AS text))
      AND (CAST(:propietario AS text) IS NULL OR c.propietario ILIKE CAST(:propietario AS text))
      AND (CAST(:vigente AS boolean) IS NULL OR c.vigente = CAST(:vigente AS boolean))
      AND (CAST(:n_id AS bigint) IS NULL OR c.n_id = CAST(:n_id AS bigint))
      AND (
        CAST(:botella AS text) IS NULL
        OR COALESCE(ba.nombre, c.extremo_a_nombre) ILIKE CAST(:botella AS text)
        OR COALESCE(bb.nombre, c.extremo_b_nombre) ILIKE CAST(:botella AS text)
      )
      AND (
        CAST(:servicio AS text) IS NULL
        OR c.n_id IN (
            SELECT p.cable_n_id
            FROM app.cromo_pelos p
            JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
            JOIN app.servicios s ON s.id = m.servicio_id
            WHERE s.servicio_id ILIKE CAST(:servicio AS text)
               OR s.numero_primer_servicio ILIKE CAST(:servicio AS text)
        )
      )
"""

_JOIN_EXTREMOS_SQL = """
    LEFT JOIN app.cromo_botellas ba ON ba.n_id = c.extremo_a_n_id
    LEFT JOIN app.cromo_botellas bb ON bb.n_id = c.extremo_b_n_id
    LEFT JOIN app.cromo_odfs oa ON oa.n_id = c.extremo_a_n_id
    LEFT JOIN app.cromo_odfs ob ON ob.n_id = c.extremo_b_n_id
"""

_SQL_CONTAR = text(f"SELECT count(*) FROM app.cromo_cables c {_JOIN_EXTREMOS_SQL} {_FILTROS_SQL}")

_SQL_BUSCAR = text(
    f"""
    SELECT
        c.n_id, c.nombre, c.capacidad, c.capacidad_pelos, c.jerarquia, c.propietario,
        COALESCE(ba.nombre, oa.nombre, c.extremo_a_nombre) AS extremo_a_nombre,
        COALESCE(bb.nombre, ob.nombre, c.extremo_b_nombre) AS extremo_b_nombre,
        c.vigente,
        (
            SELECT count(DISTINCT m.servicio_id)
            FROM app.cromo_pelos p
            JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
            WHERE p.cable_n_id = c.n_id AND m.servicio_id IS NOT NULL
        ) AS cantidad_servicios
    FROM app.cromo_cables c
    {_JOIN_EXTREMOS_SQL}
    {_FILTROS_SQL}
    ORDER BY c.nombre NULLS LAST, c.n_id
    LIMIT :limit OFFSET :offset
    """
)


async def buscar_cables(
    sesion: AsyncSession,
    *,
    q: Optional[str] = None,
    jerarquia: Optional[str] = None,
    propietario: Optional[str] = None,
    vigente: Optional[bool] = None,
    n_id: Optional[int] = None,
    botella: Optional[str] = None,
    servicio: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> ResultadoBusquedaCables:
    """Búsqueda paginada de cables. `q`/`jerarquia`/`propietario`/`botella`/`servicio` son `ILIKE`
    parcial (o `IN` sobre subquery en el caso de `servicio`); `vigente`/`n_id` exacto.

    `jerarquia` es `ILIKE`, no exacto, a propósito: los valores reales observados (Etapa 8b, contra
    `lasfocasdev-postgres`) son mucho más variados que los tres documentados originalmente
    ("Acceso"/"Troncal"/"Subtroncal") — aparecen también "Distribución", "Cruzada/Patchcord",
    "PatchCord", "Bajada", "Troncal LD", "No indicado" y vacío. Forzar match exacto desde un input
    libre sería frágil; parcial es más tolerante sin perder precisión (nadie escribe "Troncal" para
    buscar "Troncal LD" por accidente, pero si lo hace, es una ambigüedad real del dato, no del filtro.

    `botella` matchea contra el nombre real de la botella de cada extremo (JOIN a `cromo_botellas` por
    `extremo_a_n_id`/`extremo_b_n_id`, con fallback a los `extremo_a_nombre`/`extremo_b_nombre` crudos
    de `cromo_cables` si la botella todavía no bajó) — ver comentario sobre `at.34`/`at.37` arriba de
    `_FILTROS_SQL`. `servicio` (Etapa 9) matchea contra `servicio_id`/`numero_primer_servicio` de
    `app.servicios`, alcanzado vía `cromo_pelos`+`cromo_servicio_match`; ver el comentario en
    `_FILTROS_SQL` sobre por qué es un `IN` no correlacionado.

    El conteo de servicios es por `servicio_id` distinto matcheado en cualquiera de los pelos del
    cable (vía `cromo_servicio_match`) — mismo join que ya usa `verificador.servicios_por_cable`.
    """
    params = {
        "q": f"%{q.strip()}%" if q and q.strip() else None,
        "jerarquia": f"%{jerarquia.strip()}%" if jerarquia and jerarquia.strip() else None,
        "propietario": f"%{propietario.strip()}%" if propietario and propietario.strip() else None,
        "vigente": vigente,
        "n_id": n_id,
        "botella": f"%{botella.strip()}%" if botella and botella.strip() else None,
        "servicio": f"%{servicio.strip()}%" if servicio and servicio.strip() else None,
    }

    total = (await sesion.execute(_SQL_CONTAR, params)).scalar_one()
    filas = (
        await sesion.execute(_SQL_BUSCAR, {**params, "limit": limit, "offset": offset})
    ).all()

    cables = [
        CableInventario(
            n_id=fila[0],
            nombre=fila[1],
            capacidad=fila[2],
            capacidad_pelos=fila[3],
            jerarquia=fila[4],
            propietario=fila[5],
            extremo_a_nombre=fila[6],
            extremo_b_nombre=fila[7],
            vigente=fila[8],
            cantidad_servicios=fila[9],
        )
        for fila in filas
    ]
    return ResultadoBusquedaCables(total=total, limit=limit, offset=offset, cables=cables)


__all__ = ["CableInventario", "ResultadoBusquedaCables", "buscar_cables"]
