# Nombre de archivo: intent.py
# Ubicación de archivo: bot_telegram/handlers/intent.py
# Descripción: Manejo de mensajes de texto con clasificación de intención y persistencia

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict

import httpx
import psycopg
try:  # Permitir importar el módulo aunque aiogram no esté instalado en el entorno de pruebas
    from aiogram import F, Router  # type: ignore
    from aiogram.fsm.context import FSMContext  # type: ignore
    from aiogram.types import Message  # type: ignore
    _AI_AVAILABLE = True
except Exception:  # pragma: no cover - entorno sin aiogram
    _AI_AVAILABLE = False

    class _Dummy:
        def __getattr__(self, _):
            return self

        def __call__(self, *_, **__):
            return self

    class DummyRouter:
        def message(self, *_, **__):
            def _decorator(func):
                return func

            return _decorator

    F = _Dummy()  # type: ignore
    Router = DummyRouter  # type: ignore
    class FSMContext:  # type: ignore
        pass
    class Message:  # type: ignore
        pass

from bot_telegram.flows.repetitividad import start_repetitividad_flow
from bot_telegram.flows.sla import start_sla_flow
from bot_telegram.ui.menu import build_main_menu
from core.repositories.conversations import insert_conversation
from core.repositories.messages import insert_message

router = Router() if _AI_AVAILABLE else Router()
logger = logging.getLogger(__name__)
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


def _has_menu_keyword(text: str) -> bool:
    """Verifica si el texto normalizado solicita abrir el menú."""
    lowered = text.lower()
    return "menu" in lowered or "menú" in lowered


@router.message(F.text)
async def classify_message(msg: Message, state: FSMContext):
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
    elif data["intent"] == "Acción" and _has_menu_keyword(data["normalized_text"]):
        logger.info("Usuario %s abrió el menú por intención", user_id)
        await msg.answer("Seleccioná una opción:", reply_markup=build_main_menu())
    elif data["intent"] == "Acción":
        normalized = data["normalized_text"].lower()
        if "sla" in normalized:
            await start_sla_flow(msg, state, origin="intent")
        elif "repetitividad" in normalized:
            await start_repetitividad_flow(msg, state, origin="intent")
        else:
            await msg.answer(
                "📋 Acción detectada. Implementación pendiente. En breve se habilitará este flujo.\n"
                + summary
            )
    else:
        await msg.answer(summary)


