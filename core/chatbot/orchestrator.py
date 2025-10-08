# Nombre de archivo: orchestrator.py
# Ubicación de archivo: core/chatbot/orchestrator.py
# Descripción: Orquestador principal del chatbot del panel web y manejo de streaming

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from core.mcp import MCPRegistry, ToolContext, ToolRequest, ToolResult, ToolInvocationError

from .storage import ChatStorage


@dataclass(slots=True)
class ChatMessage:
    """Representa un mensaje entrante desde el cliente."""

    type: str
    content: Optional[str] = None
    attachments: Optional[List[Dict[str, Any]]] = None
    tool: Optional[str] = None
    args: Optional[Dict[str, Any]] = None


@dataclass(slots=True)
class ChatEvent:
    """Evento que se emite hacia el WebSocket del cliente."""

    type: str
    content: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"type": self.type}
        if self.content is not None:
            payload["content"] = self.content
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


class ChatOrchestrator:
    """Contenedor que recibe mensajes, elige estrategia y produce deltas en streaming."""

    def __init__(
        self,
        storage: ChatStorage,
        registry: MCPRegistry,
        logger: Optional[logging.Logger] = None,
        uploads_dir: str | Path | None = None,
    ) -> None:
        self._storage = storage
        self._registry = registry
        self._logger = logger or logging.getLogger(__name__)
        self._uploads_dir = Path(uploads_dir) if uploads_dir else None

    async def ensure_session(self, user_id: str) -> int:
        return await self._storage.ensure_session(user_id)

    async def history(self, session_id: int, limit: int = 40) -> List[Dict[str, Any]]:
        return await self._storage.list_messages(session_id, limit)

    async def handle_message(
        self,
        *,
        user_id: str,
        role: str,
        session_id: int,
        message: ChatMessage,
        user_role: str = "user",
    ) -> AsyncGenerator[ChatEvent, None]:
        if message.type == "user_message":
            async for event in self._handle_user_text(user_id=user_id, session_id=session_id, message=message):
                yield event
        elif message.type == "tool_call":
            async for event in self._handle_explicit_tool_call(user_id=user_id, session_id=session_id, message=message, user_role=user_role):
                yield event
        else:
            self._logger.warning("action=chat_unknown_message_type type=%s user_id=%s", message.type, user_id)
            yield ChatEvent(
                type="error",
                content="Tipo de mensaje no soportado",
                metadata={"code": "WS_BAD_REQUEST"},
            )

    async def _handle_user_text(
        self,
        *,
        user_id: str,
        session_id: int,
        message: ChatMessage,
    ) -> AsyncGenerator[ChatEvent, None]:
        content = (message.content or "").strip()
        attachments = message.attachments or []
        attachments = self._sanitize_attachments(message.attachments or [])
        if not content and not attachments:
            yield ChatEvent(
                type="error",
                content="Necesito un mensaje o adjunto para continuar",
                metadata={"code": "WS_BAD_REQUEST"},
            )
            await self._storage.append_message(
                session_id,
                "assistant",
                "Mensaje vacío rechazado",
                error_code="WS_BAD_REQUEST",
            )
            return

        await self._storage.append_message(
            session_id,
            "user",
            content,
            attachments=attachments,
        )
        self._logger.info(
            "action=chat_user_message user_id=%s session_id=%s chars=%s attachments=%s",
            user_id,
            session_id,
            len(content),
            len(attachments),
        )

        # Detección simple de comandos estilo /repetitividad mes=9 anio=2025
        if content.startswith("/"):
            command, tool_request = self._parse_command(content, attachments)
            if tool_request:
                async for event in self._execute_tool(user_id, session_id, tool_request):
                    yield event
                return
            if command:
                yield ChatEvent(
                    type="assistant_done",
                    content=f"Comando {command} no reconocido. Probá con /repetitividad o /comparador.",
                )
                await self._storage.append_message(
                    session_id,
                    "assistant",
                    f"Comando {command} no reconocido",
                )
                return

        # Respuesta base si no se disparó herramienta
        template = (
            "Estoy listo para ayudarte a generar informes o consultar datos. "
            "Podés usar /repetitividad o /comparador."
        )
        await self._storage.append_message(session_id, "assistant", template)
        yield ChatEvent(type="assistant_delta", content=template)
        yield ChatEvent(type="assistant_done")

    async def _handle_explicit_tool_call(
        self,
        *,
        user_id: str,
        session_id: int,
        message: ChatMessage,
        user_role: str,
    ) -> AsyncGenerator[ChatEvent, None]:
        if not message.tool:
            yield ChatEvent(
                type="error",
                content="Solicitud inválida: falta el nombre de la herramienta.",
                metadata={"code": "WS_BAD_REQUEST"},
            )
            return
        attachments = self._sanitize_attachments(message.attachments or [])
        tool_request = ToolRequest(name=message.tool, args=message.args or {}, attachments=attachments)
        async for event in self._execute_tool(user_id, session_id, tool_request, user_role=user_role):
            yield event

    def _parse_command(
        self,
        text: str,
        attachments: List[Dict[str, Any]],
    ) -> tuple[str | None, ToolRequest | None]:
        try:
            tokens = shlex.split(text)
        except ValueError:
            tokens = text.split()
        if not tokens:
            return None, None
        command = tokens[0].lstrip("/").lower()
        args_tokens = tokens[1:]
        args: Dict[str, Any] = {}
        for token in args_tokens:
            if "=" in token:
                key, value = token.split("=", 1)
                args[key.lower()] = value
        if command == "repetitividad":
            if attachments:
                args.setdefault("file_path", attachments[0].get("path"))
            return command, ToolRequest(name="GenerarInformeRepetitividad", args=args, attachments=attachments)
        if command in {"comparador", "comparadorfo", "comparador-fo"}:
            return command, ToolRequest(name="CompararTrazasFO", args=args, attachments=attachments)
        if command in {"mapa", "map"}:
            return command, ToolRequest(name="GenerarMapaGeo", args=args, attachments=attachments)
        return command, None

    async def _execute_tool(
        self,
        user_id: str,
        session_id: int,
        tool_request: ToolRequest,
        user_role: str = "user",
    ) -> AsyncGenerator[ChatEvent, None]:
        context = ToolContext(user_id=user_id, session_id=session_id, role=user_role)
        normalized_attachments = self._sanitize_attachments(tool_request.attachments)
        await self._storage.append_message(
            session_id,
            "tool",
            f"call:{tool_request.name}",
            tool_name=tool_request.name,
            tool_args=tool_request.args,
            attachments=normalized_attachments,
        )
        yield ChatEvent(
            type="assistant_delta",
            content=f"↻ Ejecutando {tool_request.name}...",
            metadata={"tool": tool_request.name},
        )
        try:
            result: ToolResult = await self._registry.invoke(tool_request.name, tool_request.args, context)
        except ToolInvocationError as exc:
            message = exc.user_message
            self._logger.warning(
                "action=chat_tool_error tool=%s user_id=%s code=%s detail=%s",
                tool_request.name,
                user_id,
                exc.code,
                exc.detail,
            )
            await self._storage.append_message(
                session_id,
                "assistant",
                message,
                tool_name=tool_request.name,
                tool_args=tool_request.args,
                attachments=normalized_attachments,
                error_code=exc.code,
            )
            yield ChatEvent(
                type="error",
                content=message,
                metadata={"code": exc.code or "WS_TOOL_ERROR"},
            )
            return

        final_message = result.message or "Operación completada."
        await self._storage.append_message(
            session_id,
            "assistant",
            final_message,
            tool_name=tool_request.name,
            tool_args=tool_request.args,
            attachments=normalized_attachments,
        )
        if result.streaming_chunks:
            for chunk in result.streaming_chunks:
                yield ChatEvent(type="assistant_delta", content=chunk, metadata=result.metadata)
        else:
            yield ChatEvent(type="assistant_delta", content=final_message, metadata=result.metadata)
        yield ChatEvent(
            type="assistant_done",
            metadata={"result": result.data, "tool": tool_request.name},
        )

    def _sanitize_attachments(self, attachments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not attachments:
            return []
        sanitized: List[Dict[str, Any]] = []
        for raw in attachments:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            path_value = item.get("path") or item.get("file_path")
            if path_value:
                path_obj = Path(path_value)
                if path_obj.is_absolute():
                    if self._uploads_dir is not None:
                        try:
                            path_obj.relative_to(self._uploads_dir)
                        except ValueError:
                            self._logger.warning(
                                "action=chat_attachment_blocked reason=absolute_outside uploads_dir=%s",
                                self._uploads_dir,
                            )
                            continue
                    item["path"] = str(path_obj)
                else:
                    if ".." in path_obj.parts:
                        self._logger.warning("action=chat_attachment_blocked reason=path_traversal")
                        continue
                    item["path"] = str(path_obj)
            sanitized.append(item)
        return sanitized


__all__ = ["ChatMessage", "ChatEvent", "ChatOrchestrator"]
