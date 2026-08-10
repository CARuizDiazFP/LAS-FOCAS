# Nombre de archivo: botellas_unificadas_service.py
# Ubicación de archivo: core/services/botellas_unificadas_service.py
# Descripción: Listado unificado de Botellas (Cromo + legado Infra/Baneos), sólo lectura, sin cruzar identidad entre ambas fuentes

"""Combina dos fuentes de datos sin relación real entre sí, ambas llamadas "Botella":

- `app.cromo_botellas` (mirror de sólo lectura de Cromo Red, sin campo de estado operativo ni FK de
  "padre" — Cromo no distingue Cámara/Poste/Botella como entidades separadas, ver
  `docs/infra.md` sección "Submódulo Botellas").
- `app.camaras` con `camara_padre_id` seteado (Botellas "legado" de la jerarquía Cámara→Botella del
  módulo Infra/Baneos, con estado operativo real).

Se combinan con una única query `UNION ALL` (mismo patrón que
`core/services/cromo/inventario.py::buscar_cables`: CTE reusado por COUNT y SELECT, `CAST(:param AS
tipo)` explícito para evitar `AmbiguousParameterError` de asyncpg cuando el filtro viene `NULL`) en vez
de dos queries (una async, una sync) combinadas con aritmética de paginación en Python — evita mezclar
sesiones sync+async dentro del mismo handler y evita lógica de "ventaneo" nueva y propensa a errores.

Cromo siempre ordena primero (`prioridad=0` vs `1`) — nunca se suprime ni fusiona una fila legado
aunque exista una Cromo con nombre similar, ambas quedan visibles con su origen. Un `n_id` de Cromo y un
`Camara.id` legado son espacios de ID independientes que pueden coincidir en valor sin ser la misma
fila — el llamador (frontend) debe tratar `(origen, id)` como la clave compuesta, nunca `id` solo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(slots=True)
class BotellaUnificada:
    origen: str  # "cromo" | "legado"
    id: int
    nombre: Optional[str]
    estado: Optional[str]  # siempre None para origen "cromo" — Cromo no trackea estado operativo


@dataclass(slots=True)
class ResultadoBusquedaBotellas:
    total: int
    limit: int
    offset: int
    botellas: list[BotellaUnificada]


_CTE_COMBINADO = """
    WITH combinado AS (
        SELECT
            'cromo'::text AS origen, cb.n_id AS id, cb.nombre AS nombre, NULL::text AS estado, 0 AS prioridad
        FROM app.cromo_botellas cb
        WHERE cb.vigente = true
          AND (
            CAST(:q AS text) IS NULL
            OR cb.nombre ILIKE CAST(:q AS text)
            OR cb.calle ILIKE CAST(:q AS text)
            OR cb.localidad ILIKE CAST(:q AS text)
          )
        UNION ALL
        SELECT
            'legado'::text AS origen, c.id AS id, c.nombre AS nombre, c.estado::text AS estado, 1 AS prioridad
        FROM app.camaras c
        WHERE c.camara_padre_id IS NOT NULL
          AND (CAST(:q AS text) IS NULL OR c.nombre ILIKE CAST(:q AS text))
    )
"""

_SQL_CONTAR = text(f"{_CTE_COMBINADO} SELECT count(*) FROM combinado")

_SQL_BUSCAR = text(
    f"""
    {_CTE_COMBINADO}
    SELECT origen, id, nombre, estado
    FROM combinado
    ORDER BY prioridad, nombre NULLS LAST, id
    LIMIT :limit OFFSET :offset
    """
)


async def buscar_botellas_unificadas(
    sesion: AsyncSession,
    *,
    q: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
) -> ResultadoBusquedaBotellas:
    """Búsqueda paginada sobre el listado unificado. `q` es `ILIKE` parcial contra nombre (Cromo
    también contra calle/localidad); vacío o `None` no filtra."""
    params = {"q": f"%{q.strip()}%" if q and q.strip() else None}

    total = (await sesion.execute(_SQL_CONTAR, params)).scalar_one()
    filas = (await sesion.execute(_SQL_BUSCAR, {**params, "limit": limit, "offset": offset})).all()

    botellas = [
        BotellaUnificada(origen=fila[0], id=fila[1], nombre=fila[2], estado=fila[3]) for fila in filas
    ]
    return ResultadoBusquedaBotellas(total=total, limit=limit, offset=offset, botellas=botellas)


__all__ = ["BotellaUnificada", "ResultadoBusquedaBotellas", "buscar_botellas_unificadas"]
