# Nombre de archivo: test_chat_orchestrator.py
# Ubicación de archivo: tests/test_chat_orchestrator.py
# Descripción: Pruebas unitarias para el orquestador del chatbot web

from __future__ import annotations

import pytest
from pydantic import BaseModel

from core.chatbot import ChatMessage, ChatOrchestrator
from core.chatbot.storage import InMemoryChatStorage
from core.mcp.registry import MCPRegistry, ToolDefinition, ToolResult, ToolInvocationError


class DummyArgs(BaseModel):
    texto: str = "hola"


async def dummy_handler(args: DummyArgs, context) -> ToolResult:  # type: ignore[override]
    return ToolResult(message=f"dummy:{args.texto}")


class ErrorArgs(BaseModel):
    pass


async def failing_handler(args: ErrorArgs, context) -> ToolResult:  # type: ignore[override]
    raise ToolInvocationError("TOOL_FAIL", "No se pudo completar la herramienta")


class AttachmentArgs(BaseModel):
    flag: str = "ok"


async def attachment_handler(args: AttachmentArgs, context) -> ToolResult:  # type: ignore[override]
    return ToolResult(message="attachments-ok", data={"status": "ok"})


@pytest.mark.asyncio
async def test_tool_call_generates_assistant_done() -> None:
    storage = InMemoryChatStorage()
    registry = MCPRegistry()
    registry.register(
        ToolDefinition(
            name="DummyTool",
            description="Respuesta placeholder",
            input_model=DummyArgs,
            handler=dummy_handler,
        )
    )
    orchestrator = ChatOrchestrator(storage=storage, registry=registry)
    session_id = await orchestrator.ensure_session("alice")
    message = ChatMessage(type="tool_call", tool="DummyTool", args={"texto": "mundo"})

    events = []
    async for event in orchestrator.handle_message(
        user_id="alice",
        role="user",
        session_id=session_id,
        message=message,
    ):
        events.append(event)

    assert any(evt.type == "assistant_done" for evt in events)
    history = await orchestrator.history(session_id)
    assert history[-1]["content"].startswith("dummy:")


@pytest.mark.asyncio
async def test_plain_text_message_returns_helper_text() -> None:
    storage = InMemoryChatStorage()
    registry = MCPRegistry()
    orchestrator = ChatOrchestrator(storage=storage, registry=registry)
    session_id = await orchestrator.ensure_session("bob")
    message = ChatMessage(type="user_message", content="hola")

    events = []
    async for event in orchestrator.handle_message(
        user_id="bob",
        role="user",
        session_id=session_id,
        message=message,
    ):
        events.append(event)

    assert any(evt.type == "assistant_done" for evt in events)
    history = await orchestrator.history(session_id)
    assert any("/repetitividad" in record["content"] for record in history if record["role"] == "assistant")


@pytest.mark.asyncio
async def test_empty_message_rejected_and_not_persisted() -> None:
    storage = InMemoryChatStorage()
    registry = MCPRegistry()
    orchestrator = ChatOrchestrator(storage=storage, registry=registry)
    session_id = await orchestrator.ensure_session("charlie")
    message = ChatMessage(type="user_message", content="   ")

    events = []
    async for event in orchestrator.handle_message(
        user_id="charlie",
        role="user",
        session_id=session_id,
        message=message,
    ):
        events.append(event)

    assert events and events[0].type == "error"
    assert events[0].metadata.get("code") == "WS_BAD_REQUEST"
    history = await orchestrator.history(session_id)
    assert len(history) == 1
    assert history[0]["role"] == "assistant"
    assert history[0]["error_code"] == "WS_BAD_REQUEST"


@pytest.mark.asyncio
async def test_tool_error_emits_error_event_and_persists_code() -> None:
    storage = InMemoryChatStorage()
    registry = MCPRegistry()
    registry.register(
        ToolDefinition(
            name="FailingTool",
            description="Falla controlada",
            input_model=ErrorArgs,
            handler=failing_handler,
        )
    )
    orchestrator = ChatOrchestrator(storage=storage, registry=registry)
    session_id = await orchestrator.ensure_session("dana")
    message = ChatMessage(type="tool_call", tool="FailingTool", args={})

    events = []
    async for event in orchestrator.handle_message(
        user_id="dana",
        role="user",
        session_id=session_id,
        message=message,
    ):
        events.append(event)

    assert any(evt.type == "error" and evt.metadata.get("code") == "TOOL_FAIL" for evt in events)
    history = await orchestrator.history(session_id)
    assert history[-1]["error_code"] == "TOOL_FAIL"


@pytest.mark.asyncio
async def test_attachment_sanitization_filters_traversal() -> None:
    storage = InMemoryChatStorage()
    registry = MCPRegistry()
    registry.register(
        ToolDefinition(
            name="AttachmentTool",
            description="Adjuntos",
            input_model=AttachmentArgs,
            handler=attachment_handler,
        )
    )
    orchestrator = ChatOrchestrator(
        storage=storage,
        registry=registry,
        uploads_dir="/safe/uploads",
    )
    session_id = await orchestrator.ensure_session("eve")
    message = ChatMessage(
        type="tool_call",
        tool="AttachmentTool",
        args={},
        attachments=[{"path": "../secret.txt"}, {"path": "valid.xlsx"}],
    )

    events = []
    async for event in orchestrator.handle_message(
        user_id="eve",
        role="user",
        session_id=session_id,
        message=message,
    ):
        events.append(event)

    assert any(evt.type == "assistant_done" for evt in events)
    history = await orchestrator.history(session_id)
    tool_entries = [row for row in history if row["role"] == "tool"]
    assert tool_entries
    assert tool_entries[0]["attachments"] == [{"path": "valid.xlsx"}]
