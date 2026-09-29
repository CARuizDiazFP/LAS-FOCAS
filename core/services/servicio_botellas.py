# Nombre de archivo: servicio_botellas.py
# Ubicación de archivo: core/services/servicio_botellas.py
# Descripción: Resolución de un Servicio por ID vigente/histórico y de las Botellas de FO por las que pasa (API v1)

"""Servicio → Botellas de fibra óptica, para integraciones interáreas (`GET /api/v1/...`).

Nunca llama a Cromo en vivo (su `/path` cuesta 4,6-14 s por pelo). Arma la lista en capas, de la
más precisa a la más amplia, deduplicando por nombre y conservando la primera aparición:

1. ``traza_cromo``: trackings `.txt` ya generados y frescos en `app.cromo_tracking_cache`. Sus
   líneas ``Empalme <id>: <nombre>`` están en orden de recorrido. El renderer emite con el mismo
   formato las ODF (y Cromo incluye racks de nodo), así que sólo se aceptan los ids que existen en
   `app.cromo_botellas` y el nombre se toma de ahí, no del texto.
2. ``traza_legada``: rutas activas cargadas desde trackings legacy (`RutaServicio` → `Empalme`, en
   el orden de `ruta_empalme_association.orden`). `tracking_empalme_id` tiene la forma
   ``<servicio>_<id Cromo>``: medido en dev el 2026-09-29, el sufijo coincide con
   `cromo_botellas.n_id` en 3107 de 3252 empalmes. Mismo filtro que la capa 1: sólo cuentan los
   que están en `cromo_botellas`. Los 145 restantes son casi todos ODF/Nodo/Rack (96 están en
   `cromo_odfs`), y `Empalme.es_transito` no sirve para descartarlos porque está en `false` en
   todas las filas; caer al nombre de la Cámara colaba esas ODF como si fueran botellas.
3. ``inventario``: botellas extremo A/B de los cables por los que tiene pelos el servicio
   (`cromo_servicio_match` → `cromo_pelos` → `cromo_cables` → `cromo_botellas`). No tiene orden de
   recorrido: se agrega al final en orden alfabético. Es la capa más amplia (el número de servicio
   figura en cada pelo del recorrido, no sólo en el de la ODF).

Las capas 1 y 2 son excluyentes (la legada sólo se usa si no hay traza de Cromo fresca); la 3
siempre complementa. ``orden_fuente`` informa qué capa dio el orden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Literal, Optional

from sqlalchemy import any_, case, exists, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from core.services.cromo import tracking_cache
from core.services.cromo.servicios_sin_odf import IDENTIDADES_DEL_SERVICIO_SQL
from db.models.infra import Servicio

OrdenFuente = Literal["traza_cromo", "traza_legada", "inventario", "sin_datos"]

_RE_EMPALME = re.compile(r"^Empalme (\d+): ")


@dataclass(frozen=True)
class ServicioResuelto:
    servicio: Servicio
    es_id_vigente: bool


@dataclass(frozen=True)
class ResultadoBotellas:
    nombres: list[str]
    orden_fuente: OrdenFuente


async def resolver_servicio_por_identificador(session: AsyncSession, identificador: str) -> Optional[ServicioResuelto]:
    """Busca el Servicio por ID vigente, alias histórico, primer servicio o número de línea.

    Dos reglas, en este orden:

    1. Se excluye toda fila cuyo `servicio_id`/`numero_primer_servicio` fue absorbido como alias por
       OTRA fila: esa identidad "se mudó" a la fila que la absorbió. Mismo criterio anti-ambigüedad
       que `_SQL_BUSCAR_SERVICIO` en `core/services/cromo/ingesta.py` (bug real 2026-08-31: una
       fila `MANUAL` huérfana con `servicio_id='61943'` le ganaba a la vigente que tenía `61943` en
       `alias_ids`). En dev quedaban 43 filas así el 2026-09-29.
    2. Entre las que quedan: ID vigente, alias, `numero_primer_servicio` y por último `numero_linea`.
    """

    ident = identificador.strip()
    if not ident:
        return None
    prioridad = case(
        (Servicio.servicio_id == ident, 0),
        (Servicio.alias_ids.any(ident), 1),
        (Servicio.numero_primer_servicio == ident, 2),
        else_=3,
    )
    absorbente = aliased(Servicio)
    identidad_absorbida = exists().where(
        absorbente.id != Servicio.id,
        or_(
            Servicio.servicio_id == any_(absorbente.alias_ids),
            Servicio.numero_primer_servicio == any_(absorbente.alias_ids),
        ),
    )
    servicio = (
        await session.execute(
            select(Servicio)
            .where(
                or_(
                    Servicio.servicio_id == ident,
                    Servicio.alias_ids.any(ident),
                    Servicio.numero_primer_servicio == ident,
                    Servicio.numero_linea == ident,
                ),
                ~identidad_absorbida,
            )
            .order_by(prioridad, Servicio.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if servicio is None:
        return None
    return ServicioResuelto(servicio=servicio, es_id_vigente=(servicio.servicio_id == ident))


def ids_empalme_en_orden(contenidos: Iterable[str]) -> list[int]:
    """Ids de las líneas ``Empalme <id>: <nombre>`` de uno o más trackings, en orden y sin repetir."""

    vistos: dict[int, None] = {}
    for contenido in contenidos:
        for linea in contenido.splitlines():
            coincidencia = _RE_EMPALME.match(linea.strip())
            if coincidencia:
                vistos.setdefault(int(coincidencia.group(1)), None)
    return list(vistos)


def deduplicar(nombres: Iterable[Optional[str]]) -> list[str]:
    """Descarta nulos/vacíos y repetidos, conservando la primera aparición."""

    vistos: dict[str, None] = {}
    for nombre in nombres:
        limpio = (nombre or "").strip()
        if limpio:
            vistos.setdefault(limpio, None)
    return list(vistos)


_SQL_TRACKINGS_DEL_SERVICIO = text(
    f"""
    SELECT tc.pelo_n_id, tc.contenido, tc.generado_at
    FROM app.cromo_tracking_cache tc
    WHERE tc.servicio_id = :sid
       OR tc.pelo_n_id IN (
            SELECT m.pelo_n_id
            FROM app.servicios s
            JOIN app.cromo_servicio_match m ON ({IDENTIDADES_DEL_SERVICIO_SQL})
            WHERE s.id = :sid
       )
    ORDER BY tc.pelo_n_id
    """
)

_SQL_NOMBRES_BOTELLAS = text(
    "SELECT n_id, nombre FROM app.cromo_botellas WHERE n_id = ANY(:ids ::bigint[])"
)

_SQL_RUTA_LEGADA = text(
    """
    SELECT b.nombre
    FROM app.rutas_servicio r
    JOIN app.ruta_empalme_association rea ON rea.ruta_id = r.id
    JOIN app.empalmes e ON e.id = rea.empalme_id
    JOIN app.cromo_botellas b
      ON b.n_id = CASE
                    WHEN split_part(e.tracking_empalme_id, '_', 2) ~ '^[0-9]+$'
                    THEN CAST(split_part(e.tracking_empalme_id, '_', 2) AS bigint)
                  END
    WHERE r.servicio_id = :sid
      AND r.activa
    ORDER BY (r.tipo = 'PRINCIPAL') DESC, r.id, rea.orden NULLS LAST, e.id
    """
)

_SQL_INVENTARIO = text(
    f"""
    SELECT DISTINCT b.nombre
    FROM app.servicios s
    JOIN app.cromo_servicio_match m ON ({IDENTIDADES_DEL_SERVICIO_SQL})
    JOIN app.cromo_pelos p ON p.n_id = m.pelo_n_id AND p.vigente
    JOIN app.cromo_cables cb ON cb.n_id = p.cable_n_id AND cb.vigente
    JOIN app.cromo_botellas b
      ON (b.n_id = cb.extremo_a_n_id OR b.n_id = cb.extremo_b_n_id) AND b.vigente
    WHERE s.id = :sid
      AND b.nombre IS NOT NULL
      AND btrim(b.nombre) <> ''
    ORDER BY b.nombre
    """
)


async def _botellas_traza_cromo(session: AsyncSession, servicio_pk: int, *, ahora: datetime) -> list[str]:
    filas = (await session.execute(_SQL_TRACKINGS_DEL_SERVICIO, {"sid": servicio_pk})).all()
    frescos = [contenido for _, contenido, generado_at in filas if not tracking_cache.esta_vencido(generado_at, ahora)]
    ids = ids_empalme_en_orden(frescos)
    if not ids:
        return []
    nombres = dict((await session.execute(_SQL_NOMBRES_BOTELLAS, {"ids": ids})).all())
    return deduplicar(nombres.get(i) for i in ids)


async def _botellas_ruta_legada(session: AsyncSession, servicio_pk: int) -> list[str]:
    return deduplicar((await session.execute(_SQL_RUTA_LEGADA, {"sid": servicio_pk})).scalars())


async def _botellas_inventario(session: AsyncSession, servicio_pk: int) -> list[str]:
    return deduplicar((await session.execute(_SQL_INVENTARIO, {"sid": servicio_pk})).scalars())


async def botellas_de_servicio(
    session: AsyncSession, servicio_pk: int, *, ahora: Optional[datetime] = None
) -> ResultadoBotellas:
    """Nombres de las Botellas por las que pasa el servicio, con la capa que determinó el orden."""

    ahora = ahora or datetime.now(timezone.utc)
    ordenadas = await _botellas_traza_cromo(session, servicio_pk, ahora=ahora)
    fuente: OrdenFuente = "traza_cromo"
    if not ordenadas:
        ordenadas = await _botellas_ruta_legada(session, servicio_pk)
        fuente = "traza_legada"
    inventario = await _botellas_inventario(session, servicio_pk)

    nombres = deduplicar([*ordenadas, *inventario])
    if not nombres:
        return ResultadoBotellas(nombres=[], orden_fuente="sin_datos")
    if not ordenadas:
        fuente = "inventario"
    return ResultadoBotellas(nombres=nombres, orden_fuente=fuente)
