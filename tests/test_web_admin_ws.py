# Nombre de archivo: test_web_admin_ws.py
# Ubicación de archivo: tests/test_web_admin_ws.py
# Descripción: Pruebas del canal WebSocket de notificaciones admin — auth y broadcast, sin Redis real

from __future__ import annotations

from starlette.websockets import WebSocketDisconnect
import pytest
from fastapi.testclient import TestClient

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
