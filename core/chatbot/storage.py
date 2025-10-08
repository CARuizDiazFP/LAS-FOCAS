# Nombre de archivo: storage.py
# Ubicación de archivo: core/chatbot/storage.py
# Descripción: Persistencia para sesiones y mensajes del chatbot del panel web

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol

import psycopg


class ChatStorage(Protocol):
    """Contrato para la capa de persistencia del chatbot."""

    async def ensure_session(self, user_id: str) -> int:
        """Devuelve una sesión activa para el usuario, creándola si es necesario."""

    async def append_message(
        self,
        session_id: int,
        role: str,
        content: str,
        *,
        tool_name: str | None = None,
        tool_args: Dict[str, Any] | None = None,
        attachments: List[Dict[str, Any]] | None = None,
        error_code: str | None = None,
    ) -> int:
        """Almacena un mensaje asociado a la sesión."""

    async def list_messages(self, session_id: int, limit: int = 40) -> List[Dict[str, Any]]:
        """Obtiene los últimos mensajes de la sesión (ordenados por creación ascendente)."""


@dataclass
class DatabaseChatStorage(ChatStorage):
    """Persistencia basada en PostgreSQL (sincrónica encapsulada en hilos)."""

    dsn: str

    async def ensure_session(self, user_id: str) -> int:
        return await asyncio.to_thread(self._ensure_session_sync, user_id)

    async def append_message(
        self,
        session_id: int,
        role: str,
        content: str,
        *,
        tool_name: str | None = None,
        tool_args: Dict[str, Any] | None = None,
        attachments: List[Dict[str, Any]] | None = None,
        error_code: str | None = None,
    ) -> int:
        return await asyncio.to_thread(
            self._append_message_sync,
            session_id,
            role,
            content,
            tool_name,
            tool_args,
            attachments,
            error_code,
        )

    async def list_messages(self, session_id: int, limit: int = 40) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._list_messages_sync, session_id, limit)

    # --- Métodos privados sincrónicos -------------------------------------------------

    def _ensure_session_sync(self, user_id: str) -> int:
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:  # type: ignore[assignment]
            cur.execute(
                """
                SELECT id FROM app.chat_sessions
                WHERE user_id = %s AND is_active IS TRUE
                ORDER BY last_activity DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if row:
                session_id = int(row[0])
                cur.execute(
                    "UPDATE app.chat_sessions SET last_activity = NOW() WHERE id = %s",
                    (session_id,),
                )
                conn.commit()
                return session_id
            cur.execute(
                """
                INSERT INTO app.chat_sessions (user_id, is_active, created_at, last_activity)
                VALUES (%s, TRUE, NOW(), NOW())
                RETURNING id
                """,
                (user_id,),
            )
            session_id = int(cur.fetchone()[0])
            conn.commit()
            return session_id

    def _append_message_sync(
        self,
        session_id: int,
        role: str,
        content: str,
        tool_name: str | None,
        tool_args: Dict[str, Any] | None,
        attachments: List[Dict[str, Any]] | None,
        error_code: str | None,
    ) -> int:
        payload_tool_args = json.dumps(tool_args, ensure_ascii=False) if tool_args else None
        payload_attachments = json.dumps(attachments, ensure_ascii=False) if attachments else None
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:  # type: ignore[assignment]
            cur.execute(
                """
                INSERT INTO app.chat_messages (
                    session_id,
                    role,
                    content,
                    tool_name,
                    tool_args,
                    attachments,
                    error_code,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, NOW())
                RETURNING id
                """,
                (
                    session_id,
                    role,
                    content,
                    tool_name,
                    payload_tool_args,
                    payload_attachments,
                    error_code,
                ),
            )
            message_id = int(cur.fetchone()[0])
            cur.execute(
                "UPDATE app.chat_sessions SET last_activity = NOW() WHERE id = %s",
                (session_id,),
            )
            conn.commit()
            return message_id

    def _list_messages_sync(self, session_id: int, limit: int) -> List[Dict[str, Any]]:
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:  # type: ignore[assignment]
            cur.execute(
                """
                SELECT id, role, content, tool_name, tool_args, attachments, error_code, created_at
                FROM app.chat_messages
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (session_id, limit),
            )
            rows = cur.fetchall()
        result: List[Dict[str, Any]] = []
        for row in reversed(rows):
            tool_args = json.loads(row[4]) if row[4] else None
            attachments = json.loads(row[5]) if row[5] else None
            result.append(
                {
                    "id": int(row[0]),
                    "role": row[1],
                    "content": row[2],
                    "tool_name": row[3],
                    "tool_args": tool_args,
                    "attachments": attachments,
                    "error_code": row[6],
                    "created_at": row[7].isoformat() if row[7] else None,
                }
            )
        return result


@dataclass
class InMemoryChatStorage(ChatStorage):
    """Implementación en memoria útil para pruebas unitarias."""

    _sessions: Dict[str, int]
    _messages: Dict[int, List[Dict[str, Any]]]

    def __init__(self) -> None:
        self._sessions = {}
        self._messages = {}
        self._counter = 0
        self._session_counter = 0

    async def ensure_session(self, user_id: str) -> int:
        if user_id not in self._sessions:
            self._session_counter += 1
            self._sessions[user_id] = self._session_counter
            self._messages[self._session_counter] = []
        return self._sessions[user_id]

    async def append_message(
        self,
        session_id: int,
        role: str,
        content: str,
        *,
        tool_name: str | None = None,
        tool_args: Dict[str, Any] | None = None,
        attachments: List[Dict[str, Any]] | None = None,
        error_code: str | None = None,
    ) -> int:
        self._counter += 1
        entry = {
            "id": self._counter,
            "role": role,
            "content": content,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "attachments": attachments,
            "error_code": error_code,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._messages.setdefault(session_id, []).append(entry)
        return self._counter

    async def list_messages(self, session_id: int, limit: int = 40) -> List[Dict[str, Any]]:
        return self._messages.get(session_id, [])[-limit:]


__all__ = [
    "ChatStorage",
    "DatabaseChatStorage",
    "InMemoryChatStorage",
]
