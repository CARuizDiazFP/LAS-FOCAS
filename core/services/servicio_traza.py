# Nombre de archivo: servicio_traza.py
# Ubicación de archivo: core/services/servicio_traza.py
# Descripción: Resolución de un Servicio por ID vigente/histórico y de su traza de FO (Botellas, Cables y ODF) para la API v1

"""Servicio → Botellas, Cables y ODF de fibra óptica, para integraciones interáreas (`/api/v1/...`).

Nunca llama a Cromo en vivo (su `/path` cuesta 4,6-14 s por pelo). Botellas y Cables se arman en
capas, de la más precisa a la más amplia, deduplicando por nombre y conservando la primera
aparición:

1. ``traza_cromo``: trackings `.txt` ya generados y frescos en `app.cromo_tracking_cache`, en
   orden de recorrido.
   - Botellas: líneas ``Empalme <id>: <nombre>``. El renderer emite con el mismo formato las ODF
     (y Cromo incluye racks de nodo), así que sólo se aceptan los ids que existen en
     `app.cromo_botellas` y el nombre se toma de ahí, no del texto.
   - Cables: líneas de tramo ``<cable>: <pelo> (<color> / <buffer> - <pelo>) --> ...``. Sólo se
     aceptan nombres de cables vigentes de `app.cromo_cables`.
2. ``traza_legada``: rutas activas cargadas desde trackings legacy.
   - Botellas: `RutaServicio` → `Empalme`, en el orden de `ruta_empalme_association.orden`.
     `tracking_empalme_id` tiene la forma ``<servicio>_<id Cromo>``: medido en dev el 2026-09-29, el
     sufijo coincide con `cromo_botellas.n_id` en 3107 de 3252 empalmes. Mismo filtro que la capa 1.
     Los 145 restantes son casi todos ODF/Nodo/Rack (96 están en `cromo_odfs`), y
     `Empalme.es_transito` no sirve para descartarlos porque está en `false` en todas las filas;
     caer al nombre de la Cámara colaba esas ODF como si fueran botellas.
   - Cables: las mismas líneas de tramo, leídas del `raw_file_content` de la ruta (el formato
     legacy es la misma gramática con la columna dB al final).
3. ``inventario``: lo que conecta los pelos matcheados al servicio (`cromo_servicio_match` →
   `cromo_pelos` → `cromo_cables` [→ `cromo_botellas` extremo A/B]). Sin orden de recorrido: se
   agrega al final en orden alfabético.

Las capas 1 y 2 son excluyentes (la legada sólo se usa si no hay traza de Cromo fresca); la 3
siempre complementa. ``orden_fuente`` informa qué capa dio el orden.

ODF: siempre desde Cromo (`verificador.odfs_por_servicio`, vías `servicio_resuelto` y `pelo`). Los
overrides manuales de LAS-FOCAS quedan fuera a propósito: el contrato con las otras áreas es "Cromo
es la fuente de la verdad". Las posiciones (bandeja + conector) salen de `cromo_odf_conectores`.
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
from core.services.cromo.verificador import odfs_por_servicio
from db.models.infra import Servicio

OrdenFuente = Literal["traza_cromo", "traza_legada", "inventario", "sin_datos"]

_RE_EMPALME = re.compile(r"^Empalme (\d+): ")
# Tramo de cable: "F-MRT-001: 3 (AZ / 1 - 3) --> 148 / 148 mts * 151.7 mts". El paréntesis con
# color/buffer/pelo lo distingue de la línea de terminal de ODF ("O-1266814-1: 3 --> Sin longitud").
_RE_TRAMO = re.compile(r"^(?P<cable>[^#:][^:]*?): \S+ \([^)]*\) --> ")


@dataclass(frozen=True)
class ServicioResuelto:
    servicio: Servicio
    es_id_vigente: bool


@dataclass(frozen=True)
class ResultadoTraza:
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


async def _trackings_frescos(session: AsyncSession, servicio_pk: int, *, ahora: datetime) -> list[str]:
    filas = (await session.execute(_SQL_TRACKINGS_DEL_SERVICIO, {"sid": servicio_pk})).all()
    return [contenido for _, contenido, generado_at in filas if not tracking_cache.esta_vencido(generado_at, ahora)]


async def _botellas_traza_cromo(session: AsyncSession, servicio_pk: int, *, ahora: datetime) -> list[str]:
    ids = ids_empalme_en_orden(await _trackings_frescos(session, servicio_pk, ahora=ahora))
    if not ids:
        return []
    nombres = dict((await session.execute(_SQL_NOMBRES_BOTELLAS, {"ids": ids})).all())
    return deduplicar(nombres.get(i) for i in ids)


async def _botellas_ruta_legada(session: AsyncSession, servicio_pk: int) -> list[str]:
    return deduplicar((await session.execute(_SQL_RUTA_LEGADA, {"sid": servicio_pk})).scalars())


async def _botellas_inventario(session: AsyncSession, servicio_pk: int) -> list[str]:
    return deduplicar((await session.execute(_SQL_INVENTARIO, {"sid": servicio_pk})).scalars())


def _combinar(ordenadas: list[str], fuente: OrdenFuente, inventario: list[str]) -> ResultadoTraza:
    nombres = deduplicar([*ordenadas, *inventario])
    if not nombres:
        return ResultadoTraza(nombres=[], orden_fuente="sin_datos")
    return ResultadoTraza(nombres=nombres, orden_fuente=fuente if ordenadas else "inventario")


async def botellas_de_servicio(
    session: AsyncSession, servicio_pk: int, *, ahora: Optional[datetime] = None
) -> ResultadoTraza:
    """Nombres de las Botellas por las que pasa el servicio, con la capa que determinó el orden."""

    ahora = ahora or datetime.now(timezone.utc)
    ordenadas = await _botellas_traza_cromo(session, servicio_pk, ahora=ahora)
    fuente: OrdenFuente = "traza_cromo"
    if not ordenadas:
        ordenadas = await _botellas_ruta_legada(session, servicio_pk)
        fuente = "traza_legada"
    return _combinar(ordenadas, fuente, await _botellas_inventario(session, servicio_pk))


# ── Cables ────────────────────────────────────────────────────────────────────


def cables_en_orden(contenidos: Iterable[str]) -> list[str]:
    """Nombres de cable de las líneas de tramo de uno o más trackings, en orden y sin repetir."""

    return deduplicar(
        coincidencia.group("cable")
        for contenido in contenidos
        for linea in contenido.splitlines()
        if (coincidencia := _RE_TRAMO.match(linea.strip()))
    )


_SQL_CABLES_VIGENTES_POR_NOMBRE = text(
    "SELECT DISTINCT nombre FROM app.cromo_cables WHERE vigente AND nombre = ANY(:nombres ::text[])"
)

_SQL_TRACKINGS_LEGADOS = text(
    """
    SELECT r.raw_file_content
    FROM app.rutas_servicio r
    WHERE r.servicio_id = :sid
      AND r.activa
      AND r.raw_file_content IS NOT NULL
    ORDER BY (r.tipo = 'PRINCIPAL') DESC, r.id
    """
)

_SQL_CABLES_INVENTARIO = text(
    f"""
    SELECT DISTINCT cb.nombre
    FROM app.servicios s
    JOIN app.cromo_servicio_match m ON ({IDENTIDADES_DEL_SERVICIO_SQL})
    JOIN app.cromo_pelos p ON p.n_id = m.pelo_n_id AND p.vigente
    JOIN app.cromo_cables cb ON cb.n_id = p.cable_n_id AND cb.vigente
    WHERE s.id = :sid
      AND cb.nombre IS NOT NULL
      AND btrim(cb.nombre) <> ''
    ORDER BY cb.nombre
    """
)


async def _solo_cables_vigentes(session: AsyncSession, nombres: list[str]) -> list[str]:
    if not nombres:
        return []
    vigentes = set((await session.execute(_SQL_CABLES_VIGENTES_POR_NOMBRE, {"nombres": nombres})).scalars())
    return [n for n in nombres if n in vigentes]


async def _cables_traza_cromo(session: AsyncSession, servicio_pk: int, *, ahora: datetime) -> list[str]:
    return await _solo_cables_vigentes(
        session, cables_en_orden(await _trackings_frescos(session, servicio_pk, ahora=ahora))
    )


async def _cables_ruta_legada(session: AsyncSession, servicio_pk: int) -> list[str]:
    contenidos = (await session.execute(_SQL_TRACKINGS_LEGADOS, {"sid": servicio_pk})).scalars()
    return await _solo_cables_vigentes(session, cables_en_orden(contenidos))


async def _cables_inventario(session: AsyncSession, servicio_pk: int) -> list[str]:
    return deduplicar((await session.execute(_SQL_CABLES_INVENTARIO, {"sid": servicio_pk})).scalars())


async def cables_de_servicio(
    session: AsyncSession, servicio_pk: int, *, ahora: Optional[datetime] = None
) -> ResultadoTraza:
    """Nombres de los Cables por los que pasa el servicio. Mismas capas y precedencia que las Botellas."""

    ahora = ahora or datetime.now(timezone.utc)
    ordenados = await _cables_traza_cromo(session, servicio_pk, ahora=ahora)
    fuente: OrdenFuente = "traza_cromo"
    if not ordenados:
        ordenados = await _cables_ruta_legada(session, servicio_pk)
        fuente = "traza_legada"
    return _combinar(ordenados, fuente, await _cables_inventario(session, servicio_pk))


# ── ODF (Cromo como fuente de la verdad) ──────────────────────────────────────


@dataclass(frozen=True)
class PosicionOdf:
    bandeja: Optional[str]
    conector: Optional[str]
    pelo: Optional[str]


@dataclass(frozen=True)
class OdfDelServicio:
    odf_n_id: int
    nombre: Optional[str]
    direccion: Optional[str]
    localidad: Optional[str]
    posiciones: list[PosicionOdf]


_SQL_PELOS_DEL_SERVICIO = text(
    f"""
    SELECT DISTINCT m.pelo_n_id
    FROM app.servicios s
    JOIN app.cromo_servicio_match m ON ({IDENTIDADES_DEL_SERVICIO_SQL})
    WHERE s.id = :sid
    """
)

# Una sola query para las posiciones de todas las ODF del servicio. No se reusa
# `odf_conectores.conectores_de_odf`: resuelve el servicio de CADA conector de la ODF con un
# `LATERAL` + `NOT EXISTS` sobre `app.servicios` (medido en dev el 2026-09-29: ~500 ms por ODF de
# 48 conectores). Acá el servicio ya está resuelto, así que alcanza con filtrar por las mismas dos
# vías con las que `odfs_por_servicio` llegó a la ODF: el conector apunta a una identidad del
# servicio (`servicio_resuelto`) o cuelga de uno de sus pelos matcheados.
# Orden `length(numero_conector), numero_conector`: mismo criterio que `odf_conectores`
# (`numero_conector` es texto; un CAST podría reventar con un valor no numérico de Cromo).
_SQL_POSICIONES_ODF = text(
    """
    SELECT c.odf_n_id, c.bandeja_nombre, c.numero_conector, p.numero_pelo
    FROM app.cromo_odf_conectores c
    LEFT JOIN app.cromo_pelos p ON p.n_id = c.pelo_n_id
    WHERE c.odf_n_id = ANY(:odfs ::bigint[])
      AND (c.servicio_resuelto = ANY(:identidades ::text[]) OR c.pelo_n_id = ANY(:pelos ::bigint[]))
    ORDER BY c.odf_n_id, c.bandeja_nombre NULLS LAST, length(c.numero_conector), c.numero_conector
    """
)

_ORIGENES_CROMO = frozenset({"servicio_resuelto", "pelo"})


def _identidades(servicio: Servicio) -> list[str]:
    return deduplicar([servicio.servicio_id, servicio.numero_primer_servicio, *(servicio.alias_ids or [])])


async def odfs_de_servicio(session: AsyncSession, servicio: Servicio) -> list[OdfDelServicio]:
    """ODF de Cromo a las que llega el servicio, con las posiciones (bandeja + conector) que ocupa."""

    odfs = [o for o in await odfs_por_servicio(session, servicio.id) if o.origen in _ORIGENES_CROMO]
    if not odfs:
        return []
    pelos = list((await session.execute(_SQL_PELOS_DEL_SERVICIO, {"sid": servicio.id})).scalars())
    filas = (
        await session.execute(
            _SQL_POSICIONES_ODF,
            {"odfs": [o.odf_n_id for o in odfs], "identidades": _identidades(servicio), "pelos": pelos},
        )
    ).all()
    posiciones: dict[int, list[PosicionOdf]] = {}
    for odf_n_id, bandeja, conector, pelo in filas:
        posiciones.setdefault(odf_n_id, []).append(PosicionOdf(bandeja=bandeja, conector=conector, pelo=pelo))

    return [
        OdfDelServicio(
            odf_n_id=odf.odf_n_id,
            nombre=odf.nombre,
            direccion=" ".join(p for p in (odf.calle, odf.altura) if p) or None,
            localidad=odf.localidad,
            posiciones=posiciones.get(odf.odf_n_id, []),
        )
        for odf in odfs
    ]
