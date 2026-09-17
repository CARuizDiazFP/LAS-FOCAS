# Nombre de archivo: tracking_cache.py
# Ubicación de archivo: core/services/cromo/tracking_cache.py
# Descripción: Caché de salida, con vencimiento, del tracking .txt de cada pelo — evita repetir la
# llamada a /path de Cromo (4,6-14 s medidos) en cada descarga, sobre todo en la descarga multipelo

"""Caché del artefacto `.txt`, no del inventario.

El camino óptico sigue sin persistirse: nada de lo que devuelve `/path` entra en las tablas
`cromo_*` de inventario (ver el docstring de `camino_optico_service.CaminoOptico`). Lo que se
guarda acá es el texto **ya renderizado** por `camino_optico_txt.renderizar_tracking_txt`, con
vencimiento, para no pagar de nuevo la llamada de red.

Por qué hace falta (medido real contra Cromo el 2026-09-17): una llamada a
`GET /network/fo/{pelo}/path` tarda entre 4,6 s y 14 s, y pasarle varios ids separados por coma
**no** devuelve varios caminos — con 3 ids Cromo contestó un único nodo raíz. La descarga del
tracking de N pelos son entonces N llamadas secuenciales: el servicio real 122347, con 6 pelos,
costaba entre 30 y 85 s en frío. Con este caché, ese costo se paga una vez por pelo y por ventana
de TTL.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.cromo import CromoTrackingCache

logger = logging.getLogger(__name__)

TTL_HORAS_DEFAULT = 24.0
_VARIABLE_TTL = "CROMO_TRACKING_CACHE_TTL_HORAS"


def ttl_horas() -> float:
    """TTL de frescura en horas. 24 h por defecto, ajustable por entorno.

    Un valor no numérico o <= 0 no rompe la descarga: se registra y se cae al default, porque un
    caché mal configurado nunca debe ser motivo de que el operador no pueda bajar su tracking.
    """
    crudo = os.getenv(_VARIABLE_TTL, "").strip()
    if not crudo:
        return TTL_HORAS_DEFAULT
    try:
        valor = float(crudo)
    except ValueError:
        logger.warning("action=tracking_cache evento=ttl_invalido valor=%r usando=%s", crudo, TTL_HORAS_DEFAULT)
        return TTL_HORAS_DEFAULT
    if valor <= 0:
        logger.warning("action=tracking_cache evento=ttl_no_positivo valor=%s usando=%s", valor, TTL_HORAS_DEFAULT)
        return TTL_HORAS_DEFAULT
    return valor


def esta_vencido(generado_at: Optional[datetime], ahora: datetime, horas: Optional[float] = None) -> bool:
    """¿La entrada generada en `generado_at` ya venció respecto de `ahora`?

    Función pura, sin base ni entorno cuando se le pasa `horas` — el grueso de la lógica de
    frescura se prueba sin Postgres.

    Una entrada sin fecha se trata como vencida (no se confía en lo que no se puede fechar). Una
    fecha ingenua se interpreta como UTC: Postgres devuelve `timestamptz`, pero un objeto armado a
    mano en un test o en un backfill puede venir sin tzinfo, y compararlo crudo contra un `ahora`
    con tz revienta con TypeError.
    """
    if generado_at is None:
        return True
    if generado_at.tzinfo is None:
        generado_at = generado_at.replace(tzinfo=timezone.utc)
    limite = timedelta(hours=horas if horas is not None else ttl_horas())
    return (ahora - generado_at) >= limite


@dataclass(slots=True)
class TrackingCacheado:
    """Un `.txt` ya generado y todavía fresco."""

    pelo_n_id: int
    nombre_archivo: str
    contenido: str
    generado_at: datetime
    duracion_ms: Optional[int]


async def leer(sesion: AsyncSession, pelo_n_id: int, *, ahora: Optional[datetime] = None) -> Optional[TrackingCacheado]:
    """Devuelve el tracking cacheado del pelo, o `None` si no existe o venció.

    Nunca devuelve contenido vencido: para el llamador, una entrada vieja y una inexistente son lo
    mismo, así no hay dos caminos distintos que mantener aguas arriba.
    """
    ahora = ahora or datetime.now(timezone.utc)
    fila = (
        await sesion.execute(select(CromoTrackingCache).where(CromoTrackingCache.pelo_n_id == pelo_n_id))
    ).scalar_one_or_none()
    if fila is None:
        return None
    if esta_vencido(fila.generado_at, ahora):
        return None
    return TrackingCacheado(
        pelo_n_id=fila.pelo_n_id,
        nombre_archivo=fila.nombre_archivo,
        contenido=fila.contenido,
        generado_at=fila.generado_at,
        duracion_ms=fila.duracion_ms,
    )


async def frescura(
    sesion: AsyncSession, pelos_n_id: Iterable[int], *, ahora: Optional[datetime] = None
) -> dict[int, datetime]:
    """`{pelo_n_id: generado_at}` de los pelos con tracking fresco, en UNA query.

    Alimenta el indicador de la UI que le dice al operador si la descarga va a ser instantánea o
    va a tardar. Los pelos vencidos o ausentes simplemente no aparecen en el dict.
    """
    ids = [int(p) for p in pelos_n_id]
    if not ids:
        return {}
    ahora = ahora or datetime.now(timezone.utc)
    filas = (
        await sesion.execute(
            select(CromoTrackingCache.pelo_n_id, CromoTrackingCache.generado_at).where(
                CromoTrackingCache.pelo_n_id.in_(ids)
            )
        )
    ).all()
    return {
        pelo_n_id: generado_at
        for pelo_n_id, generado_at in filas
        if not esta_vencido(generado_at, ahora)
    }


async def guardar(
    sesion: AsyncSession,
    *,
    pelo_n_id: int,
    servicio_id: Optional[int],
    nombre_archivo: str,
    contenido: str,
    duracion_ms: Optional[int] = None,
    ahora: Optional[datetime] = None,
) -> None:
    """Escribe (o pisa) la entrada del pelo y purga las vencidas en el mismo paso.

    El upsert va por `ON CONFLICT (pelo_n_id) DO UPDATE` para que dos descargas simultáneas del
    mismo pelo no choquen con una violación de PK. No hace `commit`: la transacción la maneja el
    llamador, que normalmente está sirviendo una descarga.
    """
    ahora = ahora or datetime.now(timezone.utc)
    sentencia = pg_insert(CromoTrackingCache.__table__).values(
        pelo_n_id=pelo_n_id,
        servicio_id=servicio_id,
        nombre_archivo=nombre_archivo,
        contenido=contenido,
        duracion_ms=duracion_ms,
        generado_at=ahora,
    )
    await sesion.execute(
        sentencia.on_conflict_do_update(
            index_elements=[CromoTrackingCache.__table__.c.pelo_n_id],
            set_={
                "servicio_id": sentencia.excluded.servicio_id,
                "nombre_archivo": sentencia.excluded.nombre_archivo,
                "contenido": sentencia.excluded.contenido,
                "duracion_ms": sentencia.excluded.duracion_ms,
                "generado_at": sentencia.excluded.generado_at,
            },
        )
    )
    await _purgar_vencidos(sesion, ahora)


async def invalidar(sesion: AsyncSession, pelos_n_id: Iterable[int]) -> int:
    """Borra las entradas de los pelos indicados y devuelve cuántas cayeron.

    Se usa al normalizar una inconsistencia: si la base cambió, el `.txt` generado antes describe
    un estado que ya no es el vigente y no puede seguir sirviéndose como fresco.
    """
    ids = [int(p) for p in pelos_n_id]
    if not ids:
        return 0
    resultado = await sesion.execute(
        delete(CromoTrackingCache).where(CromoTrackingCache.pelo_n_id.in_(ids))
    )
    return int(resultado.rowcount or 0)


async def _purgar_vencidos(sesion: AsyncSession, ahora: datetime) -> None:
    """Elimina lo vencido aprovechando que ya estamos escribiendo.

    Evita un job de limpieza propio: el caché sólo crece cuando alguien descarga, así que purgar en
    la escritura acota la tabla sin tarea programada. Va sobre el índice de `generado_at`.
    """
    corte = ahora - timedelta(hours=ttl_horas())
    await sesion.execute(delete(CromoTrackingCache).where(CromoTrackingCache.generado_at < corte))
