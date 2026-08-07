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
_FILTROS_SQL = """
    WHERE (CAST(:q AS text) IS NULL OR c.nombre ILIKE CAST(:q AS text))
      AND (CAST(:jerarquia AS text) IS NULL OR c.jerarquia ILIKE CAST(:jerarquia AS text))
      AND (CAST(:propietario AS text) IS NULL OR c.propietario ILIKE CAST(:propietario AS text))
      AND (CAST(:vigente AS boolean) IS NULL OR c.vigente = CAST(:vigente AS boolean))
"""

_SQL_CONTAR = text(f"SELECT count(*) FROM app.cromo_cables c {_FILTROS_SQL}")

_SQL_BUSCAR = text(
    f"""
    SELECT
        c.n_id, c.nombre, c.capacidad, c.capacidad_pelos, c.jerarquia, c.propietario,
        c.extremo_a_nombre, c.extremo_b_nombre, c.vigente,
        (
            SELECT count(DISTINCT m.servicio_id)
            FROM app.cromo_pelos p
            JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
            WHERE p.cable_n_id = c.n_id AND m.servicio_id IS NOT NULL
        ) AS cantidad_servicios
    FROM app.cromo_cables c
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
    limit: int = 50,
    offset: int = 0,
) -> ResultadoBusquedaCables:
    """Búsqueda paginada de cables. `q`/`jerarquia`/`propietario` son `ILIKE` parcial; `vigente` exacto.

    `jerarquia` es `ILIKE`, no exacto, a propósito: los valores reales observados (Etapa 8b, contra
    `lasfocasdev-postgres`) son mucho más variados que los tres documentados originalmente
    ("Acceso"/"Troncal"/"Subtroncal") — aparecen también "Distribución", "Cruzada/Patchcord",
    "PatchCord", "Bajada", "Troncal LD", "No indicado" y vacío. Forzar match exacto desde un input
    libre sería frágil; parcial es más tolerante sin perder precisión (nadie escribe "Troncal" para
    buscar "Troncal LD" por accidente, pero si lo hace, es una ambigüedad real del dato, no del filtro.

    El conteo de servicios es por `servicio_id` distinto matcheado en cualquiera de los pelos del
    cable (vía `cromo_servicio_match`) — mismo join que ya usa `verificador.servicios_por_cable`.
    """
    params = {
        "q": f"%{q.strip()}%" if q and q.strip() else None,
        "jerarquia": f"%{jerarquia.strip()}%" if jerarquia and jerarquia.strip() else None,
        "propietario": f"%{propietario.strip()}%" if propietario and propietario.strip() else None,
        "vigente": vigente,
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
