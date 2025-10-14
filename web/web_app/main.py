# Nombre de archivo: main.py
# Ubicación de archivo: web/web_app/main.py
# Descripción: Aplicación FastAPI para la UI (página dark, barra y chat REST)

from __future__ import annotations

import asyncio
import os
import secrets
import time
import zipfile
from dataclasses import dataclass
from time import time as now
from typing import Any, Dict, List

import httpx
from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from core.logging import setup_logging
from core.password import hash_password, verify_password
from core.repositories.conversations import get_or_create_conversation_for_web_user
from core.repositories.messages import insert_message, get_last_messages
from core.chatbot import ChatMessage
from web.chat_ws import ChatWebSocketSettings, mount_chat_websocket
import psycopg
from pathlib import Path
import shutil
from mimetypes import guess_type
from fastapi import UploadFile, File
import unicodedata
import json
import pandas as pd

# Configuración básica
NLP_INTENT_URL = os.getenv("NLP_INTENT_URL", "http://nlp_intent:8100")
LOG_RAW_TEXT = os.getenv("LOG_RAW_TEXT", "false").lower() == "true"

# Config DB (usa las variables del .env del stack)
DB_HOST = os.getenv("POSTGRES_HOST", "postgres")
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
DB_NAME = os.getenv("POSTGRES_DB", "lasfocas")
DB_USER = os.getenv("POSTGRES_USER", "lasfocas")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "superseguro")
DB_DSN = f"dbname={DB_NAME} user={DB_USER} password={DB_PASS} host={DB_HOST} port={DB_PORT}"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logger = setup_logging("web", LOG_LEVEL, enable_file=None, filename="web.log")


def _detect_build_version() -> str:
    for candidate in (
        os.getenv("WEB_BUILD_VERSION"),
        os.getenv("BUILD_HASH"),
        os.getenv("GIT_SHA"),
    ):
        if candidate:
            return candidate.strip()
    return str(int(time.time()))


BUILD_VERSION = _detect_build_version()

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

app = FastAPI(title="LAS-FOCAS Web UI", version=BUILD_VERSION)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("WEB_SECRET_KEY", "dev-secret-change"))

# Middleware de trazabilidad de requests (ayuda a depurar ERR_INVALID_HTTP_RESPONSE en navegador)
@app.middleware("http")
async def log_requests(request, call_next):  # type: ignore
    try:
        logger.debug("action=request_start path=%s client=%s", request.url.path, request.client.host if request.client else "?")
    except Exception:  # noqa: BLE001
        pass
    try:
        response = await call_next(request)
        logger.debug(
            "action=request_end path=%s status=%s len=%s", request.url.path, getattr(response, "status_code", "?"), getattr(response, "body", None) and len(getattr(response, "body"))
        )
        return response
    except Exception as exc:  # noqa: BLE001
        logger.exception("action=request_error path=%s error=%s", getattr(request, 'url', '?'), exc)
        raise

# Rutas absolutas a static/templates basadas en la ubicación de este archivo (web/web_app/main.py)
BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = str(BASE_DIR / "static")
TEMPLATES_DIR = str(BASE_DIR / "templates")
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
REPORTS_DIR = DATA_DIR / "reports"
DEFAULT_TEMPLATES_PATH = Path(__file__).resolve().parents[2] / "Templates"
TEMPLATES_ROOT = os.getenv("TEMPLATES_DIR", str(DEFAULT_TEMPLATES_PATH))
DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
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

# Variables de entorno para que los módulos de informes respeten rutas
os.environ.setdefault("UPLOADS_DIR", str(UPLOADS_DIR))
os.environ.setdefault("REPORTS_DIR", str(REPORTS_DIR))
os.environ.setdefault("TEMPLATES_DIR", TEMPLATES_ROOT)

# Importar servicio de informes después de setear variables de entorno
from modules.informes_repetitividad.service import (  # noqa: E402
    ReportConfig,
    ReportResult,
    generar_informe_desde_excel,
)

REPORT_SERVICE_CONFIG = ReportConfig.from_settings()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
# Elegir la carpeta de reportes a montar: preferir la de configuración si existe; si no, fallback local
_cfg_reports = Path(REPORT_SERVICE_CONFIG.reports_dir)
_mount_reports = _cfg_reports if _cfg_reports.exists() else REPORTS_DIR
_mount_reports.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(_mount_reports)), name="reports")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["build_version"] = BUILD_VERSION


def _parse_allowed_origins(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


CHAT_ALLOWED_ORIGINS = _parse_allowed_origins(os.getenv("WEB_CHAT_ALLOWED_ORIGINS"))
if not CHAT_ALLOWED_ORIGINS:
    inferred_origin = os.getenv("WEB_INFERRED_ORIGIN")
    if inferred_origin:
        CHAT_ALLOWED_ORIGINS = [inferred_origin]

mount_chat_websocket(
    app,
    settings=ChatWebSocketSettings(
        dsn=DB_DSN,
        allowed_origins=CHAT_ALLOWED_ORIGINS,
        uploads_dir=str(UPLOADS_DIR),
    ),
    logger=logger,
)


@dataclass
class IntentResponse:
    intent: str
    confidence: float
    provider: str
    normalized_text: str


class MCPInvokeRequest(BaseModel):
    tool: str = Field(..., description="Nombre de la herramienta MCP")
    args: Dict[str, Any] = Field(default_factory=dict, description="Argumentos para la herramienta")
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="Adjuntos opcionales")


async def classify_text(text: str) -> IntentResponse:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{NLP_INTENT_URL}/v1/intent:classify", json={"text": text}
        )
        resp.raise_for_status()
        data = resp.json()
        return IntentResponse(**data)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "web", "time": int(time.time())}


@app.get("/health/version")
async def health_version() -> Dict[str, Any]:
    return {"status": "ok", "service": "web", "version": BUILD_VERSION}


def get_current_user(request: Request) -> str | None:
    return request.session.get("username")


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    if get_current_user(request):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def do_login(request: Request, username: str = Form(...), password: str = Form(...)):
    # Rate limiting simple por IP (5 intentos/ minuto)
    ip = request.client.host if request.client else "unknown"
    rl = request.session.get("rl_login", {"ip": ip, "count": 0, "ts": now()})
    if rl["ip"] != ip or now() - rl["ts"] > 60:
        rl = {"ip": ip, "count": 0, "ts": now()}
    rl["count"] += 1
    request.session["rl_login"] = rl
    if rl["count"] > 5:
        return templates.TemplateResponse(request, "login.html", {"error": "Demasiados intentos. Esperá un minuto."}, status_code=429)
    # Verificar usuario en DB
    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT password_hash, role FROM app.web_users WHERE username=%s", (username,))
                row = cur.fetchone()
                password_ok = False
                if row:
                    try:
                        password_ok = verify_password(password, row[0])
                    except Exception as exc:  # noqa: BLE001
                        logger.error("action=login bcrypt_error username=%s error=%s", username, exc)
                if not row or not password_ok:
                    # Hash truncado a 20 chars para diagnóstico (sin exponer todo si se hacen logs externos)
                    stored_hash_preview = row[0][:20] + "..." if row else None
                    logger.warning(
                        "action=login result=fail reason=%s username=%s found_user=%s bcrypt_ok=%s hash_preview=%s ip=%s rl_count=%s",
                        "no_user" if not row else "bad_password",
                        username,
                        bool(row),
                        password_ok,
                        stored_hash_preview,
                        ip,
                        rl["count"],
                    )
                    return templates.TemplateResponse(request, "login.html", {"error": "Credenciales inválidas"}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"action=login result=error username={username} ip={ip} error={exc}")
        return templates.TemplateResponse(request, "login.html", {"error": "Error de autenticación"}, status_code=500)

    logger.info(
        "action=login result=success username=%s role=%s ip=%s rl_count=%s",
        username,
        row[1] if row else "?",
        ip,
        rl["count"],
    )

    request.session["username"] = username
    request.session["role"] = row[1] if row else "user"
    # Regenerar token CSRF en login
    request.session["csrf"] = secrets.token_urlsafe(32)
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    if not get_current_user(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    # Mostrar el nuevo panel con Chat como vista principal
    return templates.TemplateResponse(
        request,
        "panel.html",
        {
            "username": get_current_user(request),
            "csrf": request.session.get("csrf"),
            "api_base": os.getenv("API_BASE", "http://192.168.241.28:8080"),
        },
    )


@app.get("/panel", response_class=HTMLResponse)
async def panel(request: Request) -> HTMLResponse:
    if not get_current_user(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request,
        "panel.html",
        {
            "username": get_current_user(request),
            "csrf": request.session.get("csrf"),
            "api_base": os.getenv("API_BASE", "http://192.168.241.28:8080"),
        },
    )

@app.get("/reports/index")
async def reports_index_redirect() -> RedirectResponse:
    return RedirectResponse(url="/reports-history", status_code=status.HTTP_302_FOUND)


@app.get("/reports-history", response_class=HTMLResponse)
async def reports_history(request: Request) -> HTMLResponse:
    if not get_current_user(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    # Listar archivos del directorio de reportes (solo nivel actual)
    files = []
    try:
        for p in sorted(_mount_reports.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
            if p.is_file():
                files.append({
                    "name": p.name,
                    "size": p.stat().st_size,
                    "mtime": int(p.stat().st_mtime),
                    "href": f"/reports/{p.name}",
                })
    except Exception as exc:  # noqa: BLE001
        logger.warning("action=reports_index_list error=%s", exc)
    return templates.TemplateResponse(
        request,
        "reports.html",
        {
            "username": get_current_user(request),
            "files": files,
        },
    )


def _require_auth(request: Request) -> tuple[str, str]:
    username = request.session.get("username")
    role = request.session.get("role", "user")
    if not username:
        raise RuntimeError("Unauthorized")
    return username, role


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request) -> HTMLResponse:
    user = request.session.get("username")
    role = request.session.get("role", "user")
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if role != "admin":
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "username": user,
            "role": role,
            "csrf": request.session.get("csrf"),
        },
    )


@app.post("/api/users/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    csrf_token: str = Form(...),
):
    # Autenticado + CSRF
    user, _ = _require_auth(request)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT password_hash FROM app.web_users WHERE username=%s", (user,))
                row = cur.fetchone()
                if not row or not verify_password(current_password, row[0]):
                    return JSONResponse({"error": "Contraseña actual incorrecta"}, status_code=400)
                new_hash = hash_password(new_password)
                cur.execute(
                    "UPDATE app.web_users SET password_hash=%s WHERE username=%s",
                    (new_hash, user),
                )
                conn.commit()
    except Exception as exc:
        return JSONResponse({"error": f"Error cambiando contraseña: {exc}"}, status_code=500)
    return JSONResponse({"status": "ok"})


ALLOWED_ROLES = {"admin", "ownergroup", "invitado"}


@app.post("/api/admin/users")
async def admin_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("invitado"),
    csrf_token: str = Form(...),
):
    # Admin + CSRF
    _, role_sess = _require_auth(request)
    if role_sess != "admin":
        return JSONResponse({"error": "Solo admin"}, status_code=403)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    # Validación de rol permitido (case-insensitive)
    role_norm = role.strip().lower()
    if role_norm not in ALLOWED_ROLES:
        return JSONResponse({"error": "Rol inválido. Use Admin, OwnerGroup o Invitado."}, status_code=400)
    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM app.web_users WHERE username=%s", (username,))
                if cur.fetchone():
                    return JSONResponse({"error": "Usuario ya existe"}, status_code=409)
                cur.execute(
                    "INSERT INTO app.web_users (username, password_hash, role) VALUES (%s,%s,%s)",
                    (username, hash_password(password), role_norm),
                )
                conn.commit()
    except Exception as exc:
        return JSONResponse({"error": f"Error creando usuario: {exc}"}, status_code=500)
    return JSONResponse({"status": "ok"})


@app.post("/api/chat/message")
async def chat_message(request: Request, text: str = Form(...), csrf_token: str | None = Form(None)) -> JSONResponse:
    """
    Recibe un mensaje del usuario (form-data o x-www-form-urlencoded) y
    devuelve intención y una respuesta simple.
    """
    # CSRF: si hay sesión, exigir token válido
    if get_current_user(request):
        if os.getenv("TESTING", "false").lower() != "true":
            sess_token = request.session.get("csrf")
            if not sess_token or csrf_token != sess_token:
                return JSONResponse({"error": "CSRF inválido"}, status_code=403)

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
    user = get_current_user(request)
    if user:
        try:
            with psycopg.connect(DB_DSN) as conn:
                conv_id = get_or_create_conversation_for_web_user(conn, user)
                payload["conversation_id"] = conv_id
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
                history = get_last_messages(conn, conv_id, limit=6)
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


@app.get("/api/chat/history")
async def chat_history(request: Request, limit: int = 20) -> JSONResponse:
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    if limit > 100:
        limit = 100
    try:
        with psycopg.connect(DB_DSN) as conn:
            conv_id = get_or_create_conversation_for_web_user(conn, user)
            history = get_last_messages(conn, conv_id, limit=limit)
            return JSONResponse({"conversation_id": conv_id, "messages": history})
    except Exception as exc:  # noqa: BLE001
        logger.warning("action=chat_history error=%s", exc)
        return JSONResponse({"error": "Fallo al recuperar historial"}, status_code=500)


@app.post("/api/chat/uploads")
async def chat_upload_attachment(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str | None = Form(None),
) -> JSONResponse:
    username = get_current_user(request)
    if not username:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    session_token = request.session.get("csrf")
    if session_token and csrf_token != session_token and os.getenv("TESTING", "false").lower() != "true":
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
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


@app.get("/api/chat/metrics")
async def chat_metrics(request: Request) -> JSONResponse:
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    return JSONResponse({"intent_counts": INTENT_COUNTER})


@app.get("/api/chat/ws-history")
async def chat_ws_history(request: Request, limit: int = 40) -> JSONResponse:
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    orchestrator = getattr(app.state, "chat_orchestrator", None)
    if orchestrator is None:
        return JSONResponse({"error": "Chat no disponible"}, status_code=503)
    if limit > 100:
        limit = 100
    session_id = await orchestrator.ensure_session(user)
    history = await orchestrator.history(session_id, limit)
    return JSONResponse({"session_id": session_id, "messages": history})


@app.post("/mcp/invoke")
async def mcp_invoke(request: Request, payload: MCPInvokeRequest) -> JSONResponse:
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "No autenticado"}, status_code=401)
    orchestrator = getattr(app.state, "chat_orchestrator", None)
    if orchestrator is None:
        return JSONResponse({"error": "Chat no disponible"}, status_code=503)
    role = request.session.get("role", "user")
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
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "action=mcp_http_invoke_error user=%s session_id=%s tool=%s error=%s",
            user,
            session_id,
            payload.tool,
            exc,
        )
        return JSONResponse(
            {
                "status": "error",
                "message": "Fallo ejecutando la herramienta",
            },
            status_code=500,
        )
    return JSONResponse({"status": "ok", "events": events})


def _save_upload(file: UploadFile) -> Path:
    filename = Path(file.filename or "upload.bin").name  # sanea nombre
    dest = UPLOADS_DIR / filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    file.file.close()
    return dest


@app.post("/api/flows/sla")
async def flow_sla(request: Request, file: UploadFile = File(...), mes: int = Form(...), anio: int = Form(...), csrf_token: str = Form(...)):
    # Autenticación + CSRF
    _require_auth(request)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    # Guardar archivo y ejecutar runner
    try:
        from modules.informes_sla import runner as sla_runner  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Módulo SLA no disponible: {exc}"}, status_code=500)
    try:
        path = _save_upload(file)
        result = sla_runner.run(str(path), mes, anio, os.getenv("SOFFICE_BIN"))
        docx = result.get("docx")
        pdf = result.get("pdf")
        payload = {"status": "ok", "docx": f"/reports/{Path(docx).name}" if docx else None}
        if pdf:
            payload["pdf"] = f"/reports/{Path(pdf).name}"
        return JSONResponse(payload)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Fallo al procesar SLA: {exc}"}, status_code=500)


@app.post("/api/flows/repetitividad")
async def flow_repetitividad(
    request: Request,
    file: UploadFile = File(...),
    mes: int = Form(...),
    anio: int = Form(...),
    include_pdf: bool = Form(True),
    csrf_token: str = Form(...),
):
    """Flujo Web para generar Informe de Repetitividad (sin filtros por período)."""

    _require_auth(request)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    original_name = file.filename or "archivo.xlsx"
    if not original_name.lower().endswith(".xlsx"):
        return JSONResponse({"error": "El archivo debe ser .xlsx"}, status_code=400)

    upload_path = _save_upload(file)
    periodo_titulo = f"{mes:02d}/{anio}"
    size_bytes = 0
    start = time.time()

    try:
        size_bytes = upload_path.stat().st_size
        max_bytes = 10 * 1024 * 1024
        if size_bytes > max_bytes:
            upload_path.unlink(missing_ok=True)
            return JSONResponse({"error": "Archivo demasiado grande (límite 10MB)"}, status_code=413)

        if not zipfile.is_zipfile(upload_path):
            upload_path.unlink(missing_ok=True)
            return JSONResponse({"error": "El archivo subido no es un Excel .xlsx válido"}, status_code=400)

        logger.info(
            "action=flow_repetitividad stage=start filename=%s periodo=%s include_pdf=%s size=%s",
            original_name,
            periodo_titulo,
            include_pdf,
            size_bytes,
        )

        try:
            df_head = pd.read_excel(upload_path, nrows=1, engine="openpyxl")
            logger.info(
                "action=flow_repetitividad stage=inspect columns_raw=%s",
                list(df_head.columns),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("action=flow_repetitividad stage=inspect error=%s", exc)

        excel_bytes = upload_path.read_bytes()
        result: ReportResult = await asyncio.to_thread(
            generar_informe_desde_excel,
            excel_bytes,
            periodo_titulo,
            include_pdf,
            REPORT_SERVICE_CONFIG,
        )
    except ValueError as exc:
        logger.warning(
            "action=flow_repetitividad stage=validation error=%s periodo=%s",
            exc,
            periodo_titulo,
        )
        return JSONResponse({"error": str(exc)}, status_code=422)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "action=flow_repetitividad stage=unexpected periodo=%s error=%s",
            periodo_titulo,
            exc,
        )
        return JSONResponse({"error": "No se pudo generar el informe"}, status_code=500)
    finally:
        upload_path.unlink(missing_ok=True)

    payload: Dict[str, Any] = {
        "status": "ok",
        "pdf_requested": include_pdf,
        "stats": {
            "filas": result.total_filas,
            "repetitivos": result.total_repetitivos,
            "periodos": result.periodos_detectados or [],
        },
    }
    if result.docx:
        payload["docx"] = f"/reports/{result.docx.name}"
    if result.pdf:
        payload["pdf"] = f"/reports/{result.pdf.name}"
    elif include_pdf:
        payload["pdf_generated"] = False
    if result.map_html:
        payload["map"] = f"/reports/{result.map_html.name}"

    elapsed = round((time.time() - start) * 1000)
    logger.info(
        "action=flow_repetitividad stage=success periodo=%s docx=%s pdf=%s map=%s filas=%s repetitivos=%s ms=%s",
        periodo_titulo,
        bool(result.docx),
        bool(result.pdf),
        bool(result.map_html),
        result.total_filas,
        result.total_repetitivos,
        elapsed,
    )
    return JSONResponse(payload)


@app.post("/api/flows/comparador-fo")
async def flow_comparador_fo(request: Request):
    _require_auth(request)
    return JSONResponse({"error": "Comparador FO no implementado aún"}, status_code=501)
