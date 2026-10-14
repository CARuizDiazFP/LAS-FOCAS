# Nombre de archivo: clientes_categoria_hooks.py
# Ubicación de archivo: core/services/clientes_categoria_hooks.py
# Descripción: Hook resiliente que sincroniza la categoría de los clientes tocados por una ingesta (Excel SLA, PROV, scripts)

"""Puente entre las ingestas de `servicios` y `sincronizar_categorias`.

Las ingestas (planilla SLA, refresco PROV on-demand, refresco PROV desde Slack y los scripts de
backfill PROV) llaman a este hook DESPUÉS de su propio `commit`: abre una sesión sync propia
(`SessionLocal`), sincroniza sólo las claves de los clientes tocados (o todo, en los scripts) y
hace `commit`.

Resiliencia: una falla de la sync nunca tumba la ingesta. Se loguea `action=clientes_sync_error`
y se devuelve `None`; la sync es idempotente, así que el botón "Re-sincronizar" del módulo de
clientes (o la próxima ingesta) lo corrige.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable

from core.services.clientes_categoria_service import claves_de_nombres, sincronizar_categorias
from db.session import SessionLocal

logger = logging.getLogger(__name__)


def sincronizar_clientes_en_sesion_propia(claves: set[str] | None, *, origen: str) -> dict | None:
    """Sincroniza `claves` (o todos los clientes si es `None`) en una sesión propia y hace `commit`.

    Un conjunto vacío no hace nada (nunca degrada a una sync global). Nunca lanza: ante cualquier
    error loguea `action=clientes_sync_error` y devuelve `None`. Devuelve el `ResumenSync` como
    dict si la sync corrió."""
    if claves is not None and not claves:
        return None
    alcance = "global" if claves is None else str(len(claves))
    try:
        with SessionLocal() as session:
            resumen = sincronizar_categorias(session, claves)
            session.commit()
    except Exception:  # noqa: BLE001 - la ingesta que llama ya está commiteada y no debe caerse
        logger.exception("action=clientes_sync_error origen=%s claves=%s", origen, alcance)
        return None
    resultado = resumen.to_dict()
    logger.info(
        "action=clientes_sync origen=%s claves=%s clientes_creados=%d clientes_recalculados=%d "
        "servicios_actualizados=%d",
        origen,
        alcance,
        resultado["clientes_creados"],
        resultado["clientes_recalculados"],
        resultado["servicios_actualizados"],
    )
    return resultado


async def sincronizar_clientes_post_ingesta(nombres: Iterable[str | None], *, origen: str) -> dict | None:
    """Versión async para rutas/workers: calcula las claves de `nombres` (ignora vacíos) y corre la
    sync en un thread aparte (`asyncio.to_thread`, no bloquea el event loop). Sin claves válidas no
    hace nada. Nunca lanza."""
    claves = claves_de_nombres(nombres)
    if not claves:
        return None
    try:
        return await asyncio.to_thread(sincronizar_clientes_en_sesion_propia, claves, origen=origen)
    except Exception:  # noqa: BLE001 - defensa extra: el hook sync ya atrapa todo
        logger.exception("action=clientes_sync_error origen=%s claves=%d", origen, len(claves))
        return None
