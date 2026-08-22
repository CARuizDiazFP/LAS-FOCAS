# Nombre de archivo: botella_recompute_queue.py
# Ubicación de archivo: core/services/botella_recompute_queue.py
# Descripción: Caché + cola de recálculo en background de los grupos de Botellas duplicadas (Redis)

"""Los 7 endpoints que mutan datos que afectan `detectar_grupos_duplicados_botellas` (vigente,
camara_id/camara_padre_id, nombre) invalidan la caché y encolan un job acá — ver
`docs/superpowers/specs/2026-08-21-botellas-duplicados-redis-ws.md`. El worker
`modules/botellas_recalculo_worker` consume la cola, recalcula y vuelve a poblar la caché."""

from __future__ import annotations

import json
import logging

from core.cache.redis_client import get_redis
from core.services.botella_duplicados_service import BotellaDuplicadaItem, GrupoBotellasDuplicadas

logger = logging.getLogger(__name__)

CACHE_KEY = "cache:botellas_duplicados:v1"
CACHE_TTL_SECONDS = 86400
QUEUE_KEY = "admin:recompute:jobs"
JOB_KIND_BOTELLAS_DUPLICADOS = "botellas_duplicados"
# Canal pub/sub del aviso "ya recalculé". Vive acá, junto a las otras claves del pipeline, para que
# los dos extremos (el worker que publica y `web/admin_ws.py` que se suscribe) importen la MISMA
# constante — antes cada uno declaraba su propio literal y un rename podía desincronizarlos en
# silencio, sin que ningún test lo notara.
ADMIN_NOTIFICATIONS_CHANNEL = "admin-notifications"


def _grupo_to_dict(grupo: GrupoBotellasDuplicadas) -> dict:
    return {
        "camara_padre_id": grupo.camara_padre_id,
        "camara_padre_nombre": grupo.camara_padre_nombre,
        "clave_normalizada": grupo.clave_normalizada,
        "criterio": grupo.criterio,
        "estados_en_conflicto": grupo.estados_en_conflicto,
        "estado_mas_restrictivo": grupo.estado_mas_restrictivo,
        "resoluble": grupo.resoluble,
        "miembros": [
            {"origen": m.origen, "id": m.id, "nombre": m.nombre, "estado": m.estado}
            for m in grupo.miembros
        ],
    }


def _grupo_from_dict(data: dict) -> GrupoBotellasDuplicadas:
    return GrupoBotellasDuplicadas(
        camara_padre_id=data["camara_padre_id"],
        camara_padre_nombre=data["camara_padre_nombre"],
        clave_normalizada=data["clave_normalizada"],
        criterio=data["criterio"],
        miembros=[BotellaDuplicadaItem(**m) for m in data["miembros"]],
        estados_en_conflicto=data["estados_en_conflicto"],
        estado_mas_restrictivo=data["estado_mas_restrictivo"],
        resoluble=data["resoluble"],
    )


async def leer_cache_duplicados() -> list[GrupoBotellasDuplicadas] | None:
    """`None` = cache frío, payload corrupto, o Redis no disponible — el caller cae al cómputo
    síncrono existente sin cambios."""
    try:
        raw = await get_redis().get(CACHE_KEY)
    except Exception:  # noqa: BLE001 - Redis es best-effort
        logger.warning("action=botellas_duplicados_cache_read result=fail", exc_info=True)
        return None
    if raw is None:
        return None
    try:
        return [_grupo_from_dict(item) for item in json.loads(raw)]
    except (json.JSONDecodeError, TypeError, KeyError):
        logger.warning("action=botellas_duplicados_cache_read result=fail reason=payload_invalido")
        return None


async def guardar_cache_duplicados(grupos: list[GrupoBotellasDuplicadas]) -> None:
    """Best-effort — nunca rompe al caller si Redis no está disponible."""
    try:
        payload = json.dumps([_grupo_to_dict(g) for g in grupos])
        await get_redis().set(CACHE_KEY, payload, ex=CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.warning("action=botellas_duplicados_cache_write result=fail", exc_info=True)


async def encolar_recalculo_duplicados_botellas(motivo: str) -> None:
    """Invalida la caché y encola un job de recálculo para el worker — best-effort, nunca lanza.
    Llamar SIEMPRE después de confirmar la mutación (después de `session.commit()`), nunca antes."""
    try:
        client = get_redis()
        await client.delete(CACHE_KEY)
        await client.rpush(
            QUEUE_KEY,
            json.dumps({"kind": JOB_KIND_BOTELLAS_DUPLICADOS, "motivo": motivo}),
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "action=botellas_duplicados_recompute_enqueue result=fail motivo=%s", motivo, exc_info=True
        )


__all__ = [
    "ADMIN_NOTIFICATIONS_CHANNEL",
    "CACHE_KEY",
    "QUEUE_KEY",
    "JOB_KIND_BOTELLAS_DUPLICADOS",
    "leer_cache_duplicados",
    "guardar_cache_duplicados",
    "encolar_recalculo_duplicados_botellas",
]
