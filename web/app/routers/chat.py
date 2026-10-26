# Nombre de archivo: chat.py
# Ubicación de archivo: web/app/routers/chat.py
# Descripción: Rutas HTTP del chat de la app web: mensaje, historial, adjuntos, métricas de intención e invocación MCP

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
import unicodedata
from mimetypes import guess_type
from pathlib import Path
from time import time as now
from typing import Any, Dict, List

import httpx
import psycopg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.chatbot import ChatMessage
from core.repositories.conversations import get_or_create_conversation_for_web_user
from core.repositories.messages import get_last_messages, insert_message

from .. import comun
from ..comun import DATA_DIR, DB_DSN, UPLOADS_DIR, logger
from ..dependencias import UsuarioSesion, requiere_csrf
from ..errores import ErrorDeDominio, error_interno, nueva_ref


async def usuario_chat(request: Request) -> UsuarioSesion:
    """Sesión del chat; 401 `{"error": "No autenticado"}` (el cuerpo que el chat respondía y la SPA muestra).

    Reutiliza `comun._require_auth` (única fuente de la regla de sesión) y traduce su 401 a
    `ErrorDeDominio` para conservar la clave `error` en lugar del `detail` de `HTTPException`.
    """
    try:
        username, role = comun._require_auth(request)
    except HTTPException as exc:
        raise ErrorDeDominio("No autenticado", status_code=exc.status_code) from None
    return UsuarioSesion(username, role)


# Ninguna ruta del chat es pública (el WebSocket vive aparte, en web/chat_ws.py).
router = APIRouter(dependencies=[Depends(usuario_chat), Depends(requiere_csrf)])

NLP_INTENT_URL = os.getenv("NLP_INTENT_URL", "http://nlp_intent:8100")
LOG_RAW_TEXT = os.getenv("LOG_RAW_TEXT", "false").lower() == "true"

# Métricas simples en memoria (MVP) con persistencia opcional
INTENT_COUNTER: dict[str, int] = {"Solicitud de acción": 0, "Consulta/Generico": 0, "Otros": 0}
METRICS_PERSIST_PATH: str | None = None

def _load_metrics() -> None:
    if not METRICS_PERSIST_PATH:
        return
    try:
        p = Path(METRICS_PERSIST_PATH)
        if p.exists():
            data = json.loads(p.read_text())
            if isinstance(data, dict):
                for k, v in data.items():
                    if k in INTENT_COUNTER and isinstance(v, int):
                        INTENT_COUNTER[k] = v
    except Exception as exc:  # noqa: BLE001
        logger.warning("action=metrics_load error=%s", exc)

def _persist_metrics() -> None:
    if not METRICS_PERSIST_PATH:
        return
    try:
        p = Path(METRICS_PERSIST_PATH)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(INTENT_COUNTER, ensure_ascii=False))
        tmp.replace(p)
    except Exception as exc:  # noqa: BLE001
        logger.warning("action=metrics_persist error=%s", exc)

MAX_CHAT_UPLOAD_BYTES = int(os.getenv("CHAT_UPLOAD_MAX_BYTES", str(15 * 1024 * 1024)))
ALLOWED_CHAT_EXTENSIONS = {
    ".xlsx",
    ".xlsm",
    ".csv",
    ".txt",
    ".json",
    ".pdf",
    ".docx",
}
ALLOWED_CHAT_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
    "application/json",
    "text/plain",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
if METRICS_PERSIST_PATH is None:
    METRICS_PERSIST_PATH = os.getenv("METRICS_PERSIST_PATH", str(DATA_DIR / "intent_metrics.json"))
_load_metrics()


class MCPInvokeRequest(BaseModel):
    tool: str = Field(..., description="Nombre de la herramienta MCP")
    args: Dict[str, Any] = Field(default_factory=dict, description="Argumentos para la herramienta")
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="Adjuntos opcionales")


@router.post("/api/chat/message")
async def chat_message(
    request: Request,
    text: str = Form(...),
    usuario: UsuarioSesion = Depends(usuario_chat),
) -> JSONResponse:
    """
    Recibe un mensaje del usuario (form-data o x-www-form-urlencoded) y
    devuelve intención y una respuesta simple.
    """
    # Rate limit simple del chat: 30 req/min por sesión
    rl = request.session.get("rl_chat", {"count": 0, "ts": now()})
    if now() - rl["ts"] > 60:
        rl = {"count": 0, "ts": now()}
    rl["count"] += 1
    request.session["rl_chat"] = rl
    if rl["count"] > 30:
        return JSONResponse({"error": "Rate limit excedido"}, status_code=429)
    # Sanitizar entrada (remover caracteres de control invisibles excepto \n y \t)
    def _sanitize(t: str) -> str:
        return "".join(ch for ch in t if unicodedata.category(ch)[0] != "C" or ch in ("\n", "\t")).strip()
    text = _sanitize(text)

    # Clasificación enriquecida (nuevo pipeline)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{NLP_INTENT_URL}/v1/intent:analyze", json={"text": text})
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001
        # Fallback muy básico si falla el servicio de NLP
        data = {
            "intention_raw": "Otros",
            "intention": "Otros",
            "confidence": 0.0,
            "provider": "none",
            "normalized_text": text,
            "need_clarification": True,
            "clarification_question": "¿Podrías dar más detalles?",
            "next_action": None,
        }

    # Respuesta placeholder diferenciada por intención mapeada
    if data["intention"] == "Solicitud de acción":
        if data.get("action_supported") and data.get("action_code") == "repetitividad_report":
            reply = "Puedo generar el informe de repetitividad. Decime el período (mes y año) o cargá el archivo para continuar."
        else:
            reply = "Por ahora solo puedo ayudar con el informe de repetitividad. ¿Querés generar ese informe?"
    elif data["intention"] == "Consulta/Generico":
        reply = data.get("answer") or "Estoy preparando una respuesta dentro del dominio de red..."
    else:
        reply = data.get("clarification_question") or "¿Podrías ampliar un poco más?"

    payload = {"reply": reply, **data}

    # Persistencia de memoria conversacional
    user = usuario.username

    def _persistir() -> tuple[Any, Any]:
        # Sync (psycopg): corre en un hilo para no frenar el event loop.
        with psycopg.connect(DB_DSN) as conn:
            conv_id = get_or_create_conversation_for_web_user(conn, user)
            # Guardar mensaje usuario
            insert_message(
                conn,
                conv_id,
                0,  # pseudo user id ya almacenado en conversation; aquí no crítico
                "user",
                text,
                data.get("normalized_text", text),
                data.get("intention_raw", data.get("intention", "Otros")),
                data.get("confidence", 0.0),
                data.get("provider", "none"),
            )
            # Guardar respuesta asistente (sin volver a clasificar)
            insert_message(
                conn,
                conv_id,
                0,
                "assistant",
                reply,
                reply.lower(),
                data.get("intention_raw", data.get("intention", "Otros")),
                data.get("confidence", 0.0),
                data.get("provider", "none"),
            )
            # Adjuntar últimos mensajes para el cliente (opcional)
            return conv_id, get_last_messages(conn, conv_id, limit=6)

    try:
        conv_id, history = await asyncio.to_thread(_persistir)
        payload["conversation_id"] = conv_id
        payload["history"] = history
    except Exception as exc:  # noqa: BLE001
        logger.warning("action=chat_persist error=%s", exc)
    # Métricas
    mapped = data.get("intention") or data.get("intent")
    if mapped in INTENT_COUNTER:
        INTENT_COUNTER[mapped] += 1
        _persist_metrics()
    # Logging prudente: opcionalmente no incluir el texto completo
    if LOG_RAW_TEXT:
        payload["user_text"] = text

    return JSONResponse(payload)


@router.get("/api/chat/history")
def chat_history(limit: int = 20, usuario: UsuarioSesion = Depends(usuario_chat)) -> JSONResponse:
    user = usuario.username
    if limit > 100:
        limit = 100
    try:
        with psycopg.connect(DB_DSN) as conn:
            conv_id = get_or_create_conversation_for_web_user(conn, user)
            history = get_last_messages(conn, conv_id, limit=limit)
            return JSONResponse({"conversation_id": conv_id, "messages": history})
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        # El texto `action=chat_history` no termina en `_error`: se conserva y gana la ref.
        ref = nueva_ref()
        logger.warning("action=chat_history error=%s ref=%s", exc, ref)
        return JSONResponse({"error": f"Error interno (ref {ref})"}, status_code=500)


@router.post("/api/chat/uploads")
async def chat_upload_attachment(
    request: Request,
    file: UploadFile = File(...),
    usuario: UsuarioSesion = Depends(usuario_chat),
) -> JSONResponse:
    username = usuario.username
    if not file.filename:
        return JSONResponse({"error": "Archivo sin nombre"}, status_code=400)
    safe_name = Path(file.filename).name
    ext = Path(safe_name).suffix.lower()
    raw_content_type = file.content_type or guess_type(safe_name)[0]
    normalized_content_type = (raw_content_type or "").lower()

    if ext not in ALLOWED_CHAT_EXTENSIONS:
        logger.warning(
            "action=chat_upload_blocked reason=extension user=%s filename=%s",
            username,
            safe_name,
        )
        return JSONResponse({"error": "Extensión de archivo no permitida"}, status_code=415)
    if normalized_content_type and normalized_content_type not in ALLOWED_CHAT_MIME_TYPES:
        logger.warning(
            "action=chat_upload_blocked reason=mime user=%s filename=%s content_type=%s",
            username,
            safe_name,
            raw_content_type,
        )
        return JSONResponse({"error": "Tipo de archivo no permitido"}, status_code=415)
    token = secrets.token_urlsafe(6)
    stored_name = f"chat_{int(time.time())}_{token}_{safe_name}"
    dest = UPLOADS_DIR / stored_name
    size = 0
    try:
        with dest.open("wb") as buffer:
            while True:
                chunk = await file.read(512 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_CHAT_UPLOAD_BYTES:
                    buffer.close()
                    dest.unlink(missing_ok=True)
                    return JSONResponse({"error": "Adjunto supera el límite permitido"}, status_code=413)
                buffer.write(chunk)
    finally:
        await file.close()
    logger.info(
        "action=chat_upload user=%s filename=%s size_bytes=%s stored=%s",
        username,
        safe_name,
        size,
        stored_name,
    )
    return JSONResponse(
        {
            "status": "ok",
            "name": safe_name,
            "path": stored_name,
            "size": size,
            "content_type": raw_content_type,
        }
    )


@router.get("/api/chat/metrics")
async def chat_metrics() -> JSONResponse:
    return JSONResponse({"intent_counts": INTENT_COUNTER})


@router.get("/api/chat/ws-history")
async def chat_ws_history(
    request: Request, limit: int = 40, usuario: UsuarioSesion = Depends(usuario_chat)
) -> JSONResponse:
    user = usuario.username
    orchestrator = getattr(request.app.state, "chat_orchestrator", None)
    if orchestrator is None:
        return JSONResponse({"error": "Chat no disponible"}, status_code=503)
    if limit > 100:
        limit = 100
    session_id = await orchestrator.ensure_session(user)
    history = await orchestrator.history(session_id, limit)
    return JSONResponse({"session_id": session_id, "messages": history})


@router.post("/mcp/invoke")
async def mcp_invoke(
    request: Request, payload: MCPInvokeRequest, usuario: UsuarioSesion = Depends(usuario_chat)
) -> JSONResponse:
    user, role = usuario
    orchestrator = getattr(request.app.state, "chat_orchestrator", None)
    if orchestrator is None:
        return JSONResponse({"error": "Chat no disponible"}, status_code=503)
    session_id = await orchestrator.ensure_session(user)
    events: List[Dict[str, Any]] = []
    logger.info(
        "action=mcp_http_invoke user=%s role=%s tool=%s session_id=%s",
        user,
        role,
        payload.tool,
        session_id,
    )
    incoming = ChatMessage(
        type="tool_call",
        tool=payload.tool,
        args=payload.args,
        attachments=payload.attachments,
    )
    try:
        async for event in orchestrator.handle_message(
            user_id=user,
            role="user",
            session_id=session_id,
            message=incoming,
            user_role=role,
        ):
            events.append(event.to_json())
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno(
            "mcp_http_invoke",
            exc,
            cuerpo={"status": "error", "message": "Fallo ejecutando la herramienta"},
            user=user,
            session_id=session_id,
            tool=payload.tool,
        )
    return JSONResponse({"status": "ok", "events": events})
