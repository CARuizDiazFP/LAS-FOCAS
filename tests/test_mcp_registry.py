# Nombre de archivo: test_mcp_registry.py
# Ubicación de archivo: tests/test_mcp_registry.py
# Descripción: Pruebas para el registro e invocación de herramientas MCP

from __future__ import annotations

import pytest
from pydantic import BaseModel

from core.mcp.registry import MCPRegistry, ToolContext, ToolDefinition, ToolInvocationError, ToolResult


class EchoArgs(BaseModel):
    texto: str


async def echo_handler(args: EchoArgs, context: ToolContext) -> ToolResult:
    return ToolResult(message=f"echo:{args.texto}", data={"session": context.session_id})


def test_registry_prevents_duplicates() -> None:
    registry = MCPRegistry()
    registry.register(
        ToolDefinition(
            name="Echo",
            description="Devuelve el mismo texto",
            input_model=EchoArgs,
            handler=echo_handler,
        )
    )
    with pytest.raises(ValueError):
        registry.register(
            ToolDefinition(
                name="Echo",
                description="Duplicado",
                input_model=EchoArgs,
                handler=echo_handler,
            )
        )


@pytest.mark.asyncio
async def test_registry_validates_arguments() -> None:
    registry = MCPRegistry()
    registry.register(
        ToolDefinition(
            name="Echo",
            description="Devuelve el mismo texto",
            input_model=EchoArgs,
            handler=echo_handler,
        )
    )
    context = ToolContext(user_id="alice", session_id=1)
    result = await registry.invoke("Echo", {"texto": "hola"}, context)
    assert result.message == "echo:hola"

    with pytest.raises(ToolInvocationError):
        await registry.invoke("Echo", {"texto": 123}, context)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_registry_enforces_roles() -> None:
    registry = MCPRegistry()
    registry.register(
        ToolDefinition(
            name="AdminEcho",
            description="Echo restringido",
            input_model=EchoArgs,
            handler=echo_handler,
            roles=["admin"],
        )
    )
    admin_context = ToolContext(user_id="root", session_id=10, role="admin")
    result = await registry.invoke("AdminEcho", {"texto": "root"}, admin_context)
    assert result.message == "echo:root"

    user_context = ToolContext(user_id="bob", session_id=11, role="user")
    with pytest.raises(ToolInvocationError) as exc_info:
        await registry.invoke("AdminEcho", {"texto": "bob"}, user_context)
    assert exc_info.value.code == "TOOL_FORBIDDEN"
