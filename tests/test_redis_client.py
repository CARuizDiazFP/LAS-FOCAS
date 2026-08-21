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
