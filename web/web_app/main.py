# Nombre de archivo: main.py
# Ubicación de archivo: web/web_app/main.py
# Descripción: Aplicación FastAPI para la UI (página dark, barra y chat REST)

from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from time import time as now
from typing import Any, Dict

import httpx
from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from passlib.hash import bcrypt
from core.logging import setup_logging
import psycopg
from pathlib import Path
import shutil
from fastapi import UploadFile, File

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

app = FastAPI(title="LAS-FOCAS Web UI", version="0.1.0")
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
DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Variables de entorno para que los módulos de informes respeten rutas
os.environ.setdefault("UPLOADS_DIR", str(UPLOADS_DIR))
os.environ.setdefault("REPORTS_DIR", str(REPORTS_DIR))

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@dataclass
class IntentResponse:
    intent: str
    confidence: float
    provider: str
    normalized_text: str


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
                bcrypt_ok = False
                if row:
                    try:
                        bcrypt_ok = bcrypt.verify(password, row[0])
                    except Exception as exc:  # noqa: BLE001
                        logger.error(f"action=login bcrypt_error username={username} error={exc}")
                if not row or not bcrypt_ok:
                    # Hash truncado a 20 chars para diagnóstico (sin exponer todo si se hacen logs externos)
                    stored_hash_preview = row[0][:20] + "..." if row else None
                    logger.warning(
                        "action=login result=fail reason=%s username=%s found_user=%s bcrypt_ok=%s hash_preview=%s ip=%s rl_count=%s",
                        "no_user" if not row else "bad_password",
                        username,
                        bool(row),
                        bcrypt_ok,
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
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "username": get_current_user(request),
            "csrf": request.session.get("csrf"),
            "api_base": os.getenv("API_BASE", "http://192.168.241.28:8080"),
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
                if not row or not bcrypt.verify(current_password, row[0]):
                    return JSONResponse({"error": "Contraseña actual incorrecta"}, status_code=400)
                new_hash = bcrypt.hash(new_password)
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
                    (username, bcrypt.hash(password), role_norm),
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
    # Clasificación
    try:
        intent_resp = await classify_text(text)
    except Exception:  # noqa: BLE001
        # Fallback muy básico si falla el servicio de NLP
        intent_resp = IntentResponse(intent="Otros", confidence=0.0, provider="none", normalized_text=text)

    # Respuesta dummy por ahora; en la siguiente iteración integraremos Ollama
    reply = "Entendido. Estoy preparando acciones para ese flujo." if intent_resp.intent == "Acción" else "Gracias. Tomo nota de tu consulta."

    payload = {
        "reply": reply,
        "intent": intent_resp.intent,
        "confidence": intent_resp.confidence,
        "provider": intent_resp.provider,
    }
    # Logging prudente: opcionalmente no incluir el texto completo
    if LOG_RAW_TEXT:
        payload["user_text"] = text
        payload["normalized_text"] = intent_resp.normalized_text

    return JSONResponse(payload)


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
async def flow_repetitividad(request: Request, file: UploadFile = File(...), mes: int = Form(...), anio: int = Form(...), csrf_token: str = Form(...)):
    _require_auth(request)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    try:
        from modules.informes_repetitividad import runner as rep_runner  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Módulo Repetitividad no disponible: {exc}"}, status_code=500)
    try:
        path = _save_upload(file)
        result = rep_runner.run(str(path), mes, anio, os.getenv("SOFFICE_BIN"))
        docx = result.get("docx")
        pdf = result.get("pdf")
        payload = {"status": "ok", "docx": f"/reports/{Path(docx).name}" if docx else None}
        if pdf:
            payload["pdf"] = f"/reports/{Path(pdf).name}"
        return JSONResponse(payload)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Fallo al procesar Repetitividad: {exc}"}, status_code=500)


@app.post("/api/flows/comparador-fo")
async def flow_comparador_fo(request: Request):
    _require_auth(request)
    return JSONResponse({"error": "Comparador FO no implementado aún"}, status_code=501)
