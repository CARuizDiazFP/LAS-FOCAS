# Nombre de archivo: redis_client.py
# Ubicación de archivo: core/cache/redis_client.py
# Descripción: Factories de clientes Redis async — uno compartido para comandos cortos y otro dedicado a pub/sub

from __future__ import annotations

import socket
from urllib.parse import quote

from redis.asyncio import Redis, from_url

from core.config import get_secret

_client: Redis | None = None
_pubsub_client: Redis | None = None


def _keepalive_options() -> dict[int, int]:
    """Opciones TCP keepalive para el cliente pub/sub (`socket_timeout=None`): sin reloj de lectura
    del lado cliente, un peer que muere en silencio (sin FIN/RST — cable cortado, NAT que expira)
    dejaría el `listen()` colgado para siempre. El keepalive del kernel detecta ese caso en ~90s
    (60s idle + 3 sondas cada 10s) y hace que la lectura falle con `ConnectionError`, que el caller
    ya reintenta. Las constantes son de Linux; en una plataforma que no las tenga se omiten (redis-py
    cierra la conexión y propaga si `setsockopt` recibe una opción inválida)."""
    opciones: dict[int, int] = {}
    for nombre, valor in (("TCP_KEEPIDLE", 60), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3)):
        constante = getattr(socket, nombre, None)
        if constante is not None:
            opciones[constante] = valor
    return opciones


def _build_redis_url() -> str:
    host = get_secret("REDIS_HOST", "REDIS_HOST", "redis")
    port = get_secret("REDIS_PORT", "REDIS_PORT", "6379")
    password = get_secret("redis_password_v1", "REDIS_PASSWORD", "")
    auth = f":{quote(password, safe='')}@" if password else ""
    return f"redis://{auth}{host}:{port}/0"


def get_redis() -> Redis:
    """Cliente Redis compartido para comandos CORTOS Y ACOTADOS (GET/SET/DEL/RPUSH/PUBLISH y el BLPOP
    del worker). Construirlo es lazy (no abre conexión) — cada comando real puede fallar si Redis no
    está disponible; cada caller decide cómo degradar, nunca se propaga acá.

    NO usar este cliente para un subscriber pub/sub de larga vida: su `socket_timeout` finito
    convierte el silencio normal del canal en un `TimeoutError` — ver `get_redis_pubsub_client()`."""
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


def get_redis_pubsub_client() -> Redis:
    """Cliente Redis DEDICADO a subscribers pub/sub de larga vida (`web/admin_ws.py`).

    Separado de `get_redis()` a propósito: `PubSub.listen()` llama a `parse_response(block=True)`,
    que pasa `timeout=None` a `Connection.read_response()`; ahí `read_timeout = timeout if timeout is
    not None else self.socket_timeout` cae al `socket_timeout` del cliente (verificado en el fuente
    real de redis-py 5.0.8 instalado en `.venv/`). Con el `socket_timeout=10` de `get_redis()`, cada
    10s de silencio genuino del canal el `async_timeout` vence → `asyncio.TimeoutError` →
    `raise TimeoutError(...)` → `Retry.call_with_retry` lo trata como error soportado → el handler
    `PubSub._disconnect_raise_connect` hace `await conn.disconnect()` y re-lanza → el caller
    reconecta y resuscribe. Resultado medido en dev: el canal quedaba SIN suscriptores ~5s de cada
    ~15s, y todo lo publicado en esas ventanas se perdía para siempre (pub/sub es fire-and-forget).

    `socket_timeout=None` = bloquear indefinidamente en la lectura, que es exactamente lo que un
    subscriber debe hacer. Los fallos REALES se siguen detectando: si el server cierra la conexión
    (RST/FIN, contenedor detenido/reiniciado) el parser levanta `ConnectionError("Connection closed
    by server.")` desde `IncompleteReadError`/EOF, y si el host está caído el `socket_connect_timeout`
    de 2s hace fallar rápido el intento de conexión. El keepalive TCP cubre el caso de muerte
    silenciosa sin FIN/RST."""
    global _pubsub_client
    if _pubsub_client is None:
        _pubsub_client = from_url(
            _build_redis_url(),
            decode_responses=True,
            # Conectar a un host muerto sí debe fallar rápido: es una preocupación distinta e
            # independiente del timeout de lectura.
            socket_connect_timeout=2,
            socket_timeout=None,
            socket_keepalive=True,
            socket_keepalive_options=_keepalive_options(),
        )
    return _pubsub_client


def reset_redis_client() -> None:
    """Sólo para tests: fuerza reconstruir ambos clientes en la próxima llamada a su factory."""
    global _client, _pubsub_client
    _client = None
    _pubsub_client = None


__all__ = ["get_redis", "get_redis_pubsub_client", "reset_redis_client"]
