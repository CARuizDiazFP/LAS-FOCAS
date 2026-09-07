# Nombre de archivo: test_redis_client.py
# Ubicación de archivo: tests/test_redis_client.py
# Descripción: Pruebas del cliente Redis async — URL encoding, singleton, manejo de secretos

from __future__ import annotations

import pytest

from core.cache import redis_client


def test_build_redis_url_sin_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """URL correcta cuando no hay contraseña."""
    monkeypatch.setenv("REDIS_HOST", "redis.local")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_PASSWORD", "")
    url = redis_client._build_redis_url()
    assert url == "redis://redis.local:6380/0"


def test_build_redis_url_con_password_simple(monkeypatch: pytest.MonkeyPatch) -> None:
    """URL correcta con contraseña simple."""
    monkeypatch.setenv("REDIS_HOST", "redis.local")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_PASSWORD", "simplepass123")
    url = redis_client._build_redis_url()
    assert url == "redis://:simplepass123@redis.local:6380/0"


def test_build_redis_url_password_especiales_codificados(monkeypatch: pytest.MonkeyPatch) -> None:
    """URL-encoding: contraseña con @, :, /, %, = se codifica correctamente."""
    monkeypatch.setenv("REDIS_HOST", "redis.local")
    monkeypatch.setenv("REDIS_PORT", "6379")
    # Contraseña que contiene caracteres URL-unsafe: @, :, /, %, =
    monkeypatch.setenv("REDIS_PASSWORD", "p@ss:word/test=1%base64")
    url = redis_client._build_redis_url()
    # Verificar que los caracteres especiales estén codificados en la URL
    assert "%40" in url  # @ codificado
    assert "%3A" in url  # : codificado
    assert "%2F" in url  # / codificado
    assert "%25" in url  # % codificado
    assert "%3D" in url  # = codificado
    # Verificar estructura de la URL
    assert url.startswith("redis://:p%40ss%3Aword%2Ftest%3D1%25base64@redis.local:6379/0")


def test_get_redis_singleton_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_redis() devuelve siempre la misma instancia (singleton)."""
    # Resetear el cliente para esta prueba
    redis_client.reset_redis_client()

    # Primera llamada debe construir el cliente
    client1 = redis_client.get_redis()
    assert client1 is not None

    # Segunda llamada debe devolver la misma instancia
    client2 = redis_client.get_redis()
    assert client1 is client2

    # Limpiar para otras pruebas
    redis_client.reset_redis_client()


def test_reset_redis_client_fuerza_reconstruccion(monkeypatch: pytest.MonkeyPatch) -> None:
    """reset_redis_client() fuerza que la próxima llamada a get_redis() cree un cliente nuevo."""
    redis_client.reset_redis_client()

    client1 = redis_client.get_redis()
    redis_client.reset_redis_client()
    client2 = redis_client.get_redis()

    # Deben ser instancias diferentes
    assert client1 is not client2

    # Limpiar
    redis_client.reset_redis_client()


def _connection_kwargs(client) -> dict:
    return client.connection_pool.connection_kwargs


def test_pubsub_client_es_una_instancia_separada_del_compartido() -> None:
    """El subscriber pub/sub NO debe compartir cliente con los comandos cortos."""
    redis_client.reset_redis_client()
    try:
        compartido = redis_client.get_redis()
        pubsub = redis_client.get_redis_pubsub_client()
        assert pubsub is not compartido
        # ...pero sigue siendo singleton por sí mismo.
        assert pubsub is redis_client.get_redis_pubsub_client()
    finally:
        redis_client.reset_redis_client()


def test_pubsub_client_sin_socket_timeout_de_lectura() -> None:
    """Regresión del bug medido en dev (2026-08-22): con el `socket_timeout` finito del cliente
    compartido, `PubSub.listen()` levantaba TimeoutError cada 10s de silencio del canal, se
    desconectaba y resuscribía — dejando el canal SIN suscriptores ~5s de cada ~15s y perdiendo todo
    lo publicado en esas ventanas (pub/sub es fire-and-forget)."""
    redis_client.reset_redis_client()
    try:
        kwargs_pubsub = _connection_kwargs(redis_client.get_redis_pubsub_client())
        assert kwargs_pubsub.get("socket_timeout") is None, (
            "el cliente pub/sub debe bloquear indefinidamente en la lectura"
        )
        # Conectar a un host muerto sí debe seguir fallando rápido: es otra preocupación.
        assert kwargs_pubsub.get("socket_connect_timeout") == 2
        # Keepalive TCP: única defensa contra un peer que muere sin FIN/RST.
        assert kwargs_pubsub.get("socket_keepalive") is True
        assert kwargs_pubsub.get("socket_keepalive_options")
    finally:
        redis_client.reset_redis_client()


def test_cliente_compartido_conserva_su_socket_timeout_finito() -> None:
    """El cliente compartido NO cambia: el BLPOP del worker y los GET/SET/DEL/RPUSH son operaciones
    acotadas que sí quieren un timeout finito."""
    redis_client.reset_redis_client()
    try:
        kwargs = _connection_kwargs(redis_client.get_redis())
        assert kwargs.get("socket_timeout") == 10
        assert kwargs.get("socket_connect_timeout") == 2
    finally:
        redis_client.reset_redis_client()


def test_reset_redis_client_tambien_resetea_el_pubsub() -> None:
    redis_client.reset_redis_client()
    try:
        primero = redis_client.get_redis_pubsub_client()
        redis_client.reset_redis_client()
        assert redis_client.get_redis_pubsub_client() is not primero
    finally:
        redis_client.reset_redis_client()
