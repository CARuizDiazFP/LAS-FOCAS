# Nombre de archivo: main.py
# Ubicación de archivo: web/web_app/main.py
# Descripción: Aplicación FastAPI para la UI (página dark, barra y chat REST)

from __future__ import annotations

import asyncio
import io
import os
import secrets
import time
import zipfile
from dataclasses import dataclass
from time import time as now
from typing import Any, Dict, List, Optional, Union

import httpx
from fastapi import FastAPI, Form, Request, status, HTTPException, Response
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
from web.tools.vlan_comparator import compare_vlan_sets, parse_cisco_vlans
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
LOGS_ROOT = Path(os.getenv("LOGS_DIR", str(Path(__file__).resolve().parents[2] / "Logs")))
logger = setup_logging("web", LOG_LEVEL, enable_file=True, logs_dir=LOGS_ROOT, filename="web.log")


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
from core.services.repetitividad import db_to_processor_frame, reclamos_from_db  # noqa: E402
from core.services import sla as sla_service  # noqa: E402
from modules.informes_repetitividad.service import (  # noqa: E402
    ReportConfig,
    ReportResult,
    generar_informe_desde_dataframe,
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


class VLANCompareRequest(BaseModel):
    text_a: str = Field(..., description="Configuración de la primera interfaz")
    text_b: str = Field(..., description="Configuración de la segunda interfaz")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


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


@app.get("/sla", response_class=HTMLResponse)
async def sla_page(request: Request) -> HTMLResponse:
    if not get_current_user(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request,
        "sla.html",
        {
            "username": get_current_user(request),
            "csrf": request.session.get("csrf"),
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


def _merge_excel_sources(sources: List[tuple[str, bytes]]) -> bytes:
    if not sources:
        raise ValueError("No hay archivos para combinar")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:  # type: ignore[arg-type]
        sheet_index = 1
        for name, content in sources:
            try:
                workbook = pd.ExcelFile(io.BytesIO(content))
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"El archivo {name} no parece un Excel válido") from exc
            for sheet in workbook.sheet_names:
                dataframe = workbook.parse(sheet)
                prefix = Path(name).stem[:18] or "Hoja"
                sheet_label = f"{prefix}_{sheet_index}"[:31]
                dataframe.to_excel(writer, sheet_name=sheet_label, index=False)
                sheet_index += 1
    buffer.seek(0)
    return buffer.getvalue()


def _report_href(path: Path) -> str:
    """Construye la ruta HTTP para un archivo montado en /reports."""

    archivo = Path(path)
    candidatos = [Path(_mount_reports)]
    try:
        candidatos.append(Path(REPORT_SERVICE_CONFIG.reports_dir))
    except Exception:  # noqa: BLE001 - fallback defensivo
        pass
    candidatos.append(REPORTS_DIR)

    for base in candidatos:
        try:
            rel = archivo.relative_to(base)
        except ValueError:
            continue
        return f"/reports/{rel.as_posix()}"
    return f"/reports/{archivo.name}"


@app.post("/api/reports/sla")
async def generar_informe_sla_web(
    request: Request,
    mes: str | None = Form(None),
    anio: str | None = Form(None),
    periodo_mes: str | None = Form(None),
    periodo_anio: str | None = Form(None),
    pdf_enabled: bool = Form(False),
    use_db: bool = Form(False),
    csrf_token: str | None = Form(None),
    files: List[UploadFile] = File(default=[]),
):
    username, _ = _require_auth(request)
    expected_csrf = request.session.get("csrf")

    async def _close_uploads(upload_list: List[UploadFile]) -> None:
        for upload in upload_list:
            try:
                await upload.close()
            except Exception:  # noqa: BLE001
                logger.debug("action=sla_web_report stage=close_upload warning", exc_info=True)

    if expected_csrf and os.getenv("TESTING", "false").lower() != "true":
        if csrf_token != expected_csrf:
            await _close_uploads(files)
            return JSONResponse({"ok": False, "error": "CSRF inválido"}, status_code=403)

    raw_mes = mes or periodo_mes
    raw_anio = anio or periodo_anio

    try:
        mes_num = int(str(raw_mes).strip())
        anio_num = int(str(raw_anio).strip())
    except (TypeError, ValueError):
        await _close_uploads(files)
        return JSONResponse({"ok": False, "error": "Mes y año deben ser numéricos"}, status_code=422)

    if not 1 <= mes_num <= 12 or not 2000 <= anio_num <= 2100:
        await _close_uploads(files)
        return JSONResponse({"ok": False, "error": "Mes y año fuera de rango permitido"}, status_code=422)

    # Normalizar files: filtrar solo los que tienen nombre de archivo
    archivos = [archivo for archivo in files if archivo and archivo.filename]
    
    archivo_count = len(archivos)
    source = "db" if use_db else "excel"

    if use_db and archivos:
        for archivo in archivos:
            await archivo.close()
        archivos = []

    try:
        if not use_db:
            logger.info("action=sla_web_report stage=start user=%s archivos=%s", username, archivo_count)
            if len(archivos) != 2:
                await _close_uploads(archivos)
                logger.warning("action=sla_web_report stage=validation error=archivos_incorrectos count=%s", len(archivos))
                return JSONResponse(
                    {"ok": False, "error": "Debés adjuntar dos archivos: servicios y reclamos"},
                    status_code=400,
                )

            servicios_bytes: Optional[bytes] = None
            reclamos_bytes: Optional[bytes] = None

            for archivo in archivos:
                nombre = Path(archivo.filename).name
                logger.debug("action=sla_web_report stage=processing file=%s", nombre)
                if not nombre.lower().endswith(".xlsx"):
                    await archivo.close()
                    logger.warning("action=sla_web_report stage=validation error=extension file=%s", nombre)
                    return JSONResponse(
                        {"ok": False, "error": f"{nombre} debe tener extensión .xlsx"},
                        status_code=415,
                    )
                contenido = await archivo.read()
                await archivo.close()
                if not contenido:
                    logger.warning("action=sla_web_report stage=validation error=empty file=%s", nombre)
                    return JSONResponse({"ok": False, "error": f"{nombre} está vacío"}, status_code=400)
                try:
                    tipo = sla_service.identify_excel_kind(contenido)
                    logger.info("action=sla_web_report stage=identify file=%s tipo=%s", nombre, tipo)
                except ValueError as exc:
                    logger.warning("action=sla_web_report stage=identify error=%s file=%s", exc, nombre)
                    return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)

                if tipo == "servicios":
                    if servicios_bytes is not None:
                        return JSONResponse({"ok": False, "error": "Se recibió más de un Excel de servicios"}, status_code=422)
                    servicios_bytes = contenido
                else:
                    if reclamos_bytes is not None:
                        return JSONResponse({"ok": False, "error": "Se recibió más de un Excel de reclamos"}, status_code=422)
                    reclamos_bytes = contenido

            if servicios_bytes is None or reclamos_bytes is None:
                logger.warning("action=sla_web_report stage=validation error=missing_files servicios=%s reclamos=%s", servicios_bytes is not None, reclamos_bytes is not None)
                return JSONResponse({"ok": False, "error": "Adjuntá los archivos de servicios y reclamos"}, status_code=400)

            logger.info("action=sla_web_report stage=generate_legacy mes=%s anio=%s pdf=%s", mes_num, anio_num, pdf_enabled)
            documento = sla_service.generate_report_from_excel_pair(
                servicios_bytes,
                reclamos_bytes,
                mes=mes_num,
                anio=anio_num,
                incluir_pdf=pdf_enabled,
            )
            resultado_docx = documento.docx
            resultado_pdf = documento.pdf
            source = "excel-legacy"
            logger.info("action=sla_web_report stage=legacy_ok docx=%s pdf=%s", resultado_docx, resultado_pdf)
        else:
            computation = sla_service.compute_from_db(mes=mes_num, anio=anio_num)
            resultado = sla_service.generate_report_from_computation(
                computation,
                incluir_pdf=pdf_enabled,
            )
            resultado_docx = resultado.docx
            resultado_pdf = resultado.pdf
    except ValueError as exc:
        logger.warning(
            "action=sla_web_report stage=validation user=%s source=%s mes=%s anio=%s error=%s",
            username,
            source,
            mes_num,
            anio_num,
            exc,
        )
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "action=sla_web_report stage=unexpected user=%s source=%s mes=%s anio=%s error=%s",
            username,
            source,
            mes_num,
            anio_num,
            exc,
        )
        detalle = str(exc) or exc.__class__.__name__
        return JSONResponse({"ok": False, "error": f"No se pudo generar el informe SLA: {detalle}"}, status_code=500)

    report_paths = {
        "docx": _report_href(resultado_docx),
    }
    if resultado_pdf:
        report_paths["pdf"] = _report_href(resultado_pdf)

    logger.info(
        "action=sla_web_report stage=success user=%s source=%s mes=%s anio=%s pdf=%s archivos=%s",
        username,
        source,
        mes_num,
        anio_num,
        bool(resultado_pdf),
        archivo_count,
    )

    return JSONResponse(
        {
            "ok": True,
            "message": "Informe SLA generado correctamente",
            "report_paths": report_paths,
            "source": source,
        }
    )


def _require_auth(request: Request) -> tuple[str, str]:
    username = request.session.get("username")
    role = request.session.get("role", "user")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
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
async def flow_sla(
    request: Request,
    file: UploadFile | None = File(None),
    mes: int = Form(..., ge=1, le=12),
    anio: int = Form(..., ge=2000, le=2100),
    include_pdf: bool = Form(False),
    use_db: bool = Form(False),
    eventos: str = Form(""),
    conclusion: str = Form(""),
    propuesta: str = Form(""),
    csrf_token: str = Form(...),
):
    # Autenticación + CSRF
    _require_auth(request)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    use_db = use_db or not (file and file.filename)
    source = "db" if use_db else "excel"

    if use_db and file is not None:
        await file.close()

    try:
        if not use_db:
            assert file is not None
            if not file.filename or not file.filename.lower().endswith(".xlsx"):
                return JSONResponse({"error": "El archivo debe ser .xlsx"}, status_code=400)
            excel_bytes = await file.read()
            await file.close()
            if not excel_bytes:
                return JSONResponse({"error": "El archivo está vacío"}, status_code=400)

            resultado = sla_service.generate_report_from_excel(
                excel_bytes,
                mes=mes,
                anio=anio,
                eventos=eventos,
                conclusion=conclusion,
                propuesta=propuesta,
                incluir_pdf=include_pdf,
            )
        else:
            computation = sla_service.compute_from_db(mes=mes, anio=anio)
            resultado = sla_service.generate_report_from_computation(
                computation,
                eventos=eventos,
                conclusion=conclusion,
                propuesta=propuesta,
                incluir_pdf=include_pdf,
            )
    except ValueError as exc:
        logger.warning(
            "action=sla_flow stage=validation source=%s mes=%s anio=%s error=%s",
            source,
            mes,
            anio,
            exc,
        )
        return JSONResponse({"error": str(exc)}, status_code=422)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "action=sla_flow stage=unexpected source=%s mes=%s anio=%s error=%s",
            source,
            mes,
            anio,
            exc,
        )
        return JSONResponse({"error": "No se pudo generar el informe SLA"}, status_code=500)

    report_links = {"docx": _report_href(resultado.docx)}
    if resultado.pdf:
        report_links["pdf"] = _report_href(resultado.pdf)

    resumen = resultado.computation.resumen
    payload: Dict[str, Any] = {
        "status": "ok",
        "message": "Informe SLA generado",
        "source": source,
        "docx": report_links["docx"],
        "pdf": report_links.get("pdf"),
        "report_paths": report_links,
        "metrics": {
            "periodo": resumen.periodo,
            "disponibilidad_pct": resumen.disponibilidad_pct,
            "downtime_total_h": resumen.downtime_total_h,
            "servicios": resumen.servicios,
            "incidentes": resumen.incidentes,
            "tickets": resumen.tickets,
            "mttr_h": resumen.mttr_h,
            "mtbf_h": resumen.mtbf_h,
        },
    }

    logger.info(
        "action=sla_flow stage=success source=%s mes=%s anio=%s servicios=%s downtime=%s pdf=%s",
        source,
        mes,
        anio,
        resumen.servicios,
        resumen.downtime_total_h,
        bool(resultado.pdf),
    )

    return JSONResponse(payload)


@app.post("/api/flows/repetitividad")
async def flow_repetitividad(
    request: Request,
    file: UploadFile | None = File(None),
    mes: int = Form(...),
    anio: int = Form(...),
    include_pdf: bool = Form(True),
    csrf_token: str = Form(...),
    with_geo: bool = Form(False),
    use_db: bool = Form(False),
):
    """Genera el informe de Repetitividad desde Excel o DB según los parámetros."""

    _require_auth(request)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    periodo_titulo = f"{mes:02d}/{anio}"
    use_db = use_db or file is None
    start = time.time()

    try:
        if not use_db:
            if not file or not file.filename or not file.filename.lower().endswith(".xlsx"):
                return JSONResponse({"error": "El archivo debe ser .xlsx"}, status_code=400)

            upload_path = _save_upload(file)
            try:
                size_bytes = upload_path.stat().st_size
                if size_bytes > 10 * 1024 * 1024:
                    upload_path.unlink(missing_ok=True)
                    return JSONResponse({"error": "Archivo demasiado grande (límite 10MB)"}, status_code=413)
                if not zipfile.is_zipfile(upload_path):
                    upload_path.unlink(missing_ok=True)
                    return JSONResponse({"error": "El archivo subido no es un Excel .xlsx válido"}, status_code=400)
                logger.info(
                    "action=flow_repetitividad stage=start source=excel periodo=%s include_pdf=%s with_geo=%s size_bytes=%s",
                    periodo_titulo,
                    include_pdf,
                    with_geo,
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
                    with_geo,
                )
            finally:
                upload_path.unlink(missing_ok=True)
        else:
            df_db = reclamos_from_db(mes, anio)
            df_proc = db_to_processor_frame(df_db)
            if df_proc.empty:
                return JSONResponse({"error": "No hay reclamos registrados para el período"}, status_code=404)
            logger.info(
                "action=flow_repetitividad stage=start source=db periodo=%s include_pdf=%s with_geo=%s filas=%s",
                periodo_titulo,
                include_pdf,
                with_geo,
                len(df_proc),
            )
            result = await asyncio.to_thread(
                generar_informe_desde_dataframe,
                df_proc,
                periodo_titulo,
                include_pdf,
                REPORT_SERVICE_CONFIG,
                with_geo,
                "db",
            )
    except ValueError as exc:
        logger.warning(
            "action=flow_repetitividad stage=validation error=%s periodo=%s", exc, periodo_titulo
        )
        return JSONResponse({"error": str(exc)}, status_code=422)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "action=flow_repetitividad stage=unexpected periodo=%s error=%s",
            periodo_titulo,
            exc,
        )
        return JSONResponse({"error": "No se pudo generar el informe"}, status_code=500)

    image_maps = [f"/reports/{Path(m).name}" for m in result.map_images]
    payload: Dict[str, Any] = {
        "status": "ok",
        "pdf_requested": include_pdf,
        "with_geo": bool(with_geo),
        "source": "db" if use_db else "excel",
        "stats": {
            "filas": result.total_filas,
            "repetitivos": result.total_repetitivos,
            "periodos": result.periodos_detectados or [],
        },
        "maps": [],
        "map_images": image_maps,
        "assets": image_maps,
    }
    if result.docx:
        payload["docx"] = f"/reports/{result.docx.name}"
    if result.pdf:
        payload["pdf"] = f"/reports/{result.pdf.name}"
    elif include_pdf:
        payload["pdf_generated"] = False
    if image_maps:
        payload["map_image"] = image_maps[0]

    elapsed = round((time.time() - start) * 1000)
    logger.info(
        "action=flow_repetitividad stage=success periodo=%s source=%s docx=%s pdf=%s map_images=%s filas=%s repetitivos=%s ms=%s",
        periodo_titulo,
        payload["source"],
        bool(result.docx),
        bool(result.pdf),
        len(image_maps),
        result.total_filas,
        result.total_repetitivos,
        elapsed,
    )
    return JSONResponse(payload)


@app.post("/api/flows/comparador-fo")
async def flow_comparador_fo(request: Request):
    _require_auth(request)
    return JSONResponse({"error": "Comparador FO no implementado aún"}, status_code=501)


@app.post("/api/tools/alarmas-ciena")
async def tool_alarmas_ciena(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
):
    """
    Endpoint para procesar archivos CSV de alarmas Ciena (SiteManager o MCP).
    
    Detecta automáticamente el formato, parsea el CSV y retorna un archivo Excel.
    
    Args:
        request: Request de FastAPI
        file: Archivo CSV subido
        csrf_token: Token CSRF para validación
        
    Returns:
        Response con el archivo Excel para descarga
    """
    from core.parsers.alarmas_ciena import parsear_alarmas_ciena, dataframe_to_excel, FormatoAlarma
    
    # Autenticación y CSRF
    _require_auth(request)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    
    # Validar nombre y extensión
    if not file.filename or not file.filename.lower().endswith(".csv"):
        logger.warning(
            "action=alarmas_ciena_upload_invalid user=%s filename=%s",
            get_current_user(request),
            file.filename
        )
        return JSONResponse(
            {"error": "Por favor subí un archivo .CSV válido"},
            status_code=400
        )
    
    # Leer contenido
    try:
        content = await file.read()
        await file.close()
    except Exception as e:
        logger.error("action=alarmas_ciena_read_error error=%s", e, exc_info=True)
        return JSONResponse(
            {"error": "Error al leer el archivo"},
            status_code=500
        )
    
    if not content:
        return JSONResponse(
            {"error": "El archivo está vacío"},
            status_code=400
        )
    
    # Validar tamaño (límite de 10MB para CSV)
    MAX_CSV_SIZE = 10 * 1024 * 1024  # 10MB
    if len(content) > MAX_CSV_SIZE:
        logger.warning(
            "action=alarmas_ciena_size_exceeded user=%s size=%d",
            get_current_user(request),
            len(content)
        )
        return JSONResponse(
            {"error": "El archivo supera el límite de 10MB"},
            status_code=413
        )
    
    # Procesar archivo
    username = get_current_user(request)
    start_time = time.time()
    
    try:
        logger.info(
            "action=alarmas_ciena_start user=%s filename=%s size=%d",
            username,
            file.filename,
            len(content)
        )
        
        # Detectar formato y parsear
        df, formato = parsear_alarmas_ciena(content)
        
        logger.info(
            "action=alarmas_ciena_parsed user=%s formato=%s rows=%d cols=%d",
            username,
            formato.value,
            len(df),
            len(df.columns)
        )
        
        # Generar Excel
        excel_content = dataframe_to_excel(df)
        
        elapsed = time.time() - start_time
        logger.info(
            "action=alarmas_ciena_complete user=%s formato=%s rows=%d size_out=%d elapsed=%.2fs",
            username,
            formato.value,
            len(df),
            len(excel_content),
            elapsed
        )
        
        # Preparar nombre de salida
        base_name = file.filename.rsplit('.', 1)[0]
        output_filename = f"{base_name}_procesado.xlsx"
        
        # Retornar Excel para descarga
        from fastapi.responses import Response
        return Response(
            content=excel_content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                'Content-Disposition': f'attachment; filename="{output_filename}"',
                'X-Formato-Detectado': formato.value,
                'X-Filas-Procesadas': str(len(df)),
                'X-Columnas': str(len(df.columns)),
            }
        )
        
    except ValueError as e:
        # Errores de validación o formato no soportado
        logger.warning(
            "action=alarmas_ciena_validation_error user=%s error=%s",
            username,
            str(e)
        )
        return JSONResponse(
            {"error": str(e)},
            status_code=415  # Unsupported Media Type
        )
        
    except Exception as e:
        # Errores inesperados
        logger.error(
            "action=alarmas_ciena_error user=%s error=%s",
            username,
            str(e),
            exc_info=True
        )
        return JSONResponse(
            {"error": f"Error al procesar el archivo: {str(e)}"},
            status_code=500
        )


@app.post("/api/tools/compare-vlans")
async def tool_compare_vlans(request: Request, payload: VLANCompareRequest) -> JSONResponse:
    """Compara las VLANs permitidas entre dos interfaces Cisco."""

    username, _ = _require_auth(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not payload.csrf_token or payload.csrf_token != expected_csrf):
        logger.warning("action=vlan_compare result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    vlans_a = parse_cisco_vlans(payload.text_a)
    vlans_b = parse_cisco_vlans(payload.text_b)
    missing_sections: list[str] = []
    if not vlans_a:
        missing_sections.append("Interfaz A")
    if not vlans_b:
        missing_sections.append("Interfaz B")
    if missing_sections:
        detail = " y ".join(missing_sections)
        logger.warning(
            "action=vlan_compare result=fail reason=empty user=%s missing=%s",
            username,
            ",".join(missing_sections),
        )
        return JSONResponse(
            {
                "error": f"No se detectaron VLANs en {detail}. Asegurate de incluir líneas 'switchport trunk allowed vlan'.",
            },
            status_code=400,
        )

    diff = compare_vlan_sets(vlans_a, vlans_b)
    response = {
        "vlans_a": diff.vlans_a,
        "vlans_b": diff.vlans_b,
        "only_a": diff.only_a,
        "only_b": diff.only_b,
        "common": diff.common,
        "total_a": len(diff.vlans_a),
        "total_b": len(diff.vlans_b),
    }
    logger.info(
        "action=vlan_compare result=success user=%s total_a=%s total_b=%s only_a=%s only_b=%s common=%s",
        username,
        response["total_a"],
        response["total_b"],
        len(response["only_a"]),
        len(response["only_b"]),
        len(response["common"]),
    )
    return JSONResponse(response)


# =============================================================================
# INFRAESTRUCTURA / CÁMARAS
# =============================================================================

class CamaraResponseModel(BaseModel):
    """Modelo de respuesta para una cámara."""

    id: int
    nombre: str
    fontine_id: Optional[str] = None
    direccion: Optional[str] = None
    estado: str
    origen_datos: str
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    servicios: List[str] = []


class CamarasListResponseModel(BaseModel):
    """Modelo de respuesta para lista de cámaras."""

    status: str
    total: int
    camaras: List[CamaraResponseModel]


@app.get("/api/infra/camaras")
async def search_camaras_web(
    request: Request,
    q: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = 100,
) -> JSONResponse:
    """Busca cámaras por query y/o estado (proxy al API interno)."""

    username, _ = _require_auth(request)
    limit = min(limit, 500)

    try:
        from db.models.infra import Camara, CamaraEstado, Servicio, RutaServicio, ruta_empalme_association
        from db.session import SessionLocal

        with SessionLocal() as session:
            query = session.query(Camara)

            # Filtro por estado
            if estado:
                estado_upper = estado.upper()
                if estado_upper in [e.value for e in CamaraEstado]:
                    query = query.filter(Camara.estado == CamaraEstado(estado_upper))

            # Filtro por texto
            if q and q.strip():
                search_term = f"%{q.strip()}%"
                query = query.filter(
                    (Camara.nombre.ilike(search_term)) |
                    (Camara.direccion.ilike(search_term)) |
                    (Camara.fontine_id.ilike(search_term))
                )

            camaras_db = query.order_by(Camara.nombre).limit(limit).all()

            # Construir respuesta con servicios y rutas
            camaras_response = []
            for cam in camaras_db:
                # Obtener rutas asociadas a esta cámara a través de empalmes
                rutas_info = []
                seen_rutas = set()
                
                for empalme in cam.empalmes:
                    for ruta in empalme.rutas:
                        if ruta.id not in seen_rutas:
                            seen_rutas.add(ruta.id)
                            rutas_info.append({
                                "ruta_id": ruta.id,
                                "servicio_id": ruta.servicio.servicio_id,
                                "ruta_nombre": ruta.nombre,
                                "ruta_tipo": ruta.tipo.value,
                            })

                # Para retrocompatibilidad, mantener lista simple de servicios
                servicios_ids = list(set(r["servicio_id"] for r in rutas_info))

                camaras_response.append({
                    "id": cam.id,
                    "nombre": cam.nombre or "",
                    "fontine_id": cam.fontine_id,
                    "direccion": cam.direccion,
                    "estado": cam.estado.value if cam.estado else "LIBRE",
                    "origen_datos": cam.origen_datos.value if cam.origen_datos else "MANUAL",
                    "latitud": cam.latitud,
                    "longitud": cam.longitud,
                    "servicios": servicios_ids,
                    "rutas": rutas_info,
                })

            # Buscar por servicio_id si no se encontraron cámaras
            if q and q.strip() and not camaras_response:
                servicio = session.query(Servicio).filter(
                    Servicio.servicio_id.ilike(f"%{q.strip()}%")
                ).first()

                if servicio:
                    # Obtener cámaras a través de las rutas del servicio
                    seen_cam_ids = set()
                    for ruta in servicio.rutas:
                        for empalme in ruta.empalmes:
                            if empalme.camara and empalme.camara.id not in seen_cam_ids:
                                seen_cam_ids.add(empalme.camara.id)
                                cam = empalme.camara
                                
                                # Obtener todas las rutas de esta cámara
                                rutas_info = []
                                seen_rutas = set()
                                for emp in cam.empalmes:
                                    for r in emp.rutas:
                                        if r.id not in seen_rutas:
                                            seen_rutas.add(r.id)
                                            rutas_info.append({
                                                "ruta_id": r.id,
                                                "servicio_id": r.servicio.servicio_id,
                                                "ruta_nombre": r.nombre,
                                                "ruta_tipo": r.tipo.value,
                                            })
                                
                                servicios_ids = list(set(r["servicio_id"] for r in rutas_info))

                                camaras_response.append({
                                    "id": cam.id,
                                    "nombre": cam.nombre or "",
                                    "fontine_id": cam.fontine_id,
                                    "direccion": cam.direccion,
                                    "estado": cam.estado.value if cam.estado else "LIBRE",
                                    "origen_datos": cam.origen_datos.value if cam.origen_datos else "MANUAL",
                                    "latitud": cam.latitud,
                                    "longitud": cam.longitud,
                                    "servicios": servicios_ids,
                                    "rutas": rutas_info,
                                })

            logger.info(
                "action=search_camaras user=%s query=%s estado=%s results=%d",
                username,
                q,
                estado,
                len(camaras_response),
            )

            return JSONResponse({
                "status": "ok",
                "total": len(camaras_response),
                "camaras": camaras_response,
            })

    except Exception as exc:
        logger.exception("action=search_camaras_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"error": f"Error buscando cámaras: {exc!s}"},
            status_code=500
        )


@app.get("/api/infra/servicios/{servicio_id}/rutas")
async def get_servicio_rutas_web(
    request: Request,
    servicio_id: str,
) -> JSONResponse:
    """Obtiene las rutas de un servicio para el wizard de baneo."""
    
    username, _ = _require_auth(request)
    
    try:
        from db.models.infra import Servicio, RutaServicio
        from db.session import SessionLocal
        
        with SessionLocal() as session:
            servicio = session.query(Servicio).filter(
                Servicio.servicio_id == servicio_id
            ).first()
            
            if not servicio:
                return JSONResponse(
                    {"error": f"Servicio {servicio_id} no encontrado"},
                    status_code=404
                )
            
            rutas_info = []
            for ruta in servicio.rutas:
                rutas_info.append({
                    "id": ruta.id,
                    "nombre": ruta.nombre,
                    "tipo": ruta.tipo.value if ruta.tipo else "PRINCIPAL",
                    "hash_contenido": ruta.hash_contenido,
                    "empalmes_count": len(ruta.empalmes),
                    "activa": bool(ruta.activa),
                    "created_at": ruta.created_at.isoformat() if ruta.created_at else None,
                    "nombre_archivo_origen": ruta.nombre_archivo_origen,
                })
            
            logger.info(
                "action=get_servicio_rutas user=%s servicio_id=%s rutas=%d",
                username,
                servicio_id,
                len(rutas_info),
            )
            
            return JSONResponse({
                "status": "ok",
                "servicio_id": servicio.servicio_id,
                "servicio_db_id": servicio.id,
                "cliente": servicio.cliente,
                "rutas": rutas_info,
                "total_rutas": len(rutas_info),
            })
            
    except Exception as exc:
        logger.exception("action=get_servicio_rutas_error user=%s servicio_id=%s error=%s", username, servicio_id, exc)
        return JSONResponse(
            {"error": f"Error obteniendo rutas: {exc!s}"},
            status_code=500
        )


@app.get("/api/infra/rutas/{ruta_id}/tracking")
async def get_ruta_tracking(
    request: Request,
    ruta_id: int,
) -> JSONResponse:
    """Obtiene el tracking completo de una ruta (secuencia cámara-cable-cámara)."""
    
    username, _ = _require_auth(request)
    
    try:
        from db.models.infra import RutaServicio, ruta_empalme_association
        from db.session import SessionLocal
        import json as json_module
        
        with SessionLocal() as session:
            ruta = session.query(RutaServicio).filter(RutaServicio.id == ruta_id).first()
            
            if not ruta:
                return JSONResponse({"error": "Ruta no encontrada"}, status_code=404)
            
            # Parsear el contenido original del tracking
            tracking_entries = []
            punta_a_info = None
            punta_b_info = None
            
            # Primero intentar parsear raw_file_content (el TXT original)
            if ruta.raw_file_content:
                from core.parsers.tracking_parser import parse_tracking
                parsed = parse_tracking(ruta.raw_file_content, ruta.nombre_archivo_origen or "")
                
                # Extraer puntas A y B del parsing
                if parsed.punta_a:
                    punta_a_info = {
                        "sitio": parsed.punta_a.sitio_descripcion or "",
                        "identificador": parsed.punta_a.identificador_fisico or "",
                        "conector": parsed.punta_a.pelo_conector or "",
                    }
                if parsed.punta_b:
                    punta_b_info = {
                        "sitio": parsed.punta_b.sitio_descripcion or "",
                        "identificador": parsed.punta_b.identificador_fisico or "",
                        "conector": parsed.punta_b.pelo_conector or "",
                    }
                
                # Construir secuencia cámara-cable desde entries
                for entry in parsed.entries:
                    if entry.tipo == "empalme":
                        tracking_entries.append({
                            "tipo": "camara",
                            "descripcion": entry.empalme_descripcion or "",
                            "empalme_id": entry.empalme_id,
                        })
                    elif entry.tipo == "tramo":
                        tracking_entries.append({
                            "tipo": "cable",
                            "nombre": entry.cable_nombre or "",
                            "atenuacion_db": entry.atenuacion_db,
                        })
                
                # Extraer terminales de primera/última línea si no hay puntas formales
                if not punta_a_info and parsed.entries:
                    # Buscar primer tramo con nombre de cable tipo ODF (O-xxxxx)
                    for entry in parsed.entries:
                        if entry.tipo == "tramo" and entry.cable_nombre:
                            # Extraer sitio:conector del raw_line si está presente
                            import re
                            match = re.search(r"(O-[\w-]+):\s*(\d+)", entry.raw_line)
                            if match:
                                punta_a_info = {
                                    "sitio": match.group(1),
                                    "identificador": "",
                                    "conector": match.group(2),
                                }
                            break
                
                if not punta_b_info and parsed.entries:
                    # Buscar último tramo con ODF
                    for entry in reversed(parsed.entries):
                        if entry.tipo == "tramo" and entry.cable_nombre:
                            import re
                            match = re.search(r"(O-[\w-]+):\s*(\d+)", entry.raw_line)
                            if match:
                                punta_b_info = {
                                    "sitio": match.group(1),
                                    "identificador": "",
                                    "conector": match.group(2),
                                }
                            break
            
            # Fallback a contenido_original (JSON guardado)
            elif ruta.contenido_original:
                try:
                    parsed = json_module.loads(ruta.contenido_original)
                    entries = parsed.get("entries", [])
                    
                    # Extraer info de puntas A y B
                    punta_a_raw = parsed.get("punta_a")
                    punta_b_raw = parsed.get("punta_b")
                    if punta_a_raw:
                        punta_a_info = {
                            "sitio": punta_a_raw.get("sitio_descripcion", ""),
                            "identificador": punta_a_raw.get("identificador_fisico", ""),
                            "conector": punta_a_raw.get("pelo_conector", ""),
                        }
                    if punta_b_raw:
                        punta_b_info = {
                            "sitio": punta_b_raw.get("sitio_descripcion", ""),
                            "identificador": punta_b_raw.get("identificador_fisico", ""),
                            "conector": punta_b_raw.get("pelo_conector", ""),
                        }
                    
                    # Construir secuencia cámara-cable
                    for entry in entries:
                        if entry.get("tipo") == "empalme":
                            tracking_entries.append({
                                "tipo": "camara",
                                "descripcion": entry.get("empalme_descripcion", ""),
                                "empalme_id": entry.get("empalme_id"),
                            })
                        elif entry.get("tipo") == "tramo":
                            tracking_entries.append({
                                "tipo": "cable",
                                "nombre": entry.get("cable_nombre", ""),
                                "atenuacion_db": entry.get("atenuacion_db"),
                            })
                except json_module.JSONDecodeError:
                    pass
            
            # Si no hay contenido original, construir desde empalmes
            if not tracking_entries:
                for empalme in ruta.empalmes:
                    tracking_entries.append({
                        "tipo": "camara",
                        "descripcion": empalme.camara.nombre if empalme.camara else "Sin cámara",
                        "empalme_id": empalme.tracking_empalme_id,
                    })
            
            return JSONResponse({
                "status": "ok",
                "ruta_id": ruta.id,
                "servicio_id": ruta.servicio.servicio_id,
                "ruta_nombre": ruta.nombre,
                "ruta_tipo": ruta.tipo.value,
                "tracking": tracking_entries,
                "punta_a": punta_a_info,
                "punta_b": punta_b_info,
            })
    
    except Exception as exc:
        logger.exception("action=get_ruta_tracking_error ruta_id=%d error=%s", ruta_id, exc)
        return JSONResponse(
            {"error": f"Error obteniendo tracking: {exc!s}"},
            status_code=500
        )


@app.get("/api/infra/rutas/{ruta_id}/download")
async def download_ruta_tracking(
    request: Request,
    ruta_id: int,
) -> Response:
    """Descarga el tracking de una ruta como archivo TXT."""
    
    username, _ = _require_auth(request)
    
    try:
        from db.models.infra import RutaServicio
        from db.session import SessionLocal
        import json as json_module
        
        with SessionLocal() as session:
            ruta = session.query(RutaServicio).filter(RutaServicio.id == ruta_id).first()
            
            if not ruta:
                return JSONResponse({"error": "Ruta no encontrada"}, status_code=404)
            
            # Reconstruir formato de tracking TXT
            servicio_id = ruta.servicio.servicio_id if ruta.servicio else "unknown"
            lines = [
                f"# Tracking de Ruta - Servicio {servicio_id}",
                f"# Ruta: {ruta.nombre} ({ruta.tipo.value if ruta.tipo else 'PRINCIPAL'})",
                f"# Exportado: {__import__('datetime').datetime.now().isoformat()}",
                "",
            ]
            
            # Intentar usar contenido original si existe
            if ruta.contenido_original:
                try:
                    parsed = json_module.loads(ruta.contenido_original)
                    entries = parsed.get("entries", [])
                    
                    for entry in entries:
                        if entry.get("tipo") == "empalme":
                            desc = entry.get("empalme_descripcion", "Empalme")
                            lines.append(f"EMPALME: {desc}")
                        elif entry.get("tipo") == "tramo":
                            cable = entry.get("cable_nombre", "Cable")
                            atten = entry.get("atenuacion_db", 0)
                            lines.append(f"  └─ CABLE: {cable} ({atten} dB)")
                except json_module.JSONDecodeError:
                    pass
            
            # Si no hay contenido original, usar empalmes de la ruta
            if len(lines) <= 4:
                for empalme in ruta.empalmes:
                    if empalme.camara:
                        lines.append(f"CAMARA: {empalme.camara.nombre or empalme.camara.direccion or 'Sin nombre'}")
                    lines.append(f"  └─ EMPALME: {empalme.descripcion or empalme.nombre or 'Empalme'}")
            
            content = "\\n".join(lines)
            filename = f"tracking_{servicio_id}_{ruta.nombre.replace(' ', '_')}.txt"
            
            logger.info("action=download_tracking user=%s ruta_id=%d servicio=%s", username, ruta_id, servicio_id)
            
            return Response(
                content=content,
                media_type="text/plain; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                }
            )
            
    except Exception as exc:
        logger.exception("action=download_tracking_error ruta_id=%d error=%s", ruta_id, exc)
        return JSONResponse(
            {"error": f"Error descargando tracking: {exc!s}"},
            status_code=500
        )


# -----------------------------------------------------------------------------
# ALIAS: TRACKING DOWNLOAD (para compatibilidad con panel.js)
# -----------------------------------------------------------------------------

@app.get("/api/infra/tracking/{ruta_id}/download")
async def download_tracking_alias(
    request: Request,
    ruta_id: int,
) -> Response:
    """Alias de /api/infra/rutas/{ruta_id}/download para compatibilidad."""
    
    username, _ = _require_auth(request)
    
    try:
        from db.models.infra import RutaServicio
        from db.session import SessionLocal
        
        with SessionLocal() as session:
            ruta = session.query(RutaServicio).filter(RutaServicio.id == ruta_id).first()
            
            if not ruta:
                return JSONResponse({"error": "Ruta no encontrada"}, status_code=404)
            
            # Usar raw_file_content si existe
            if ruta.raw_file_content:
                filename = ruta.nombre_archivo_origen or f"tracking_ruta_{ruta_id}.txt"
                
                return Response(
                    content=ruta.raw_file_content,
                    media_type="text/plain; charset=utf-8",
                    headers={
                        "Content-Disposition": f'attachment; filename="{filename}"',
                    }
                )
            
            # No hay contenido original
            return JSONResponse(
                {"error": "Archivo original no disponible para esta ruta"},
                status_code=404
            )
            
    except Exception as exc:
        logger.exception("action=download_tracking_alias_error ruta_id=%d error=%s", ruta_id, exc)
        return JSONResponse(
            {"error": f"Error descargando tracking: {exc!s}"},
            status_code=500
        )


# -----------------------------------------------------------------------------
# ENDPOINTS DE BANEO (Protocolo de Protección)
# -----------------------------------------------------------------------------

class BanCreateRequestModel(BaseModel):
    """Request para crear un baneo."""
    ticket_asociado: Optional[str] = None
    servicio_afectado_id: str
    servicio_protegido_id: str
    ruta_protegida_id: Optional[int] = None
    motivo: Optional[str] = None


@app.post("/api/infra/ban/create")
async def create_ban_web(
    request: Request,
    ban_request: BanCreateRequestModel,
) -> JSONResponse:
    """Crea un incidente de baneo y marca las cámaras como BANEADAS."""
    
    username, _ = _require_auth(request)
    
    try:
        from core.services.protection_service import create_ban as do_create_ban
        from db.session import SessionLocal
        
        with SessionLocal() as session:
            result = do_create_ban(
                session,
                ticket_asociado=ban_request.ticket_asociado,
                servicio_afectado_id=ban_request.servicio_afectado_id,
                servicio_protegido_id=ban_request.servicio_protegido_id,
                ruta_protegida_id=ban_request.ruta_protegida_id,
                usuario_ejecutor=username,
                motivo=ban_request.motivo,
            )
            
            if result.success:
                session.commit()
                logger.info(
                    "action=create_ban user=%s ticket=%s servicio_afectado=%s servicio_protegido=%s camaras=%d",
                    username,
                    ban_request.ticket_asociado,
                    ban_request.servicio_afectado_id,
                    ban_request.servicio_protegido_id,
                    result.camaras_baneadas,
                )
            else:
                session.rollback()
                logger.warning(
                    "action=create_ban_failed user=%s error=%s",
                    username,
                    result.message,
                )
            
            return JSONResponse(result.to_dict())
            
    except Exception as exc:
        logger.exception("action=create_ban_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"success": False, "error": f"Error creando baneo: {exc!s}"},
            status_code=500
        )


@app.get("/api/infra/ban/active")
async def get_active_bans_web(request: Request) -> JSONResponse:
    """Obtiene todos los incidentes de baneo activos."""
    
    username, _ = _require_auth(request)
    
    try:
        from core.services.protection_service import get_incidentes_activos
        from db.session import SessionLocal
        
        with SessionLocal() as session:
            incidentes = get_incidentes_activos(session)
            
            incidentes_data = []
            for inc in incidentes:
                duracion = None
                if inc.fecha_inicio:
                    from datetime import datetime, timezone
                    ahora = datetime.now(timezone.utc)
                    duracion = (ahora - inc.fecha_inicio).total_seconds() / 3600
                
                incidentes_data.append({
                    "id": inc.id,
                    "ticket_asociado": inc.ticket_asociado,
                    "servicio_afectado_id": inc.servicio_afectado_id,
                    "servicio_protegido_id": inc.servicio_protegido_id,
                    "ruta_protegida_id": inc.ruta_protegida_id,
                    "usuario_ejecutor": inc.usuario_ejecutor,
                    "motivo": inc.motivo,
                    "fecha_inicio": inc.fecha_inicio.isoformat() if inc.fecha_inicio else None,
                    "activo": inc.activo,
                    "duracion_horas": round(duracion, 1) if duracion else None,
                })
            
            logger.info("action=get_active_bans user=%s count=%d", username, len(incidentes_data))
            
            return JSONResponse({
                "status": "ok",
                "incidentes": incidentes_data,
                "total": len(incidentes_data),
            })
            
    except Exception as exc:
        logger.exception("action=get_active_bans_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"error": f"Error obteniendo baneos activos: {exc!s}"},
            status_code=500
        )


class BanLiftRequestModel(BaseModel):
    """Request para levantar un baneo."""
    incidente_id: int
    motivo_cierre: Optional[str] = None


@app.post("/api/infra/ban/lift")
async def lift_ban_web(
    request: Request,
    lift_request: BanLiftRequestModel,
) -> JSONResponse:
    """Levanta un baneo y restaura el estado de las cámaras."""
    
    username, _ = _require_auth(request)
    
    try:
        from core.services.protection_service import lift_ban as do_lift_ban
        from db.session import SessionLocal
        
        with SessionLocal() as session:
            result = do_lift_ban(
                session,
                lift_request.incidente_id,
                usuario_ejecutor=username,
                motivo_cierre=lift_request.motivo_cierre,
            )
            
            if result.success:
                session.commit()
                logger.info(
                    "action=lift_ban user=%s incidente_id=%d camaras_restauradas=%d",
                    username,
                    lift_request.incidente_id,
                    result.camaras_restauradas,
                )
            else:
                session.rollback()
                logger.warning(
                    "action=lift_ban_failed user=%s incidente_id=%d error=%s",
                    username,
                    lift_request.incidente_id,
                    result.message,
                )
            
            return JSONResponse(result.to_dict())
            
    except Exception as exc:
        logger.exception("action=lift_ban_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"success": False, "error": f"Error levantando baneo: {exc!s}"},
            status_code=500
        )


# -----------------------------------------------------------------------------
# ENDPOINTS DE NOTIFICACIÓN POR EMAIL
# -----------------------------------------------------------------------------

class EmailNotifyRequestModel(BaseModel):
    """Request para enviar notificación por email."""
    to: list[str]
    cc: Optional[list[str]] = None
    subject: str
    body: str
    incidente_ids: list[int] = []
    include_xls: bool = False
    include_txt: bool = False


@app.post("/api/infra/notify/email")
async def send_email_notification_web(
    request: Request,
    email_request: EmailNotifyRequestModel,
) -> JSONResponse:
    """Envía un correo electrónico con información de baneos."""
    
    username, _ = _require_auth(request)
    
    try:
        from core.services.email_service import EmailAttachment, get_email_service
        from db.models.infra import IncidenteBaneo
        from db.session import SessionLocal
        import io
        
        email_service = get_email_service()
        
        if not email_service.is_configured():
            return JSONResponse({
                "success": False,
                "message": "Servicio de email no configurado",
                "error": "SMTP no está configurado en el servidor",
            }, status_code=500)
        
        attachments: list = []
        
        with SessionLocal() as session:
            # Obtener incidentes
            incidentes = []
            if email_request.incidente_ids:
                incidentes = (
                    session.query(IncidenteBaneo)
                    .filter(IncidenteBaneo.id.in_(email_request.incidente_ids))
                    .all()
                )
            
            # Generar XLS si se solicita
            if email_request.include_xls and incidentes:
                try:
                    import pandas as pd
                    
                    rows = []
                    for incidente in incidentes:
                        for camara in incidente.camaras_afectadas:
                            rows.append({
                                "Incidente ID": incidente.id,
                                "Ticket": incidente.ticket_asociado or "-",
                                "Servicio Afectado": incidente.servicio_afectado_id,
                                "Servicio Protegido": incidente.servicio_protegido_id,
                                "Cámara ID": camara.id,
                                "Cámara Nombre": camara.nombre,
                                "Estado": camara.estado.value if camara.estado else "-",
                                "Fecha Inicio": (
                                    incidente.fecha_inicio.strftime("%Y-%m-%d %H:%M")
                                    if incidente.fecha_inicio else "-"
                                ),
                                "Motivo": incidente.motivo or "-",
                            })
                    
                    if rows:
                        df = pd.DataFrame(rows)
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine="openpyxl") as writer:
                            df.to_excel(writer, sheet_name="Baneos_Activos", index=False)
                        output.seek(0)
                        
                        attachments.append(
                            EmailAttachment(
                                filename="baneos_activos.xlsx",
                                content=output.getvalue(),
                                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )
                        )
                
                except ImportError:
                    logger.warning("action=notify_email warning=pandas_not_available skipping_xls=true")
            
            # Obtener TXT original si se solicita
            if email_request.include_txt and incidentes:
                from db.models.infra import Servicio
                
                for incidente in incidentes:
                    servicio = (
                        session.query(Servicio)
                        .filter(Servicio.servicio_id == incidente.servicio_protegido_id)
                        .first()
                    )
                    if servicio and servicio.rutas:
                        for ruta in servicio.rutas:
                            if ruta.raw_file_content:
                                filename = (
                                    ruta.nombre_archivo_origen
                                    or f"tracking_{servicio.servicio_id}.txt"
                                )
                                attachments.append(
                                    EmailAttachment(
                                        filename=filename,
                                        content=ruta.raw_file_content.encode("utf-8"),
                                        mime_type="text/plain; charset=utf-8",
                                    )
                                )
                                break
                        break
        
        # Enviar correo
        result = email_service.send_email(
            to=email_request.to,
            cc=email_request.cc,
            subject=email_request.subject,
            body=email_request.body,
            attachments=attachments if attachments else None,
        )
        
        logger.info(
            "action=send_email user=%s to=%s success=%s attachments=%d",
            username,
            email_request.to,
            result.success,
            len(attachments),
        )
        
        return JSONResponse({
            "success": result.success,
            "message": result.message,
            "error": result.error,
            "recipients_count": len(email_request.to) + len(email_request.cc or []),
        })
        
    except Exception as exc:
        logger.exception("action=send_email_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"success": False, "message": "Error enviando email", "error": str(exc)},
            status_code=500
        )


@app.get("/api/infra/notify/email/config")
async def get_email_config_web(request: Request) -> JSONResponse:
    """Obtiene el estado de configuración del email."""
    
    _require_auth(request)
    
    try:
        from core.services.email_service import get_email_service
        
        email_service = get_email_service()
        settings = email_service.settings
        
        return JSONResponse({
            "configured": email_service.is_configured(),
            "from_email": settings.from_email if email_service.is_configured() else None,
            "from_name": settings.from_name if email_service.is_configured() else None,
        })
        
    except Exception as exc:
        logger.exception("action=get_email_config_error error=%s", exc)
        return JSONResponse({"configured": False, "error": str(exc)})


# -----------------------------------------------------------------------------
# GENERACIÓN DE ARCHIVO EML (ALTERNATIVA A SMTP)
# -----------------------------------------------------------------------------

class EmlDownloadRequestModel(BaseModel):
    """Request para generar archivo .eml descargable."""
    incident_id: int
    recipients: str  # Emails separados por coma o punto y coma
    subject: str
    html_body: str = ""  # HTML completo del correo
    include_xls: bool = True
    include_txt: bool = True


DEFAULT_EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .header { background: #2563eb; color: white; padding: 20px; border-radius: 8px 8px 0 0; }
        .content { padding: 20px; background: #f8fafc; border: 1px solid #e2e8f0; }
        .footer { padding: 15px; background: #f1f5f9; border-radius: 0 0 8px 8px; font-size: 12px; color: #64748b; }
        table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #e2e8f0; }
        th { background: #f1f5f9; font-weight: 600; }
        .badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; }
        .badge-warning { background: #fef3c7; color: #92400e; }
    </style>
</head>
<body>
    <div class="header">
        <h2>🔒 Notificación de Protocolo de Protección</h2>
    </div>
    <div class="content">
        <p>Se ha activado el Protocolo de Protección en la red de fibra óptica.</p>
        <table>
            <tr><th>Ticket</th><td>{{ticket}}</td></tr>
            <tr><th>Servicio Afectado</th><td>{{servicio_afectado}}</td></tr>
            <tr><th>Servicio Protegido</th><td>{{servicio_protegido}}</td></tr>
            <tr><th>Cámaras Baneadas</th><td>{{total_camaras}}</td></tr>
            <tr><th>Fecha</th><td>{{fecha}}</td></tr>
            <tr><th>Motivo</th><td>{{motivo}}</td></tr>
        </table>
        <p>Se adjunta el detalle de las cámaras afectadas.</p>
    </div>
    <div class="footer">
        <p>Este mensaje fue generado automáticamente por LAS-FOCAS - Metrotel</p>
    </div>
</body>
</html>
"""


@app.post("/api/infra/notify/download-eml")
async def generate_eml_file(
    request: Request,
    eml_request: EmlDownloadRequestModel,
) -> Response:
    """Genera un archivo .eml descargable con el correo de notificación.
    
    Este endpoint es una alternativa cuando no se puede usar SMTP directamente
    (ej: Office 365 sin App Password). El usuario puede abrir el .eml con su
    cliente de correo y enviarlo manualmente.
    
    Args:
        eml_request: Datos del correo a generar
        
    Returns:
        Archivo .eml para descarga
    """
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formataddr, formatdate
    from datetime import datetime, timezone
    import io
    import re
    
    username, _ = _require_auth(request)
    
    try:
        from db.models.infra import IncidenteBaneo, Servicio
        from db.session import SessionLocal
        from core.config import get_settings
        
        settings = get_settings()
        
        # Parsear destinatarios (soporta coma, punto y coma, espacios)
        recipients_raw = re.split(r'[,;\s]+', eml_request.recipients.strip())
        recipients = [r.strip() for r in recipients_raw if r.strip() and '@' in r]
        
        if not recipients:
            return JSONResponse(
                {"error": "No se especificaron destinatarios válidos"},
                status_code=400
            )
        
        with SessionLocal() as session:
            # Obtener datos del incidente
            incidente = session.query(IncidenteBaneo).get(eml_request.incident_id)
            
            if not incidente:
                return JSONResponse(
                    {"error": f"Incidente {eml_request.incident_id} no encontrado"},
                    status_code=404
                )
            
            # Preparar variables para el template
            template_vars = {
                "ticket": incidente.ticket_asociado or f"INC-{incidente.id}",
                "servicio_afectado": incidente.servicio_afectado_id or "-",
                "servicio_protegido": incidente.servicio_protegido_id or "-",
                "total_camaras": len(incidente.camaras_afectadas),
                "fecha": incidente.fecha_inicio.strftime("%d/%m/%Y %H:%M") if incidente.fecha_inicio else "-",
                "motivo": incidente.motivo or "Sin especificar",
            }
            
            # Determinar el cuerpo HTML
            html_body = eml_request.html_body.strip()
            
            if not html_body:
                # Usar template por defecto
                html_body = DEFAULT_EMAIL_TEMPLATE
            
            # Reemplazar variables residuales {{variable}}
            for key, value in template_vars.items():
                html_body = html_body.replace(f"{{{{{key}}}}}", str(value))
            
            # Crear mensaje MIME
            msg = MIMEMultipart("mixed")
            msg["From"] = formataddr((
                settings.smtp.from_name or "LAS-FOCAS",
                settings.smtp.from_email or "notificaciones@lasfocas.local"
            ))
            msg["To"] = ", ".join(recipients)
            msg["Subject"] = eml_request.subject
            msg["Date"] = formatdate(localtime=True)
            msg["X-Mailer"] = "LAS-FOCAS Notification System"
            
            # Cuerpo HTML
            html_part = MIMEText(html_body, "html", "utf-8")
            msg.attach(html_part)
            
            attachments_info = []
            
            # Adjuntar Excel con cámaras baneadas
            if eml_request.include_xls:
                try:
                    import pandas as pd
                    
                    rows = []
                    for camara in incidente.camaras_afectadas:
                        rows.append({
                            "ID": camara.id,
                            "Nombre": camara.nombre or "",
                            "Fontine_ID": camara.fontine_id or "",
                            "Dirección": camara.direccion or "",
                            "Estado": camara.estado.value if camara.estado else "-",
                            "Ticket": incidente.ticket_asociado or f"INC-{incidente.id}",
                        })
                    
                    if rows:
                        df = pd.DataFrame(rows)
                        xls_buffer = io.BytesIO()
                        with pd.ExcelWriter(xls_buffer, engine="openpyxl") as writer:
                            df.to_excel(writer, sheet_name="Camaras_Baneadas", index=False)
                        xls_buffer.seek(0)
                        
                        xls_part = MIMEApplication(xls_buffer.getvalue())
                        xls_filename = f"camaras_baneadas_{incidente.ticket_asociado or incidente.id}.xlsx"
                        xls_part.add_header(
                            "Content-Disposition",
                            "attachment",
                            filename=xls_filename
                        )
                        msg.attach(xls_part)
                        attachments_info.append(xls_filename)
                        
                except ImportError:
                    logger.warning("action=generate_eml warning=pandas_not_available skipping_xls=true")
            
            # Adjuntar TXT original de tracking
            if eml_request.include_txt:
                servicio = session.query(Servicio).filter(
                    Servicio.servicio_id == incidente.servicio_protegido_id
                ).first()
                
                if servicio and servicio.rutas:
                    for ruta in servicio.rutas:
                        if ruta.raw_file_content:
                            txt_filename = (
                                ruta.nombre_archivo_origen
                                or f"tracking_{servicio.servicio_id}.txt"
                            )
                            txt_part = MIMEApplication(
                                ruta.raw_file_content.encode("utf-8"),
                                Name=txt_filename
                            )
                            txt_part.add_header(
                                "Content-Disposition",
                                "attachment",
                                filename=txt_filename
                            )
                            msg.attach(txt_part)
                            attachments_info.append(txt_filename)
                            break  # Solo un TXT
            
            # Generar contenido del .eml
            eml_content = msg.as_bytes()
            
            # Nombre del archivo .eml
            ticket_safe = re.sub(r'[^\w\-]', '_', incidente.ticket_asociado or f"INC_{incidente.id}")
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            eml_filename = f"notificacion_{ticket_safe}_{timestamp}.eml"
            
            logger.info(
                "action=generate_eml user=%s incident_id=%d recipients=%d attachments=%s",
                username,
                eml_request.incident_id,
                len(recipients),
                attachments_info,
            )
            
            return Response(
                content=eml_content,
                media_type="message/rfc822",
                headers={
                    "Content-Disposition": f'attachment; filename="{eml_filename}"',
                }
            )
            
    except Exception as exc:
        logger.exception("action=generate_eml_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"error": f"Error generando archivo EML: {exc!s}"},
            status_code=500
        )


# -----------------------------------------------------------------------------
# EXPORTACIÓN DE CÁMARAS
# -----------------------------------------------------------------------------

@app.get("/api/infra/export/cameras")
async def export_cameras_web(
    request: Request,
    filter_status: Optional[str] = None,
    servicio_id: Optional[str] = None,
    format: str = "csv",
) -> Response:
    """Exporta listado de cámaras a CSV o XLSX."""
    
    username, _ = _require_auth(request)
    
    try:
        from db.models.infra import Camara, CamaraEstado, IncidenteBaneo, Servicio
        from db.session import SessionLocal
        from datetime import datetime, timezone
        import csv
        import io
        
        with SessionLocal() as session:
            query = session.query(Camara)
            
            # Filtrar por estado
            if filter_status and filter_status.upper() != "ALL":
                estado_upper = filter_status.upper()
                if estado_upper in [e.value for e in CamaraEstado]:
                    query = query.filter(Camara.estado == CamaraEstado(estado_upper))
            
            # Filtrar por servicio
            if servicio_id:
                servicio = session.query(Servicio).filter(
                    Servicio.servicio_id == servicio_id
                ).first()
                
                if servicio:
                    camara_ids = set()
                    for ruta in servicio.rutas_activas:
                        for empalme in ruta.empalmes:
                            if empalme.camara:
                                camara_ids.add(empalme.camara.id)
                    
                    if camara_ids:
                        query = query.filter(Camara.id.in_(camara_ids))
                    else:
                        query = query.filter(Camara.id == -1)
            
            camaras = query.order_by(Camara.nombre).all()
            
            # Obtener tickets de baneo activos
            baneos_activos = session.query(IncidenteBaneo).filter(
                IncidenteBaneo.activo == True
            ).all()
            
            ticket_por_servicio: dict = {}
            for baneo in baneos_activos:
                ticket_por_servicio[baneo.servicio_protegido_id] = baneo.ticket_asociado or f"INC-{baneo.id}"
            
            # Preparar datos
            rows = []
            for cam in camaras:
                servicios_cat6 = []
                for empalme in cam.empalmes:
                    for srv in empalme.servicios:
                        if srv.servicio_id and srv.servicio_id not in servicios_cat6:
                            servicios_cat6.append(srv.servicio_id)
                
                ticket_baneo = ""
                if cam.estado == CamaraEstado.BANEADA:
                    for svc_id in servicios_cat6:
                        if svc_id in ticket_por_servicio:
                            ticket_baneo = ticket_por_servicio[svc_id]
                            break
                
                rows.append({
                    "ID": cam.id,
                    "Nombre": cam.nombre or "",
                    "Fontine_ID": cam.fontine_id or "",
                    "Dirección": cam.direccion or "",
                    "Estado": cam.estado.value if cam.estado else "LIBRE",
                    "Servicios_Cat6": ", ".join(servicios_cat6),
                    "Ticket_Baneo": ticket_baneo,
                    "Latitud": cam.latitud or "",
                    "Longitud": cam.longitud or "",
                    "Origen_Datos": cam.origen_datos.value if cam.origen_datos else "MANUAL",
                })
            
            logger.info(
                "action=export_cameras user=%s filter_status=%s format=%s rows=%d",
                username,
                filter_status,
                format,
                len(rows),
            )
            
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            
            if format.lower() == "xlsx":
                try:
                    import pandas as pd
                    
                    df = pd.DataFrame(rows)
                    output = io.BytesIO()
                    
                    with pd.ExcelWriter(output, engine="openpyxl") as writer:
                        df.to_excel(writer, sheet_name="Cámaras", index=False)
                    
                    output.seek(0)
                    
                    return Response(
                        content=output.getvalue(),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={
                            "Content-Disposition": f'attachment; filename="camaras_{timestamp}.xlsx"',
                        },
                    )
                    
                except ImportError:
                    logger.warning("action=export_cameras warning=pandas_not_available fallback=csv")
            
            # CSV (default)
            output = io.StringIO()
            if rows:
                writer = csv.DictWriter(output, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            else:
                output.write("Sin datos\\n")
            
            content = output.getvalue().encode("utf-8-sig")
            
            return Response(
                content=content,
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="camaras_{timestamp}.csv"',
                },
            )
            
    except Exception as exc:
        logger.exception("action=export_cameras_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"error": f"Error exportando cámaras: {exc!s}"},
            status_code=500
        )


class SearchFilterModel(BaseModel):
    """Filtro individual para búsqueda avanzada."""
    field: str
    operator: str = "contains"
    value: str | list[str]


class SearchRequestModel(BaseModel):
    """Request para búsqueda avanzada de cámaras."""
    filters: list[SearchFilterModel] = []
    limit: int = 100
    offset: int = 0


@app.post("/api/infra/search")
async def advanced_search_camaras_web(
    request: Request,
    body: SearchRequestModel,
) -> JSONResponse:
    """Búsqueda avanzada de cámaras con filtros combinables (AND).

    Campos: service_id, address, status, cable, origen
    Operadores: eq, contains, starts_with, ends_with, in
    """

    username, _ = _require_auth(request)

    try:
        from db.models.infra import Cable, Camara, CamaraEstado, CamaraOrigenDatos, Empalme, Servicio
        from db.session import SessionLocal

        limit = min(body.limit, 500)
        offset = max(body.offset, 0)

        with SessionLocal() as session:
            all_camaras = session.query(Camara).order_by(Camara.nombre).all()

            def apply_text_filter(value: str, operator: str, db_value: str | None) -> bool:
                if db_value is None:
                    return False
                db_lower = db_value.lower()
                val_lower = value.lower() if isinstance(value, str) else value

                if operator == "eq":
                    return db_lower == val_lower
                elif operator == "contains":
                    return val_lower in db_lower
                elif operator == "starts_with":
                    return db_lower.startswith(val_lower)
                elif operator == "ends_with":
                    return db_lower.endswith(val_lower)
                elif operator == "in":
                    if isinstance(value, list):
                        return db_lower in [v.lower() for v in value]
                    return db_lower == val_lower
                return False

            def get_camara_servicios(camara: Camara) -> list[str]:
                servicios_ids = []
                for empalme in camara.empalmes:
                    for servicio in empalme.servicios:
                        if servicio.servicio_id and servicio.servicio_id not in servicios_ids:
                            servicios_ids.append(servicio.servicio_id)
                return servicios_ids

            def get_camara_cables(camara: Camara) -> list[str]:
                cables_nombres = []
                for cable in camara.cables:
                    if cable.nombre and cable.nombre not in cables_nombres:
                        cables_nombres.append(cable.nombre)
                return cables_nombres

            def camara_matches_filter(camara, flt, servicios_ids, cables_nombres) -> bool:
                value = flt.value if isinstance(flt.value, str) else (flt.value[0] if flt.value else "")

                if flt.field == "service_id":
                    for svc_id in servicios_ids:
                        if apply_text_filter(value, flt.operator, svc_id):
                            return True
                    return False

                elif flt.field == "address":
                    return (
                        apply_text_filter(value, flt.operator, camara.nombre) or
                        apply_text_filter(value, flt.operator, camara.direccion)
                    )

                elif flt.field == "status":
                    estado_actual = camara.estado.value if camara.estado else "LIBRE"
                    if flt.operator == "in" and isinstance(flt.value, list):
                        return estado_actual.upper() in [v.upper() for v in flt.value]
                    return estado_actual.upper() == value.upper()

                elif flt.field == "cable":
                    for cable_nombre in cables_nombres:
                        if apply_text_filter(value, flt.operator, cable_nombre):
                            return True
                    return False

                elif flt.field == "origen":
                    origen_actual = camara.origen_datos.value if camara.origen_datos else "MANUAL"
                    if flt.operator == "in" and isinstance(flt.value, list):
                        return origen_actual.upper() in [v.upper() for v in flt.value]
                    return origen_actual.upper() == value.upper()

                return False

            # Si no hay filtros, devolver todas
            if not body.filters:
                total = len(all_camaras)
                paginated = all_camaras[offset:offset + limit]
                camaras_response = []
                for cam in paginated:
                    servicios_ids = get_camara_servicios(cam)
                    camaras_response.append({
                        "id": cam.id,
                        "nombre": cam.nombre or "",
                        "fontine_id": cam.fontine_id,
                        "direccion": cam.direccion,
                        "estado": cam.estado.value if cam.estado else "LIBRE",
                        "origen_datos": cam.origen_datos.value if cam.origen_datos else "MANUAL",
                        "latitud": cam.latitud,
                        "longitud": cam.longitud,
                        "servicios": servicios_ids,
                    })

                return JSONResponse({
                    "status": "ok",
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "filters_applied": 0,
                    "camaras": camaras_response,
                })

            # Aplicar filtros con lógica AND
            matching_camaras = []
            for camara in all_camaras:
                servicios_ids = get_camara_servicios(camara)
                cables_nombres = get_camara_cables(camara)

                matches_all = True
                for flt in body.filters:
                    if not camara_matches_filter(camara, flt, servicios_ids, cables_nombres):
                        matches_all = False
                        break

                if matches_all:
                    matching_camaras.append((camara, servicios_ids))

            total = len(matching_camaras)
            paginated = matching_camaras[offset:offset + limit]
            camaras_response = []
            for cam, svc_ids in paginated:
                camaras_response.append({
                    "id": cam.id,
                    "nombre": cam.nombre or "",
                    "fontine_id": cam.fontine_id,
                    "direccion": cam.direccion,
                    "estado": cam.estado.value if cam.estado else "LIBRE",
                    "origen_datos": cam.origen_datos.value if cam.origen_datos else "MANUAL",
                    "latitud": cam.latitud,
                    "longitud": cam.longitud,
                    "servicios": svc_ids,
                })

            logger.info(
                "action=advanced_search user=%s filters=%d total=%d returned=%d",
                username,
                len(body.filters),
                total,
                len(camaras_response),
            )

            return JSONResponse({
                "status": "ok",
                "total": total,
                "limit": limit,
                "offset": offset,
                "filters_applied": len(body.filters),
                "camaras": camaras_response,
            })

    except Exception as exc:
        logger.exception("action=advanced_search_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"error": f"Error en búsqueda avanzada: {exc!s}"},
            status_code=500
        )


class SmartSearchRequestModel(BaseModel):
    """Request para Smart Search con términos libres."""
    terms: list[str] = []
    limit: int = 100
    offset: int = 0


@app.post("/api/infra/smart-search")
async def smart_search_camaras_web(
    request: Request,
    body: SmartSearchRequestModel,
) -> JSONResponse:
    """Smart Search: búsqueda libre por términos.

    Cada término se busca en múltiples campos (nombre, dirección, fontine_id,
    servicios, cables, estado, origen). Los términos se combinan con AND.
    """

    username, _ = _require_auth(request)

    try:
        from db.models.infra import Camara
        from db.session import SessionLocal

        limit = min(body.limit, 500)
        offset = max(body.offset, 0)

        with SessionLocal() as session:
            all_camaras = session.query(Camara).order_by(Camara.nombre).all()

            def get_camara_rutas(camara: Camara) -> list[dict]:
                """Obtiene las rutas asociadas a una cámara a través de empalmes."""
                rutas_info = []
                seen_rutas = set()
                for empalme in camara.empalmes:
                    for ruta in empalme.rutas:
                        if ruta.id not in seen_rutas:
                            seen_rutas.add(ruta.id)
                            rutas_info.append({
                                "ruta_id": ruta.id,
                                "servicio_id": ruta.servicio.servicio_id,
                                "ruta_nombre": ruta.nombre,
                                "ruta_tipo": ruta.tipo.value,
                            })
                return rutas_info

            def get_camara_servicios(camara: Camara, rutas_info: list[dict] = None) -> list[str]:
                """Obtiene servicios desde rutas (preferido) o empalmes legacy."""
                if rutas_info:
                    return list(set(r["servicio_id"] for r in rutas_info))
                # Fallback: relación legacy
                servicios_ids = []
                for empalme in camara.empalmes:
                    for servicio in empalme.servicios:
                        if servicio.servicio_id and servicio.servicio_id not in servicios_ids:
                            servicios_ids.append(servicio.servicio_id)
                return servicios_ids

            def get_camara_cables(camara: Camara) -> list[str]:
                cables_nombres = []
                for cable in camara.cables:
                    if cable.nombre and cable.nombre not in cables_nombres:
                        cables_nombres.append(cable.nombre)
                return cables_nombres

            def term_matches_camara(term: str, camara, servicios_ids, cables_nombres) -> bool:
                term_lower = term.lower()

                # Buscar en nombre
                if camara.nombre and term_lower in camara.nombre.lower():
                    return True

                # Buscar en dirección
                if camara.direccion and term_lower in camara.direccion.lower():
                    return True

                # Buscar en fontine_id
                if camara.fontine_id and term_lower in camara.fontine_id.lower():
                    return True

                # Buscar en servicios
                for svc_id in servicios_ids:
                    if term_lower in svc_id.lower():
                        return True

                # Buscar en cables
                for cable_nombre in cables_nombres:
                    if term_lower in cable_nombre.lower():
                        return True

                # Buscar en estado
                estado_actual = camara.estado.value if camara.estado else "LIBRE"
                if term_lower in estado_actual.lower():
                    return True

                # Buscar en origen
                origen_actual = camara.origen_datos.value if camara.origen_datos else "MANUAL"
                if term_lower in origen_actual.lower():
                    return True

                return False

            # Si no hay términos, devolver todas
            if not body.terms:
                total = len(all_camaras)
                paginated = all_camaras[offset:offset + limit]
                camaras_response = []
                for cam in paginated:
                    rutas_info = get_camara_rutas(cam)
                    servicios_ids = get_camara_servicios(cam, rutas_info)
                    camaras_response.append({
                        "id": cam.id,
                        "nombre": cam.nombre or "",
                        "fontine_id": cam.fontine_id,
                        "direccion": cam.direccion,
                        "estado": cam.estado.value if cam.estado else "LIBRE",
                        "origen_datos": cam.origen_datos.value if cam.origen_datos else "MANUAL",
                        "latitud": cam.latitud,
                        "longitud": cam.longitud,
                        "servicios": servicios_ids,
                        "rutas": rutas_info,
                    })

                return JSONResponse({
                    "status": "ok",
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "filters_applied": 0,
                    "camaras": camaras_response,
                })

            # Aplicar términos con lógica AND
            matching_camaras = []
            for camara in all_camaras:
                rutas_info = get_camara_rutas(camara)
                servicios_ids = get_camara_servicios(camara, rutas_info)
                cables_nombres = get_camara_cables(camara)

                matches_all = True
                for term in body.terms:
                    term_clean = term.strip()
                    if not term_clean:
                        continue
                    if not term_matches_camara(term_clean, camara, servicios_ids, cables_nombres):
                        matches_all = False
                        break

                if matches_all:
                    matching_camaras.append((camara, servicios_ids, rutas_info))

            total = len(matching_camaras)
            paginated = matching_camaras[offset:offset + limit]
            camaras_response = []
            for cam, svc_ids, rutas in paginated:
                camaras_response.append({
                    "id": cam.id,
                    "nombre": cam.nombre or "",
                    "fontine_id": cam.fontine_id,
                    "direccion": cam.direccion,
                    "estado": cam.estado.value if cam.estado else "LIBRE",
                    "origen_datos": cam.origen_datos.value if cam.origen_datos else "MANUAL",
                    "latitud": cam.latitud,
                    "longitud": cam.longitud,
                    "servicios": svc_ids,
                    "rutas": rutas,
                })

            terms_count = len([t for t in body.terms if t.strip()])
            logger.info(
                "action=smart_search user=%s terms=%d total=%d returned=%d",
                username,
                terms_count,
                total,
                len(camaras_response),
            )

            return JSONResponse({
                "status": "ok",
                "total": total,
                "limit": limit,
                "offset": offset,
                "filters_applied": terms_count,
                "camaras": camaras_response,
            })

    except Exception as exc:
        logger.exception("action=smart_search_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"error": f"Error en smart search: {exc!s}"},
            status_code=500
        )


@app.post("/api/infra/upload_tracking")
async def upload_tracking_web(
    request: Request,
    file: UploadFile = File(...),
) -> JSONResponse:
    """Procesa un archivo de tracking de fibra óptica."""

    username, _ = _require_auth(request)

    # Validar extensión
    if not file.filename or not file.filename.lower().endswith(".txt"):
        return JSONResponse(
            {"error": "El archivo debe tener extensión .txt"},
            status_code=400
        )

    try:
        from core.parsers.tracking_parser import parse_tracking
        from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos, Empalme, Servicio
        from db.session import SessionLocal
        from datetime import datetime, timezone

        # Leer contenido
        content = await file.read()
        try:
            raw_text = content.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = content.decode("latin-1")

        # Parsear
        result = parse_tracking(raw_text, file.filename)

        if not result.servicio_id:
            return JSONResponse(
                {"error": f"No se pudo extraer el ID del servicio desde: {file.filename}"},
                status_code=400
            )

        topologia = result.get_topologia()
        if not topologia:
            return JSONResponse(
                {"error": "No se encontraron empalmes/ubicaciones en el archivo"},
                status_code=400
            )

        logger.info(
            "action=upload_tracking user=%s filename=%s servicio_id=%s empalmes=%d",
            username,
            file.filename,
            result.servicio_id,
            len(topologia),
        )

        camaras_nuevas = 0
        camaras_existentes = 0
        empalmes_registrados = 0

        with SessionLocal() as session:
            # Obtener o crear servicio
            servicio = session.query(Servicio).filter(
                Servicio.servicio_id == result.servicio_id
            ).first()

            if servicio:
                servicio.nombre_archivo_origen = file.filename
            else:
                servicio = Servicio(
                    servicio_id=result.servicio_id,
                    nombre_archivo_origen=file.filename,
                )
                session.add(servicio)
                session.flush()

            servicio.raw_tracking_data = result.to_dict()

            # Procesar empalmes
            for empalme_id, ubicacion in topologia:
                # Buscar cámara
                nombre_norm = " ".join(ubicacion.strip().lower().split())
                camara = session.query(Camara).filter(Camara.nombre == ubicacion).first()

                if not camara:
                    # Buscar normalizado
                    all_cams = session.query(Camara).all()
                    for c in all_cams:
                        if c.nombre and " ".join(c.nombre.strip().lower().split()) == nombre_norm:
                            camara = c
                            break

                if camara:
                    camaras_existentes += 1
                else:
                    camara = Camara(
                        nombre=ubicacion.strip(),
                        estado=CamaraEstado.DETECTADA,
                        origen_datos=CamaraOrigenDatos.TRACKING,
                        last_update=datetime.now(timezone.utc),
                    )
                    session.add(camara)
                    session.flush()
                    camaras_nuevas += 1

                # Registrar empalme
                tracking_id_completo = f"{result.servicio_id}_{empalme_id}"
                empalme = session.query(Empalme).filter(
                    Empalme.tracking_empalme_id == tracking_id_completo
                ).first()

                if empalme:
                    if empalme.camara_id != camara.id:
                        empalme.camara_id = camara.id
                    if servicio not in empalme.servicios:
                        empalme.servicios.append(servicio)
                else:
                    empalme = Empalme(
                        tracking_empalme_id=tracking_id_completo,
                        camara_id=camara.id,
                    )
                    session.add(empalme)
                    session.flush()
                    empalme.servicios.append(servicio)
                    empalmes_registrados += 1

            session.commit()

            logger.info(
                "action=upload_tracking_complete user=%s servicio_id=%s camaras_nuevas=%d "
                "camaras_existentes=%d empalmes=%d",
                username,
                result.servicio_id,
                camaras_nuevas,
                camaras_existentes,
                empalmes_registrados,
            )

            return JSONResponse({
                "status": "ok",
                "servicios_procesados": 1,
                "servicio_id": result.servicio_id,
                "camaras_nuevas": camaras_nuevas,
                "camaras_existentes": camaras_existentes,
                "empalmes_registrados": empalmes_registrados,
                "mensaje": f"Tracking del servicio {result.servicio_id} procesado correctamente",
            })

    except Exception as exc:
        logger.exception(
            "action=upload_tracking_error user=%s filename=%s error=%s",
            username,
            file.filename,
            exc,
        )
        return JSONResponse(
            {"error": f"Error procesando el archivo: {exc!s}"},
            status_code=500
        )


# =============================================================================
# TRACKING V2: ANÁLISIS Y RESOLUCIÓN INTELIGENTE
# =============================================================================


class TrackingResolveRequestModel(BaseModel):
    """Request para resolver un tracking."""
    action: str  # CREATE_NEW, MERGE_APPEND, REPLACE, BRANCH
    content: str
    filename: str
    target_ruta_id: Optional[int] = None
    new_ruta_name: Optional[str] = None
    new_ruta_tipo: Optional[str] = None  # PRINCIPAL, BACKUP, ALTERNATIVA


@app.post("/api/infra/trackings/analyze")
async def analyze_tracking_web(
    request: Request,
    file: UploadFile = File(...),
) -> JSONResponse:
    """Analiza un archivo de tracking (Fase 1 del Portero).
    
    Detecta si el servicio es nuevo, idéntico o hay conflicto.
    """
    username, _ = _require_auth(request)
    
    # Leer contenido del archivo
    raw_bytes = await file.read()
    try:
        raw_content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raw_content = raw_bytes.decode("latin-1")
    
    filename_used = file.filename or "unknown.txt"
    
    try:
        from core.services.infra_service import InfraService
        from db.session import SessionLocal
        
        with SessionLocal() as session:
            service = InfraService(session)
            result = service.analyze_tracking(raw_content, filename_used)
            
            logger.info(
                "action=analyze_tracking user=%s filename=%s status=%s servicio=%s",
                username,
                filename_used,
                result.status.value,
                result.servicio_id,
            )
            
            # Convertir rutas_existentes a dict
            rutas_list = []
            for r in result.rutas_existentes:
                rutas_list.append(r.to_dict())
            
            # Sugerir acción basada en el status
            suggested_action = None
            if result.status.value == "NEW":
                suggested_action = "CREATE_NEW"
            elif result.status.value == "IDENTICAL":
                suggested_action = "SKIP"
            elif result.status.value == "CONFLICT":
                suggested_action = "REPLACE"  # Default, el usuario puede elegir otra
            
            return JSONResponse({
                "status": result.status.value,
                "servicio_id": result.servicio_id,
                "servicio_db_id": result.servicio_db_id,
                "nuevo_hash": result.nuevo_hash,
                "rutas_existentes": rutas_list,
                "ruta_identica_id": result.ruta_identica_id,
                "parsed_empalmes_count": result.parsed_empalmes_count,
                "empalmes_nuevos": result.parsed_empalmes_count,
                "message": result.message,
                "error": result.error,
                "suggested_action": suggested_action,
                "hash_match": result.ruta_identica_id is not None,
            })
            
    except Exception as exc:
        logger.exception(
            "action=analyze_tracking_error user=%s filename=%s error=%s",
            username,
            filename_used,
            exc,
        )
        return JSONResponse(
            {"error": f"Error analizando el archivo: {exc!s}"},
            status_code=500
        )


@app.post("/api/infra/trackings/resolve")
async def resolve_tracking_web(
    request: Request,
    body: TrackingResolveRequestModel,
) -> JSONResponse:
    """Resuelve un tracking ejecutando la acción (Fase 2 del Portero).
    
    Acciones: CREATE_NEW, MERGE_APPEND, REPLACE, BRANCH, ADD_STRAND, SKIP
    """
    username, _ = _require_auth(request)
    
    # Validar acción
    valid_actions = ["CREATE_NEW", "MERGE_APPEND", "REPLACE", "BRANCH", "ADD_STRAND", "SKIP"]
    action_upper = body.action.upper()
    if action_upper not in valid_actions:
        return JSONResponse(
            {"error": f"Acción inválida: {body.action}. Opciones: {', '.join(valid_actions)}"},
            status_code=400
        )
    
    # SKIP no hace nada
    if action_upper == "SKIP":
        return JSONResponse({
            "success": True,
            "action": "SKIP",
            "message": "Operación omitida por el usuario",
        })
    
    try:
        from core.services.infra_service import InfraService, ResolveAction, RutaTipo
        from db.session import SessionLocal
        
        # Convertir acción
        action = ResolveAction(action_upper)
        
        # Convertir tipo de ruta si se especifica
        ruta_tipo = RutaTipo.ALTERNATIVA
        if body.new_ruta_tipo:
            try:
                ruta_tipo = RutaTipo(body.new_ruta_tipo.upper())
            except ValueError:
                pass  # Usar default
        
        with SessionLocal() as session:
            service = InfraService(session)
            result = service.resolve_tracking(
                action=action,
                raw_content=body.content,
                filename=body.filename,
                target_ruta_id=body.target_ruta_id,
                new_ruta_name=body.new_ruta_name,
                new_ruta_tipo=ruta_tipo,
            )
            
            logger.info(
                "action=resolve_tracking user=%s action=%s servicio=%s success=%s",
                username,
                action_upper,
                result.servicio_id,
                result.success,
            )
            
            return JSONResponse({
                "success": result.success,
                "action": result.action.value,
                "servicio_id": result.servicio_id,
                "servicio_db_id": result.servicio_db_id,
                "ruta_id": result.ruta_id,
                "ruta_nombre": result.ruta_nombre,
                "camaras_nuevas": result.camaras_nuevas,
                "camaras_existentes": result.camaras_existentes,
                "empalmes_creados": result.empalmes_creados,
                "empalmes_asociados": result.empalmes_asociados,
                "message": result.message,
                "error": result.error,
            })
            
    except Exception as exc:
        logger.exception(
            "action=resolve_tracking_error user=%s action=%s error=%s",
            username,
            body.action,
            exc,
        )
        return JSONResponse(
            {"error": f"Error resolviendo el tracking: {exc!s}"},
            status_code=500
        )


@app.delete("/api/infra/servicios/{servicio_id}/empalmes")
async def delete_servicio_empalmes_web(
    request: Request,
    servicio_id: str,
) -> JSONResponse:
    """Elimina todas las asociaciones de empalmes de un servicio.
    
    ⚠️ PRECAUCIÓN: Operación destructiva.
    """
    username, _ = _require_auth(request)
    
    try:
        from db.models.infra import Servicio, RutaServicio
        from db.session import SessionLocal
        
        with SessionLocal() as session:
            servicio = session.query(Servicio).filter(
                Servicio.servicio_id == servicio_id
            ).first()
            
            if not servicio:
                return JSONResponse(
                    {"error": f"Servicio {servicio_id} no encontrado"},
                    status_code=404
                )
            
            # Contar antes de eliminar
            empalmes_legacy_count = len(servicio.empalmes)
            rutas_count = len(servicio.rutas)
            
            # Eliminar asociaciones legacy
            servicio.empalmes.clear()
            
            # Eliminar rutas
            for ruta in list(servicio.rutas):
                session.delete(ruta)
            
            session.commit()
            
            logger.info(
                "action=delete_servicio_empalmes user=%s servicio_id=%s empalmes=%d rutas=%d",
                username,
                servicio_id,
                empalmes_legacy_count,
                rutas_count,
            )
            
            return JSONResponse({
                "status": "ok",
                "servicio_id": servicio_id,
                "message": f"Eliminadas {empalmes_legacy_count} asociaciones y {rutas_count} rutas",
                "empalmes_legacy_eliminados": empalmes_legacy_count,
                "rutas_eliminadas": rutas_count,
            })
            
    except Exception as exc:
        logger.exception(
            "action=delete_servicio_empalmes_error user=%s servicio_id=%s error=%s",
            username,
            servicio_id,
            exc,
        )
        return JSONResponse(
            {"error": f"Error eliminando asociaciones: {exc!s}"},
            status_code=500
        )