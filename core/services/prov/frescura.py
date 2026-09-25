# Nombre de archivo: frescura.py
# Ubicación de archivo: core/services/prov/frescura.py
# Descripción: Consulta batch — dado un conjunto de servicio_id, cuáles tienen la sincronización PROV vencida (versión async y sync)

"""Frescura de `app.servicios_sync_prov` (Task 7 del plan "Corrección de ingresos/servicios").

Un `servicio_id` (el PK entero de `app.servicios`, no el `servicio_id` string externo) cuenta como
**vencido** si nunca tiene fila en `servicios_sync_prov` (`ultima_sincronizacion_ok IS NULL`) o si su
última sincronización exitosa es más vieja que el umbral de frescura. Con la tabla recién creada y
vacía, y el 92,5% de los servicios alcanzables por cable sin ninguna sincronización histórica contra
PROV (medido real contra `lasfocasdev-postgres`, ver `docs/decisiones.md`), lo esperable hasta que
corra `scripts/servicios_backfill_prov.py` es que la enorme mayoría de cualquier lote consultado
vuelva vencida — no es un bug de esta consulta, es el estado real del dato.

Siempre batch, nunca una query por servicio: la Task 8 llama esta consulta con hasta ~118
`servicio_id` de una sola vez (el tamaño de un cable real, ver `servicios_unicos_por_cable` en
`core/services/cromo/verificador.py`) — un query por servicio a esa escala sería 118 round-trips
por comando de Slack.

Dos versiones, async y sync, mismo patrón de gemelas que ya usa `verificador.py`
(`servicios_unicos_por_cable`/`servicios_unicos_por_cable_sync`): el listener de Slack que consume
esta consulta (Task 8) corre en un callback síncrono de Slack Bolt, así que necesita la variante
`Session` sin `await`. Misma sentencia `text()` en ambas — sólo cambia `await`.

Gotcha real del repo con `text()` + psycopg3 (ver `verificador.py::_SQL_TIENE_CABLES_BATCH`): un bind
nombrado con cast de array lleva el espacio ANTES del `::` (`:ids ::integer[]`) — `:ids::integer[]`
sin espacio falla. La consulta usa `unnest(:ids ::integer[])` para tratar el conjunto de entrada como
la única fuente de verdad (no hace falta tocar `app.servicios`: la pregunta es exclusivamente sobre
el estado de `servicios_sync_prov`, y un `servicio_id` que el caller nunca debería haber pasado
igual cae del lado seguro — "vencido" — al no tener fila).

Umbral configurable por `PROV_FRESCURA_HORAS` (default 48 h) — mismo criterio tolerante que
`core/services/cromo/tracking_cache.py::ttl_horas`: un valor no numérico o <= 0 no rompe la consulta,
se loguea y se cae al default.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_VARIABLE_HORAS = "PROV_FRESCURA_HORAS"
HORAS_FRESCURA_DEFAULT = 48.0


def horas_frescura() -> float:
    """Umbral de frescura en horas. 48 h por defecto, ajustable por entorno.

    Un valor no numérico o <= 0 no rompe la consulta de frescura: se registra y se cae al default,
    mismo criterio que `tracking_cache.ttl_horas` — una variable de entorno mal puesta nunca debe
    ser motivo de que el comando de Slack (Task 8) deje de responder.
    """
    crudo = os.getenv(_VARIABLE_HORAS, "").strip()
    if not crudo:
        return HORAS_FRESCURA_DEFAULT
    try:
        valor = float(crudo)
    except ValueError:
        logger.warning(
            "action=prov_frescura evento=horas_invalidas valor=%r usando=%s", crudo, HORAS_FRESCURA_DEFAULT
        )
        return HORAS_FRESCURA_DEFAULT
    if valor <= 0:
        logger.warning(
            "action=prov_frescura evento=horas_no_positivas valor=%s usando=%s", valor, HORAS_FRESCURA_DEFAULT
        )
        return HORAS_FRESCURA_DEFAULT
    return valor


# `unnest` sobre el propio parámetro: el universo de la consulta es exactamente el conjunto de
# entrada, no lo que exista o no en `app.servicios`/`servicios_sync_prov`. Un id sin fila en
# `servicios_sync_prov` sale por el `LEFT JOIN` con `ultima_sincronizacion_ok IS NULL` -> vencido.
_SQL_VENCIDOS_BATCH = text(
    """
    SELECT entrada.servicio_id
    FROM unnest(:ids ::integer[]) AS entrada(servicio_id)
    LEFT JOIN app.servicios_sync_prov sp ON sp.servicio_id = entrada.servicio_id
    WHERE sp.ultima_sincronizacion_ok IS NULL OR sp.ultima_sincronizacion_ok < :corte
    """
)


def _normalizar_ids(servicio_ids: Iterable[int]) -> list[int]:
    return sorted({int(i) for i in servicio_ids})


def _corte(horas: Optional[float], ahora: Optional[datetime]) -> datetime:
    ahora = ahora or datetime.now(timezone.utc)
    return ahora - timedelta(hours=horas if horas is not None else horas_frescura())


async def servicios_vencidos(
    sesion: AsyncSession,
    servicio_ids: Iterable[int],
    *,
    horas: Optional[float] = None,
    ahora: Optional[datetime] = None,
) -> set[int]:
    """Subconjunto de `servicio_ids` (PK de `app.servicios`) cuya sincronización PROV está vencida
    o nunca existió. `horas`/`ahora` son overrides explícitos para tests deterministas — en
    producción ambos quedan en `None` y se resuelven contra `horas_frescura()`/`datetime.now()`."""
    ids = _normalizar_ids(servicio_ids)
    if not ids:
        return set()
    corte = _corte(horas, ahora)
    filas = (await sesion.execute(_SQL_VENCIDOS_BATCH, {"ids": ids, "corte": corte})).all()
    return {f[0] for f in filas}


def servicios_vencidos_sync(
    session: Session,
    servicio_ids: Iterable[int],
    *,
    horas: Optional[float] = None,
    ahora: Optional[datetime] = None,
) -> set[int]:
    """Gemela síncrona de `servicios_vencidos` — mismo patrón que
    `servicios_unicos_por_cable_sync` (`core/services/cromo/verificador.py`): misma `text()`, sólo
    cambia el `await`. Para el comando de Slack que consume esta consulta (Task 8), que corre dentro
    de un callback síncrono de Slack Bolt."""
    ids = _normalizar_ids(servicio_ids)
    if not ids:
        return set()
    corte = _corte(horas, ahora)
    filas = session.execute(_SQL_VENCIDOS_BATCH, {"ids": ids, "corte": corte}).all()
    return {f[0] for f in filas}


__all__ = [
    "HORAS_FRESCURA_DEFAULT",
    "horas_frescura",
    "servicios_vencidos",
    "servicios_vencidos_sync",
]
