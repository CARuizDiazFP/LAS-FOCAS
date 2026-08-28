# Nombre de archivo: odf_detalle.py
# Ubicación de archivo: core/services/cromo/odf_detalle.py
# Descripción: Detalle de UN ODF (metadata + cables asociados resueltos + vecinos de misma dirección), sin N+1

"""Resuelve "mostrame el detalle completo de este ODF" — metadata propia, los cables que Cromo le
asocia (`cables_asociados`, JSONB con n_ids de cable) resueltos a `{n_id, nombre}` vía join contra
`cromo_cables`, y otros ODFs que comparten domicilio físico (mismo espíritu que
`core/services/cromo/detalle.py` para cables, pero sin tubos/pelos: un ODF no tiene jerarquía
propia, sólo referencia cables por `n_id`). Sólo lectura sobre las tablas `app.cromo_*` ya pobladas
por la ingesta (Tareas 1-3 del plan ODFs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.cromo.verificador import ObjetoNoEncontrado


@dataclass(slots=True)
class DetalleOdf:
    n_id: int
    nombre: Optional[str]
    tipo_elemento: str
    propietario: Optional[str]
    codigo_modelo: Optional[str]
    id_legacy: Optional[str]
    notas: Optional[str]
    calle: Optional[str]
    altura: Optional[str]
    localidad: Optional[str]
    provincia: Optional[str]
    ubicacion_fisica: Optional[str]
    tendido: Optional[str]
    latitud: Optional[float]
    longitud: Optional[float]
    vigente: bool
    cables_asociados: list[dict] = field(default_factory=list)
    odfs_en_la_misma_direccion: list[dict] = field(default_factory=list)


_SQL_ODF_DETALLE = text(
    """
    SELECT o.n_id, o.nombre, o.tipo_elemento, o.propietario, o.codigo_modelo, o.id_legacy, o.notas,
           o.calle, o.altura, o.localidad, o.provincia, o.ubicacion_fisica, o.tendido,
           o.latitud, o.longitud, o.vigente, o.cables_asociados
    FROM app.cromo_odfs o
    WHERE o.n_id = :n_id
    """
)

# `cables_asociados` es un mirror crudo de n_ids (JSONB) sin FK dura a `cromo_cables` (mismo criterio
# "sin FK dura" que el resto de Cromo, ver docstrings de CromoCable/CromoFusion): un cable referenciado
# puede no haber bajado todavía. `ANY(:cable_ids ::bigint[])` resuelve todos los nombres en una sola
# query — nunca una por cable (evita N+1 incluso si el ODF referencia decenas de cables).
_SQL_CABLES_POR_IDS = text(
    """
    SELECT n_id, nombre
    FROM app.cromo_cables
    WHERE n_id = ANY(:cable_ids ::bigint[])
    """
)

# CAST(:calle AS text) IS NOT NULL como guardia explícita: si el propio ODF no tiene `calle` cargada,
# esta query debe devolver cero filas (no agrupar falsamente todos los ODFs sin dirección conocida
# entre sí, ver brief de la Tarea 4) — en vez de resolver eso en Python con un `if` que salte la
# query, se lo deja resuelto en el WHERE para que la firma siga siendo "3 queries fijas" sin
# ramas. `altura`/`localidad` usan `IS NOT DISTINCT FROM` (NULL-safe) porque dos ODFs de la misma
# calle que comparten "sin altura cargada" siguen siendo la misma dirección física a los efectos de
# este agrupamiento — una igualdad estricta (`altura = :altura`) nunca matchea NULL contra NULL y
# los dejaría siempre afuera entre sí.
_SQL_VECINOS_DIRECCION = text(
    """
    SELECT n_id, nombre
    FROM app.cromo_odfs
    WHERE CAST(:calle AS text) IS NOT NULL
      AND calle = CAST(:calle AS text)
      AND altura IS NOT DISTINCT FROM CAST(:altura AS text)
      AND localidad IS NOT DISTINCT FROM CAST(:localidad AS text)
      AND n_id != :n_id
    ORDER BY nombre NULLS LAST, n_id
    """
)


async def obtener_detalle_odf(sesion: AsyncSession, n_id: int) -> DetalleOdf:
    """Detalle completo de un ODF: metadata + cables asociados resueltos + vecinos de misma dirección.

    3 queries fijas sin importar cuántos cables asociados o vecinos tenga el ODF (nunca N+1): el ODF
    propio, TODOS los nombres de `cables_asociados` en una sola query (`ANY(...)`), y los vecinos de
    dirección en una sola query (con guardia `calle IS NOT NULL` resuelta en el propio WHERE).

    A diferencia de `detalle.obtener_detalle_cable`, no hay tolerancia a "referencia colgada": un
    ODF sólo existe si tiene fila propia en `cromo_odfs` (no hay tubos/pelos que lo referencien por
    fuera de esa fila, como sí pasa con cables). Si no hay fila, levanta `ObjetoNoEncontrado`.
    """
    odf = (await sesion.execute(_SQL_ODF_DETALLE, {"n_id": n_id})).first()
    if odf is None:
        raise ObjetoNoEncontrado(f"No existe un ODF con n_id={n_id} en el inventario ingerido.")

    cables_asociados_ids: list[int] = [cid for cid in (odf[16] or []) if cid is not None]
    filas_cables = (
        await sesion.execute(_SQL_CABLES_POR_IDS, {"cable_ids": cables_asociados_ids})
    ).all()
    nombres_por_cable = {fila[0]: fila[1] for fila in filas_cables}
    # Preserva el orden de `cables_asociados` tal como lo manda Cromo, no el orden alfabético de la
    # resolución — y no descarta en silencio un cable que todavía no bajó (nombre=None en vez de
    # desaparecer de la lista), mismo criterio tolerante que el resto de Cromo.
    cables_asociados = [
        {"n_id": cid, "nombre": nombres_por_cable.get(cid)} for cid in cables_asociados_ids
    ]

    filas_vecinos = (
        await sesion.execute(
            _SQL_VECINOS_DIRECCION,
            {"calle": odf[7], "altura": odf[8], "localidad": odf[9], "n_id": n_id},
        )
    ).all()
    odfs_en_la_misma_direccion = [{"n_id": fila[0], "nombre": fila[1]} for fila in filas_vecinos]

    return DetalleOdf(
        n_id=odf[0],
        nombre=odf[1],
        tipo_elemento=odf[2],
        propietario=odf[3],
        codigo_modelo=odf[4],
        id_legacy=odf[5],
        notas=odf[6],
        calle=odf[7],
        altura=odf[8],
        localidad=odf[9],
        provincia=odf[10],
        ubicacion_fisica=odf[11],
        tendido=odf[12],
        latitud=odf[13],
        longitud=odf[14],
        vigente=odf[15],
        cables_asociados=cables_asociados,
        odfs_en_la_misma_direccion=odfs_en_la_misma_direccion,
    )


__all__ = ["DetalleOdf", "obtener_detalle_odf"]
