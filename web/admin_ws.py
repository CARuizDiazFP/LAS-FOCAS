# Nombre de archivo: admin_ws.py
# Ubicación de archivo: web/admin_ws.py
# Descripción: Canal WebSocket genérico de notificaciones admin — broadcast a todos los paneles conectados

"""A diferencia de `web/chat_ws.py` (1 conexión ↔ 1 orchestrator, sin registro), este canal necesita
hacer BROADCAST: cualquier proceso externo (el worker de recálculo, hoy; potencialmente otros a
futuro) publica en el canal Redis `admin-notifications` y este módulo reenvía el mensaje a TODAS las
conexiones WebSocket activas del panel admin — de ahí el `ConnectionManager` con un `set`, que
`chat_ws.py` no necesita."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect

from core.cache.redis_client import get_redis_pubsub_client
from core.services.botella_recompute_queue import ADMIN_NOTIFICATIONS_CHANNEL

_TESTING_HEADER = "x-test-user"


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    def register(self, websocket: WebSocket) -> None:
        self._connections.add(websocket)

    def unregister(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        # Copia de la lista antes de iterar: un cliente puede desconectarse durante el broadcast.
        for connection in list(self._connections):
            try:
                await connection.send_json(message)
            except Exception:  # noqa: BLE001 - una conexión rota no debe tumbar el broadcast
                self.unregister(connection)


async def _get_admin_identity(websocket: WebSocket, allowed_origins: list[str]) -> str:
    session = getattr(websocket, "session", None) or {}
    username: Optional[str] = session.get("username") if isinstance(session, dict) else None
    role: str = session.get("role", "user") if isinstance(session, dict) else "user"

    if not username and os.getenv("TESTING", "false").lower() == "true":
        header_user = websocket.headers.get(_TESTING_HEADER)
        if header_user:
            parts = header_user.split(":", 1)
            username = parts[0]
            if len(parts) > 1:
                role = parts[1]

    # Mismo chequeo de origen que `web/chat_ws.py::_get_user_identity` — evita que otro sitio abra
    # este WebSocket autenticado por cookie de sesión (CSRF-vía-WS).
    origin = websocket.headers.get("origin")
    if allowed_origins and origin and origin not in allowed_origins:
        raise PermissionError("Origen no autorizado")

    if not username:
        raise PermissionError("Sesión no encontrada")
    if role != "admin":
        raise PermissionError("Permisos insuficientes")
    return username


async def _cerrar_pubsub(pubsub) -> None:
    """Best-effort: liberar la conexión pub/sub al pool. Nunca puede tapar el error original que
    llevó a cerrarla, ni frenar un `CancelledError` en curso."""
    if pubsub is None:
        return
    try:
        await pubsub.aclose()
    except Exception:  # noqa: BLE001 - cierre best-effort
        pass


async def _subscriber_loop(manager: ConnectionManager, logger: logging.Logger) -> None:
    """Se reintenta con backoff fijo si Redis no está disponible al arrancar o se cae — nunca tira
    abajo la app: si Redis nunca vuelve, el canal simplemente no emite nada más.

    Usa `get_redis_pubsub_client()` (conexión dedicada, `socket_timeout=None`) y NO el `get_redis()`
    compartido: el `socket_timeout=10` de ese último está calibrado para el `BLPOP` del worker y
    convertía cada 10s de silencio genuino del canal en un `TimeoutError` → desconexión →
    resuscripción, dejando el canal sin suscriptores ~5s de cada ~15s (medido en dev con
    `PUBSUB NUMSUB`). Todo lo publicado en esas ventanas se perdía: pub/sub es fire-and-forget.
    Los fallos reales (Redis caído, conexión cerrada por el server) siguen cayendo en el `except` de
    abajo con su reintento — sólo se eliminó el disparador FALSO."""
    while True:
        pubsub = None
        try:
            client = get_redis_pubsub_client()
            pubsub = client.pubsub()
            await pubsub.subscribe(ADMIN_NOTIFICATIONS_CHANNEL)
            logger.info("action=admin_ws_subscriber evento=suscripto canal=%s", ADMIN_NOTIFICATIONS_CHANNEL)
            async for mensaje in pubsub.listen():
                if mensaje.get("type") != "message":
                    continue
                try:
                    data = json.loads(mensaje["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("action=admin_ws_subscriber evento=mensaje_invalido")
                    continue
                await manager.broadcast(data)
        except asyncio.CancelledError:
            await _cerrar_pubsub(pubsub)
            raise
        except Exception:  # noqa: BLE001 - Redis caído/reconectando: loguear y reintentar
            logger.warning("action=admin_ws_subscriber evento=error_reintentando", exc_info=True)
            # Devolver la conexión al pool antes de reintentar: `PubSub.__del__` no la libera (sólo
            # desregistra el callback de reconexión), así que abandonar el objeto en cada reintento
            # iría dejando conexiones colgadas en el pool.
            await _cerrar_pubsub(pubsub)
            await asyncio.sleep(5)


def mount_admin_websocket(app: FastAPI, *, allowed_origins: list[str], logger: logging.Logger) -> None:
    router = APIRouter()
    manager = ConnectionManager()
    ws_logger = logger.getChild("admin_ws")
    app.state.admin_ws_manager = manager

    @router.websocket("/ws/admin-notifications")
    async def admin_notifications_endpoint(websocket: WebSocket) -> None:
        try:
            username = await _get_admin_identity(websocket, allowed_origins)
        except PermissionError as exc:
            await websocket.accept()
            ws_logger.warning("action=admin_ws_unauthorized reason=%s", exc)
            await websocket.close(code=4401, reason="No autorizado")
            return

        await websocket.accept()
        manager.register(websocket)
        ws_logger.info("action=admin_ws_connected user=%s", username)
        try:
            while True:
                await websocket.receive_text()  # el cliente no manda nada; sólo detecta desconexión
        except WebSocketDisconnect:
            ws_logger.info("action=admin_ws_disconnected user=%s", username)
        finally:
            manager.unregister(websocket)

    app.include_router(router)

    @app.on_event("startup")
    async def _start_admin_ws_subscriber() -> None:
        app.state.admin_ws_subscriber_task = asyncio.create_task(_subscriber_loop(manager, ws_logger))

    @app.on_event("shutdown")
    async def _stop_admin_ws_subscriber() -> None:
        task = getattr(app.state, "admin_ws_subscriber_task", None)
        if task is not None:
            task.cancel()


__all__ = ["ConnectionManager", "mount_admin_websocket", "ADMIN_NOTIFICATIONS_CHANNEL"]
