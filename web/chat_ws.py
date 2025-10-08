# Nombre de archivo: chat_ws.py
# Ubicación de archivo: web/chat_ws.py
# Descripción: Configuración y endpoint WebSocket para el chatbot del panel web

from __future__ import annotations

import json
import os
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect, status

from core.chatbot import ChatMessage, ChatOrchestrator, ChatEvent, DatabaseChatStorage
from core.mcp import get_default_registry


@dataclass(slots=True)
class ChatWebSocketSettings:
    dsn: str
    allowed_origins: List[str]
    uploads_dir: str
    testing_header: str = "x-test-user"


async def _get_user_identity(websocket: WebSocket, settings: ChatWebSocketSettings) -> tuple[str, str]:
    session = getattr(websocket, "session", None) or {}
    username: Optional[str] = session.get("username") if isinstance(session, dict) else None
    role: str = session.get("role", "user") if isinstance(session, dict) else "user"

    if not username and os.getenv("TESTING", "false").lower() == "true":
        header_user = websocket.headers.get(settings.testing_header)
        if header_user:
            parts = header_user.split(":", 1)
            username = parts[0]
            if len(parts) > 1:
                role = parts[1]

    origin = websocket.headers.get("origin")
    if settings.allowed_origins and origin and origin not in settings.allowed_origins:
        raise PermissionError("Origen no autorizado")

    if not username:
        raise PermissionError("Sesión no encontrada")
    return username, role or "user"


def mount_chat_websocket(
    app: FastAPI,
    *,
    settings: ChatWebSocketSettings,
    logger: logging.Logger,
) -> None:
    router = APIRouter()
    storage = DatabaseChatStorage(settings.dsn)
    registry = get_default_registry()
    router_logger = logger.getChild("chat_ws")
    orchestrator = ChatOrchestrator(
        storage=storage,
        registry=registry,
        logger=router_logger,
        uploads_dir=settings.uploads_dir,
    )

    app.state.chat_registry = registry
    app.state.chat_orchestrator = orchestrator
    app.state.chat_settings = settings
    app.state.chat_logger = router_logger

    @router.websocket("/ws/chat")
    async def chat_endpoint(websocket: WebSocket) -> None:
        ws_logger = getattr(app.state, "chat_logger", router_logger)
        orchestrator_ref = getattr(app.state, "chat_orchestrator", orchestrator)
        try:
            username, role = await _get_user_identity(websocket, settings)
        except PermissionError as exc:
            await websocket.accept()
            ws_logger.warning(
                "action=chat_ws_unauthorized reason=%s origin=%s user_agent=%s",
                exc,
                websocket.headers.get("origin"),
                websocket.headers.get("user-agent"),
            )
            await websocket.send_json(
                {
                    "type": "error",
                    "content": "Sesión no encontrada o inaccesible",
                    "metadata": {"code": "WS_UNAUTHORIZED"},
                }
            )
            await websocket.close(code=4401, reason="No autorizado")
            return
        await websocket.accept()

        try:
            session_id = await orchestrator_ref.ensure_session(username)
            history = await orchestrator_ref.history(session_id, limit=40)
        except Exception as exc:  # noqa: BLE001
            ws_logger.exception(
                "action=chat_ws_session_error user=%s error=%s", username, exc
            )
            await websocket.send_json(
                {
                    "type": "error",
                    "content": "No se pudo inicializar la sesión de chat",
                    "metadata": {"code": "WS_SESSION_ERROR"},
                }
            )
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            return
        await websocket.send_json({"type": "history_snapshot", "messages": history})
        ws_logger.info("action=chat_ws_connected user=%s session_id=%s", username, session_id)

        try:
            while True:
                data = await websocket.receive_text()
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "content": "Mensaje inválido",
                            "metadata": {"code": "WS_BAD_REQUEST"},
                        }
                    )
                    continue
                incoming = ChatMessage(
                    type=payload.get("type", "user_message"),
                    content=payload.get("content"),
                    attachments=payload.get("attachments", []),
                    tool=payload.get("tool"),
                    args=payload.get("args"),
                )
                async for event in orchestrator_ref.handle_message(
                    user_id=username,
                    role="user",
                    session_id=session_id,
                    message=incoming,
                    user_role=role,
                ):
                    await websocket.send_json(event.to_json())
        except WebSocketDisconnect:
            ws_logger.info(
                "action=chat_ws_disconnected user=%s session_id=%s", username, session_id
            )
        except Exception as exc:  # noqa: BLE001
            ws_logger.exception(
                "action=chat_ws_error user=%s session_id=%s error=%s", username, session_id, exc
            )
            await websocket.send_json(
                {
                    "type": "error",
                    "content": "Ocurrió un error en el servidor",
                    "metadata": {"code": "WS_INTERNAL_ERROR"},
                }
            )
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)

    app.include_router(router)


__all__ = ["ChatWebSocketSettings", "mount_chat_websocket"]
