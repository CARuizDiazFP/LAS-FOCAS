# Nombre de archivo: slack_gateway.py
# Ubicación de archivo: core/services/fo_monitor/slack_gateway.py
# Descripción: Acceso mínimo a Slack para FO Monitor (publicar, leer hilo, permalink, buscar token) con WebClient

"""Puerta a Slack de FO Monitor.

Sólo `WebClient` con el bot token: el worker NUNCA abre Socket Mode con el app token del listener
de ingresos, porque Slack repartiría los eventos entre las dos conexiones y el listener perdería
mensajes. Las respuestas de burritoIA se leen con `conversations.replies` (polling); los scopes
`chat:write` + `channels:history`/`groups:history` ya los tienen las apps dev y prod.

`SlackGateway` es el protocolo que usa `motor.py`; los tests le pasan un fake en memoria.
"""

from __future__ import annotations

import re
from typing import Optional, Protocol

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler


class SlackGateway(Protocol):
    def publicar(self, canal: str, texto: str, thread_ts: Optional[str] = None) -> str: ...

    def respuestas(self, canal: str, ts: str) -> list[dict]: ...

    def permalink(self, canal: str, ts: str) -> Optional[str]: ...

    def buscar_token(self, canal: str, token: str, desde_epoch: float) -> Optional[str]: ...


class SlackGatewayWebClient:
    def __init__(self, token: str) -> None:
        self._client = WebClient(token=token, timeout=30)
        self._client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))

    def publicar(self, canal: str, texto: str, thread_ts: Optional[str] = None) -> str:
        resp = self._client.chat_postMessage(
            channel=canal, text=texto, thread_ts=thread_ts, unfurl_links=False, unfurl_media=False
        )
        return resp["ts"]

    def respuestas(self, canal: str, ts: str) -> list[dict]:
        resp = self._client.conversations_replies(channel=canal, ts=ts, limit=200)
        return list(resp.get("messages", []))[1:]  # el primero es el mensaje raíz

    def permalink(self, canal: str, ts: str) -> Optional[str]:
        try:
            return self._client.chat_getPermalink(channel=canal, message_ts=ts).get("permalink")
        except SlackApiError:
            return None

    def buscar_token(self, canal: str, token: str, desde_epoch: float) -> Optional[str]:
        patron = re.compile(re.escape(token) + r"(?!\d)")  # FOMON-Q1 no debe matchear FOMON-Q12
        resp = self._client.conversations_history(channel=canal, oldest=f"{desde_epoch:.6f}", limit=200)
        for m in resp.get("messages", []):
            if patron.search(m.get("text") or ""):
                return m.get("ts")
        return None
