# Nombre de archivo: test_web_chat.py
# Ubicación de archivo: tests/test_web_chat.py
# Descripción: Pruebas básicas del endpoint del chat del servicio Web

import os
from pathlib import Path
import sys

# Permite importar app.web sin necesidad de instalar el paquete
sys.path.append(str(Path(__file__).resolve().parents[1] / "web"))

from fastapi.testclient import TestClient
import pytest
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from core.chatbot import ChatOrchestrator
from core.chatbot.storage import InMemoryChatStorage
from core.mcp.registry import MCPRegistry, ToolDefinition, ToolResult
from web_app.main import app  # type: ignore[import]

client = TestClient(app)


def test_health_ok() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_chat_message_returns_json(monkeypatch) -> None:
    # Mock del clasificador para evitar IO
    async def _fake_classify(text: str):
        # Simula respuesta antigua para endpoint deprecado; el nuevo endpoint de analyze se consume internamente.
        from web_app.main import IntentResponse  # type: ignore[import]
        return IntentResponse(intent="Consulta", confidence=0.9, provider="heuristic", normalized_text=text)

    from web_app import main as web_main  # type: ignore[import]
    web_main.classify_text = _fake_classify

    res = client.post("/api/chat/message", data={"text": "¿Cómo genero el SLA?"})
    assert res.status_code == 200
    data = res.json()
    required = {"reply", "intention_raw", "intention", "confidence", "provider"}
    assert required.issubset(data.keys())
    assert data["intention_raw"] in ("Consulta", "Acción", "Otros")
    assert data["intention"] in ("Consulta/Generico", "Solicitud de acción", "Otros")


class PingArgs(BaseModel):
    texto: str | None = None


async def ping_handler(args: PingArgs, context) -> ToolResult:  # type: ignore[override]
    return ToolResult(message="pong", data={"status": "ok"})


def test_websocket_streaming_flow(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "true")
    storage = InMemoryChatStorage()
    registry = MCPRegistry()
    registry.register(
        ToolDefinition(
            name="PingTool",
            description="Respuesta básica",
            input_model=PingArgs,
            handler=ping_handler,
        )
    )
    orchestrator = ChatOrchestrator(storage=storage, registry=registry)
    previous_orchestrator = getattr(app.state, "chat_orchestrator", None)
    previous_registry = getattr(app.state, "chat_registry", None)
    app.state.chat_orchestrator = orchestrator
    app.state.chat_registry = registry

    try:
        with client.websocket_connect("/ws/chat", headers={"X-Test-User": "wsuser:admin"}) as websocket:
            initial = websocket.receive_json()
            assert initial["type"] == "history_snapshot"
            websocket.send_json({"type": "tool_call", "tool": "PingTool", "args": {}})
            events = []
            while True:
                payload = websocket.receive_json()
                events.append(payload)
                if payload.get("type") == "assistant_done":
                    break
            assert events[0]["type"] == "assistant_delta"
            assert events[-1]["type"] == "assistant_done"
            assert events[-1]["metadata"]["result"]["status"] == "ok"
    finally:
        app.state.chat_orchestrator = previous_orchestrator
        app.state.chat_registry = previous_registry


def test_websocket_without_identity_returns_4401(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "true")
    with client.websocket_connect("/ws/chat") as websocket:
        payload = websocket.receive_json()
        assert payload["type"] == "error"
        assert payload.get("metadata", {}).get("code") == "WS_UNAUTHORIZED"
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()
        assert exc_info.value.code == 4401
