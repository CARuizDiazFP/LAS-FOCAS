# Nombre de archivo: pon_inventario.py
# Ubicación de archivo: core/services/cromo/pon_inventario.py
# Descripción: Inventario navegable (búsqueda + paginación) sobre cajas PON y rosetas de la red de
# acceso ya ingeridas

"""Resuelve "listame/buscame cajas PON o rosetas", mismo espíritu que `inventario.py` (cables) y
`odf_inventario.py` (ODFs). Sólo lectura sobre `app.cromo_pon_elementos`.

Cajas PON y rosetas comparten tabla porque comparten esquema; lo que las separa es la **lista de
clases** que pide cada consumidor. Por eso `clases` es un parámetro y no hay dos funciones: la
vista de Cajas PON pasa las siete, la de Rosetas pasa `[85]`, y un buscador global no pasa ninguna.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(slots=True)
class PonElementoInventario:
    n_id: int
    clase: int
    nombre: Optional[str]
    localidad: Optional[str]
    calle: Optional[str]
    altura: Optional[str]
    propietario: Optional[str]
    tipo_conector: Optional[str]
    capacidad_puertos: Optional[int]
    latitud: Optional[float]
    longitud: Optional[float]
    vigente: bool
    cantidad_splitters: int


@dataclass(slots=True)
class ResultadoBusquedaPon:
    total: int
    limit: int
    offset: int
    elementos: list[PonElementoInventario]


# `CAST(...)` explícito en cada filtro opcional, por el mismo motivo real que ya documentan
# `inventario.py` y `odf_inventario.py`: sin él, cuando todos los filtros son NULL a la vez —el caso
# más común, "listame todo"— el driver no puede inferir el tipo del parámetro en la primera
# preparación del statement y tira `could not determine data type of parameter $1`. El atajo
# `:param::tipo` pegado al bind no sirve; siempre `CAST(:param AS tipo)`.
#
# `clases` va con `= ANY(...)` sobre un `bigint[]` en vez de un `IN` armado por string: es lo que
# permite que la misma consulta sirva para la vista de Cajas PON (siete clases) y la de Rosetas
# (una) sin concatenar SQL.
_FILTROS_SQL = """
    WHERE (CAST(:q AS text) IS NULL OR e.nombre ILIKE CAST(:q AS text))
      AND (CAST(:n_id AS bigint) IS NULL OR e.n_id = CAST(:n_id AS bigint))
      AND (CAST(:clases AS bigint[]) IS NULL OR e.clase = ANY(CAST(:clases AS bigint[])))
      AND (CAST(:vigente AS boolean) IS NULL OR e.vigente = CAST(:vigente AS boolean))
      AND (CAST(:localidad AS text) IS NULL OR e.localidad ILIKE CAST(:localidad AS text))
      AND (CAST(:propietario AS text) IS NULL OR e.propietario ILIKE CAST(:propietario AS text))
"""

_SQL_CONTAR = text(
    f"""
    SELECT count(*) FROM app.cromo_pon_elementos e
    {_FILTROS_SQL}
    """
)

# `cantidad_splitters` sale de `cromo_splitters.contenedor_n_id`, que es exactamente para lo que
# esa columna existe. Es un subselect correlacionado sobre las filas YA paginadas (como mucho
# `limit` lookups sobre un índice), no un join contra la tabla entera: mismo criterio que
# `odf_inventario`. Es el dato que el operador quiere ver de una caja PON —cuántos splitters tiene
# adentro— y el único que no se lee de la propia fila.
_SQL_BUSCAR = text(
    f"""
    SELECT
        e.n_id,
        e.clase,
        e.nombre,
        e.localidad,
        e.calle,
        e.altura,
        e.propietario,
        e.tipo_conector,
        e.capacidad_puertos,
        e.latitud,
        e.longitud,
        e.vigente,
        (
            SELECT count(*)
            FROM app.cromo_splitters s
            WHERE s.contenedor_n_id = e.n_id AND s.vigente = true
        ) AS cantidad_splitters
    FROM app.cromo_pon_elementos e
    {_FILTROS_SQL}
    ORDER BY e.localidad NULLS LAST, e.calle NULLS LAST, e.altura NULLS LAST, e.nombre, e.n_id
    LIMIT :limit OFFSET :offset
    """
)


def _texto_o_none(valor: Optional[str]) -> Optional[str]:
    """Un filtro en blanco es "sin filtro", no "igual a nada"."""
    return f"%{valor.strip()}%" if valor and valor.strip() else None


async def buscar_pon_elementos(
    sesion: AsyncSession,
    *,
    q: Optional[str] = None,
    n_id: Optional[int] = None,
    clases: Optional[Sequence[int]] = None,
    vigente: Optional[bool] = None,
    localidad: Optional[str] = None,
    propietario: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> ResultadoBusquedaPon:
    """Búsqueda paginada de cajas PON y rosetas.

    `q`/`localidad`/`propietario` son `ILIKE` parcial; `n_id`/`vigente` exactos; `clases` acota a un
    subconjunto de las ocho clases que viven en la tabla.

    Orden por `localidad, calle, altura, nombre, n_id` (NULLS LAST en las tres primeras), igual que
    el inventario de ODFs: deja adyacentes los elementos que comparten domicilio físico sin
    necesitar una columna de sitio que Cromo no publica.

    Dos consultas fijas (COUNT + SELECT paginado), sin N+1.
    """
    params = {
        "q": _texto_o_none(q),
        "n_id": n_id,
        "clases": list(clases) if clases else None,
        "vigente": vigente,
        "localidad": _texto_o_none(localidad),
        "propietario": _texto_o_none(propietario),
    }

    total = (await sesion.execute(_SQL_CONTAR, params)).scalar_one()
    filas = (
        await sesion.execute(_SQL_BUSCAR, {**params, "limit": limit, "offset": offset})
    ).all()

    elementos = [
        PonElementoInventario(
            n_id=fila[0],
            clase=fila[1],
            nombre=fila[2],
            localidad=fila[3],
            calle=fila[4],
            altura=fila[5],
            propietario=fila[6],
            tipo_conector=fila[7],
            capacidad_puertos=fila[8],
            latitud=fila[9],
            longitud=fila[10],
            vigente=fila[11],
            cantidad_splitters=fila[12],
        )
        for fila in filas
    ]
    return ResultadoBusquedaPon(total=total, limit=limit, offset=offset, elementos=elementos)


__all__ = ["PonElementoInventario", "ResultadoBusquedaPon", "buscar_pon_elementos"]
