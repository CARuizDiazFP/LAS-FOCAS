# Nombre de archivo: __init__.py
# Ubicación de archivo: core/mcp/__init__.py
# Descripción: Paquete para capa MCP y registro de herramientas del chatbot

"""Registro y utilidades para herramientas expuestas vía Model Context Protocol."""

from .registry import MCPRegistry, ToolContext, ToolInvocationError, ToolRequest, ToolResult, get_default_registry

__all__ = [
    "MCPRegistry",
    "ToolContext",
    "ToolInvocationError",
    "ToolRequest",
    "ToolResult",
    "get_default_registry",
]
