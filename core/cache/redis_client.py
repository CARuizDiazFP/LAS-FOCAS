# Nombre de archivo: redis_client.py
# Ubicación de archivo: core/cache/redis_client.py
# Descripción: Factory de cliente Redis async compartido — lazy, nunca lanza al construirse

from __future__ import annotations

from urllib.parse import quote

from redis.asyncio import Redis, from_url

from core.config import get_secret

_client: Redis | None = None


def _build_redis_url() -> str:
    host = get_secret("REDIS_HOST", "REDIS_HOST", "redis")
    port = get_secret("REDIS_PORT", "REDIS_PORT", "6379")
    password = get_secret("redis_password_v1", "REDIS_PASSWORD", "")
    auth = f":{quote(password, safe='')}@" if password else ""
    return f"redis://{auth}{host}:{port}/0"


def get_redis() -> Redis:
    """Cliente Redis compartido. Construirlo es lazy (no abre conexión) — cada comando real puede
    fallar si Redis no está disponible; cada caller decide cómo degradar, nunca se propaga acá."""
    global _client
    if _client is None:
        _client = from_url(
            _build_redis_url(),
            decode_responses=True,
            socket_connect_timeout=2,
            # BLPOP_TIMEOUT_SECONDS (modules/botellas_recalculo_worker/config.py) es 5s: el timeout
            # de lectura del socket debe superarlo con margen, o cada ciclo BLPOP idle (el caso
            # normal, sin jobs) lanza un TimeoutError espurio del lado cliente — server y cliente
            # tienen relojes de timeout independientes, redis-py no los coordina para comandos
            # bloqueantes. 10s = 2x BLPOP_TIMEOUT_SECONDS + margen por jitter de red/GC.
            socket_timeout=10,
        )
    return _client


def reset_redis_client() -> None:
    """Sólo para tests: fuerza reconstruir el cliente en la próxima llamada a `get_redis()`."""
    global _client
    _client = None


__all__ = ["get_redis", "reset_redis_client"]
