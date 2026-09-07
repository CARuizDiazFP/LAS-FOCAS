# Nombre de archivo: test_web_admin_ws.py
# Ubicación de archivo: tests/test_web_admin_ws.py
# Descripción: Pruebas del canal WebSocket de notificaciones admin — auth y broadcast, sin Redis real

from __future__ import annotations

import asyncio
import json
import logging

from starlette.websockets import WebSocketDisconnect
import pytest
from fastapi.testclient import TestClient

from web import admin_ws
from web.admin_ws import ConnectionManager
from web.app.main import app

client = TestClient(app)


def test_admin_ws_sin_identidad_devuelve_4401(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "true")
    with client.websocket_connect("/ws/admin-notifications") as websocket:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()
        assert exc_info.value.code == 4401


def test_admin_ws_no_admin_devuelve_4401(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "true")
    with client.websocket_connect(
        "/ws/admin-notifications", headers={"X-Test-User": "user1:user"}
    ) as websocket:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()
        assert exc_info.value.code == 4401


@pytest.mark.asyncio
async def test_connection_manager_broadcast_ignora_conexion_rota() -> None:
    manager = ConnectionManager()

    class _Rota:
        async def send_json(self, message):
            raise RuntimeError("conexión cerrada")

    class _Ok:
        def __init__(self):
            self.recibido = None

        async def send_json(self, message):
            self.recibido = message

    rota, ok = _Rota(), _Ok()
    manager.register(rota)
    manager.register(ok)
    await manager.broadcast({"type": "test"})
    assert ok.recibido == {"type": "test"}


# ── _subscriber_loop: conexión Redis dedicada (fix 2026-08-22) ────────────────


class _FakePubSub:
    """Pub/sub fake: entrega los mensajes dados y después se queda bloqueado para siempre, igual que
    el `listen()` real de una conexión sin `socket_timeout`."""

    def __init__(self, mensajes: list[dict], *, fallar_subscribe: bool = False) -> None:
        self.mensajes = mensajes
        self.fallar_subscribe = fallar_subscribe
        self.canales: list[str] = []
        self.cerrado = False

    async def subscribe(self, canal: str) -> None:
        if self.fallar_subscribe:
            raise ConnectionError("redis caído")
        self.canales.append(canal)

    async def listen(self):
        for mensaje in self.mensajes:
            yield mensaje
        await asyncio.Event().wait()  # bloquea indefinidamente, nunca por timeout

    async def aclose(self) -> None:
        self.cerrado = True


class _FakeClient:
    def __init__(self, pubsub: _FakePubSub) -> None:
        self._pubsub = pubsub
        self.veces = 0

    def pubsub(self) -> _FakePubSub:
        self.veces += 1
        return self._pubsub


class _ConexionEspia:
    def __init__(self) -> None:
        self.recibidos: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.recibidos.append(message)


def test_admin_ws_no_usa_el_cliente_redis_compartido() -> None:
    """Regresión: el subscriber debe usar la conexión dedicada (`socket_timeout=None`). Con el
    cliente compartido (`socket_timeout=10`) el canal quedaba sin suscriptores ~5s de cada ~15s de
    silencio — medido con `PUBSUB NUMSUB` contra el dev real."""
    assert hasattr(admin_ws, "get_redis_pubsub_client")
    assert not hasattr(admin_ws, "get_redis"), (
        "web/admin_ws.py no debe importar el cliente Redis compartido"
    )


def test_admin_ws_reusa_la_constante_de_canal_del_pipeline() -> None:
    """El canal se declara una sola vez (`core/services/botella_recompute_queue.py`); los dos
    extremos lo importan de ahí, no cada uno su propio literal."""
    from core.services import botella_recompute_queue
    from modules.botellas_recalculo_worker import worker as worker_mod

    assert admin_ws.ADMIN_NOTIFICATIONS_CHANNEL is botella_recompute_queue.ADMIN_NOTIFICATIONS_CHANNEL
    assert worker_mod.ADMIN_NOTIFICATIONS_CHANNEL is botella_recompute_queue.ADMIN_NOTIFICATIONS_CHANNEL


@pytest.mark.asyncio
async def test_subscriber_loop_suscribe_con_el_cliente_dedicado_y_broadcastea(monkeypatch) -> None:
    fake_pubsub = _FakePubSub([
        {"type": "subscribe", "channel": "admin-notifications", "data": 1},
        {"type": "message", "data": json.dumps({"type": "botellas_duplicados_recalculado", "at": "z"})},
    ])
    fake_client = _FakeClient(fake_pubsub)
    monkeypatch.setattr(admin_ws, "get_redis_pubsub_client", lambda: fake_client)

    manager = ConnectionManager()
    conexion = _ConexionEspia()
    manager.register(conexion)

    tarea = asyncio.create_task(admin_ws._subscriber_loop(manager, logging.getLogger("test_admin_ws")))
    try:
        for _ in range(100):
            if conexion.recibidos:
                break
            await asyncio.sleep(0.01)
    finally:
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    assert fake_client.veces == 1, "debió suscribirse una sola vez (sin ciclo de timeout/reconexión)"
    assert fake_pubsub.canales == ["admin-notifications"]
    assert conexion.recibidos == [{"type": "botellas_duplicados_recalculado", "at": "z"}]


@pytest.mark.asyncio
async def test_subscriber_loop_reintenta_y_libera_la_conexion_si_redis_falla(monkeypatch) -> None:
    """Un fallo REAL (Redis caído) se sigue atrapando, logueando y reintentando con backoff — y la
    conexión pub/sub vuelve al pool en vez de quedar colgada en cada reintento."""
    fake_pubsub = _FakePubSub([], fallar_subscribe=True)
    monkeypatch.setattr(admin_ws, "get_redis_pubsub_client", lambda: _FakeClient(fake_pubsub))

    dormidas: list[float] = []

    async def _fake_sleep(segundos: float) -> None:
        dormidas.append(segundos)
        raise asyncio.CancelledError()  # cortar el loop tras el primer reintento

    monkeypatch.setattr(admin_ws.asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await admin_ws._subscriber_loop(ConnectionManager(), logging.getLogger("test_admin_ws"))

    assert dormidas == [5], "el backoff fijo de 5s sigue vigente para fallos reales"
    assert fake_pubsub.cerrado is True, "la conexión pub/sub debe liberarse antes de reintentar"
