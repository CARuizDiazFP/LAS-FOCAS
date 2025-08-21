# Nombre de archivo: intent.py
# Ubicación de archivo: bot_telegram/handlers/intent.py
# Descripción: Manejo de mensajes de texto con clasificación de intención y persistencia

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict

import httpx
import psycopg
from aiogram import Router, F
from aiogram.types import Message

from core.repositories.conversations import insert_conversation
from core.repositories.messages import insert_message

router = Router()
_rate_limit: dict[int, list[float]] = defaultdict(list)
_conversations: dict[int, int] = {}


def _check_rate(user_id: int, limit: int = 20, interval: int = 60) -> bool:
    now = time.time()
    times = _rate_limit[user_id]
    times[:] = [t for t in times if now - t < interval]
    if len(times) >= limit:
        return False
    times.append(now)
    return True


def _get_conn() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


@router.message(F.text)
async def classify_message(msg: Message):
    user_id = msg.from_user.id
    if not _check_rate(user_id):
        await msg.answer("Rate limit alcanzado. Esperá un momento ⏳")
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post("http://nlp_intent:8100/v1/intent:classify", json={"text": msg.text})
        data = resp.json()

    conn = await asyncio.to_thread(_get_conn)
    conversation_id = _conversations.get(user_id)
    if conversation_id is None:
        conversation_id = await asyncio.to_thread(insert_conversation, conn, user_id)
        _conversations[user_id] = conversation_id
    await asyncio.to_thread(
        insert_message,
        conn,
        conversation_id,
        user_id,
        "user",
        msg.text,
        data["normalized_text"],
        data["intent"],
        data["confidence"],
        data["provider"],
    )
    conn.close()

    summary = f"Intención: {data['intent']} (confianza: {data['confidence']:.2f})."
    threshold = float(os.getenv("INTENT_THRESHOLD", "0.7"))
    if data["confidence"] < threshold:
        await msg.answer("No estoy 100% seguro 🤔 ¿Querías hacer una acción o consultar algo?\n" + summary)
    elif data["intent"] == "Acción":
        await msg.answer(
            "📋 Acción detectada. Implementación pendiente. En breve se habilitará este flujo.\n" + summary
        )
    else:
        await msg.answer(summary)


