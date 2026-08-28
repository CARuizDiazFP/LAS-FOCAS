# Nombre de archivo: odf_inventario.py
# Ubicación de archivo: core/services/cromo/odf_inventario.py
# Descripción: Inventario navegable (búsqueda + paginación) sobre el submódulo ODFs de Cromo ya ingerido (Etapa 4 del plan ODFs)

"""Resuelve "listame/buscame ODFs", mismo espíritu que `inventario.py` (equivalente para cables),
distinto de `verificador.py` ("qué servicios pasan por *este* ODF puntual"). Sólo lectura sobre
`app.cromo_odfs` ya poblada por la ingesta (Tareas 1-3 del plan)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(slots=True)
class OdfInventario:
    n_id: int
    nombre: Optional[str]
    tipo_elemento: str
    localidad: Optional[str]
    calle: Optional[str]
    altura: Optional[str]
    propietario: Optional[str]
    vigente: bool
    cantidad_cables_asociados: int
    cantidad_servicios: int


@dataclass(slots=True)
class ResultadoBusquedaOdfs:
    total: int
    limit: int
    offset: int
    odfs: list[OdfInventario]


# CAST(...) explícito por el mismo motivo real que ya documenta `inventario.py::_FILTROS_SQL`: sin
# él, cuando todos los filtros opcionales son NULL a la vez (sin ningún filtro puesto — el caso más
# común, "listame todos los ODFs"), asyncpg no puede inferir el tipo del parámetro en la primera
# preparación del statement y tira `AmbiguousParameterError: could not determine data type of
# parameter $1` — reproducido real contra `lasfocasdev-postgres` (127.0.0.1:5433) al escribir este
# módulo. El atajo `:param::tipo` pegado al bind no sirve (SQLAlchemy interpreta mal el `::` pegado);
# siempre `CAST(:param AS tipo)`.
#
# `servicio` atraviesa `cables_asociados` (JSONB, lista de n_ids de cable) → `cromo_pelos.cable_n_id`
# → `cromo_servicio_match` → `app.servicios`, mismo destino final que el filtro homónimo de
# `inventario.py` pero sin una columna de FK normalizada de la que partir (a diferencia de
# `cromo_pelos.cable_n_id`, acá no hay un `cromo_odf_cable` — decisión explícita del plan, ver brief
# de la Tarea 4). El EXISTS queda correlacionado a `o.cables_asociados` porque no hay forma de
# evitarlo con una columna JSONB por fila; a diferencia del `IN` no correlacionado de
# `inventario.py` (justificado ahí por 30.000+ cables candidatos), acá el volumen de ODFs es órdenes
# de magnitud menor (decenas/centenas, clase 69 de Cromo) — no vale la pena la complejidad de
# separar el subquery en uno no correlacionado sólo por rendimiento.
_FILTROS_SQL = """
    WHERE (CAST(:q AS text) IS NULL OR o.nombre ILIKE CAST(:q AS text))
      AND (CAST(:n_id AS bigint) IS NULL OR o.n_id = CAST(:n_id AS bigint))
      AND (CAST(:vigente AS boolean) IS NULL OR o.vigente = CAST(:vigente AS boolean))
      AND (CAST(:tipo_elemento AS text) IS NULL OR o.tipo_elemento = CAST(:tipo_elemento AS text))
      AND (
        CAST(:servicio AS text) IS NULL
        OR EXISTS (
            SELECT 1
            FROM app.cromo_pelos p
            JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
            JOIN app.servicios s ON s.id = m.servicio_id
            WHERE (s.servicio_id ILIKE CAST(:servicio AS text) OR s.numero_primer_servicio ILIKE CAST(:servicio AS text))
              AND p.cable_n_id IN (
                  SELECT (jsonb_array_elements_text(COALESCE(o.cables_asociados, '[]'::jsonb)))::bigint
              )
        )
      )
"""

_SQL_CONTAR = text(f"SELECT count(*) FROM app.cromo_odfs o {_FILTROS_SQL}")

# `cantidad_servicios` como subselect correlacionado, mismo patrón (y misma justificación de
# rendimiento) que `inventario.py::_SQL_BUSCAR`: corre sólo sobre los ≤200 ODFs ya paginados, no
# sobre las filas candidatas antes de paginar.
_SQL_BUSCAR = text(
    f"""
    SELECT
        o.n_id, o.nombre, o.tipo_elemento, o.localidad, o.calle, o.altura, o.propietario, o.vigente,
        o.cables_asociados,
        (
            SELECT count(DISTINCT m.servicio_id)
            FROM jsonb_array_elements_text(COALESCE(o.cables_asociados, '[]'::jsonb)) AS cable_id_texto
            JOIN app.cromo_pelos p ON p.cable_n_id = cable_id_texto::bigint
            JOIN app.cromo_servicio_match m ON m.pelo_n_id = p.n_id
            WHERE m.servicio_id IS NOT NULL
        ) AS cantidad_servicios
    FROM app.cromo_odfs o
    {_FILTROS_SQL}
    ORDER BY o.localidad NULLS LAST, o.calle NULLS LAST, o.altura NULLS LAST, o.nombre, o.n_id
    LIMIT :limit OFFSET :offset
    """
)


async def buscar_odfs(
    sesion: AsyncSession,
    *,
    q: Optional[str] = None,
    n_id: Optional[int] = None,
    vigente: Optional[bool] = None,
    tipo_elemento: Optional[str] = None,
    servicio: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> ResultadoBusquedaOdfs:
    """Búsqueda paginada de ODFs. `q`/`servicio` son `ILIKE`/`EXISTS` parcial; `n_id`/`vigente`/
    `tipo_elemento` exacto.

    Orden por defecto `localidad, calle, altura, nombre, n_id` (NULLS LAST en las tres primeras) —
    sustituye al agrupamiento por un ID de sitio que pedía el ticket original y que no existe en los
    datos reales de Cromo (ver docstring de `CromoOdf`): ODFs que comparten domicilio físico quedan
    adyacentes en el listado por este orden, sin necesitar una columna de sitio nueva.

    Dos queries fijas (COUNT + SELECT paginado), sin N+1 — `cantidad_servicios` se resuelve con un
    subselect correlacionado sobre las filas ya paginadas, mismo criterio que `inventario.buscar_cables`.
    """
    params = {
        "q": f"%{q.strip()}%" if q and q.strip() else None,
        "n_id": n_id,
        "vigente": vigente,
        "tipo_elemento": tipo_elemento.strip() if tipo_elemento and tipo_elemento.strip() else None,
        "servicio": f"%{servicio.strip()}%" if servicio and servicio.strip() else None,
    }

    total = (await sesion.execute(_SQL_CONTAR, params)).scalar_one()
    filas = (
        await sesion.execute(_SQL_BUSCAR, {**params, "limit": limit, "offset": offset})
    ).all()

    odfs = [
        OdfInventario(
            n_id=fila[0],
            nombre=fila[1],
            tipo_elemento=fila[2],
            localidad=fila[3],
            calle=fila[4],
            altura=fila[5],
            propietario=fila[6],
            vigente=fila[7],
            cantidad_cables_asociados=len(fila[8] or []),
            cantidad_servicios=fila[9],
        )
        for fila in filas
    ]
    return ResultadoBusquedaOdfs(total=total, limit=limit, offset=offset, odfs=odfs)


__all__ = ["OdfInventario", "ResultadoBusquedaOdfs", "buscar_odfs"]
