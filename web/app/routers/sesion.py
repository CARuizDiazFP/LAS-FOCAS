# Nombre de archivo: sesion.py
# Ubicación de archivo: web/app/routers/sesion.py
# Descripción: Rutas de sesión de la app web: health, login/logout, cambio de contraseña y alta de usuarios

from __future__ import annotations

import secrets
import time
from time import time as now
from typing import Any, Dict

import psycopg
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from core.password import hash_password, verify_password

from ..comun import (
    BUILD_VERSION,
    DB_DSN,
    _env_int,
    logger,
)
from ..dependencias import UsuarioSesion, usuario_admin, usuario_sesion
from ..errores import ErrorDeDominio, error_interno, nueva_ref

# Sin dependencia a nivel router: health, auth/session, auth/login, auth/logout y logout son públicas.
# Las demás piden sesión con Depends en su firma.
router = APIRouter()

WEB_LOGIN_RATE_LIMIT_MAX = _env_int("WEB_LOGIN_RATE_LIMIT_MAX", 5)
WEB_LOGIN_RATE_LIMIT_WINDOW = _env_int("WEB_LOGIN_RATE_LIMIT_WINDOW", 60)
_LOGIN_ATTEMPTS: dict[tuple[str, str], tuple[int, float]] = {}


@router.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "web", "time": int(time.time())}


@router.get("/health/version")
async def health_version() -> Dict[str, Any]:
    return {"status": "ok", "service": "web", "version": BUILD_VERSION}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _login_rate_limit_key(ip: str, username: str) -> tuple[str, str]:
    user_key = username.strip().lower() or "-"
    return (ip, user_key)


def _login_rate_limit_exceeded(ip: str, username: str) -> bool:
    timestamp = now()
    window_start = timestamp - WEB_LOGIN_RATE_LIMIT_WINDOW
    expired = [key for key, (_, ts) in _LOGIN_ATTEMPTS.items() if ts < window_start]
    for key in expired:
        _LOGIN_ATTEMPTS.pop(key, None)

    key = _login_rate_limit_key(ip, username)
    count, first_ts = _LOGIN_ATTEMPTS.get(key, (0, timestamp))
    if timestamp - first_ts > WEB_LOGIN_RATE_LIMIT_WINDOW:
        count = 0
        first_ts = timestamp
    count += 1
    _LOGIN_ATTEMPTS[key] = (count, first_ts)
    return count > WEB_LOGIN_RATE_LIMIT_MAX


def _clear_login_rate_limit(ip: str, username: str) -> None:
    _LOGIN_ATTEMPTS.pop(_login_rate_limit_key(ip, username), None)


@router.get("/api/auth/session")
async def api_auth_session(request: Request) -> JSONResponse:
    """Devuelve el estado de la sesión actual (sin autenticación requerida)."""
    username = request.session.get("username")
    if not username:
        return JSONResponse({"authenticated": False, "username": None, "role": None, "csrf": None})
    return JSONResponse({
        "authenticated": True,
        "username": username,
        "role": request.session.get("role", "user"),
        "csrf": request.session.get("csrf"),
    })


@router.post("/api/auth/login")
async def api_auth_login(request: Request) -> JSONResponse:
    """Login vía JSON. Devuelve sesión o error."""
    try:
        body = await request.json()
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
    except Exception:
        return JSONResponse({"ok": False, "error": "Body inválido"}, status_code=400)

    ip = _client_ip(request)
    if _login_rate_limit_exceeded(ip, username):
        return JSONResponse({"ok": False, "error": "Demasiados intentos. Esperá un minuto."}, status_code=429)

    if not username or not password:
        return JSONResponse({"ok": False, "error": "Usuario y contraseña requeridos"}, status_code=400)

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
                        logger.error("action=api_login bcrypt_error username=%s error=%s", username, exc)
                if not row or not password_ok:
                    logger.warning("action=api_login result=fail username=%s ip=%s", username, ip)
                    return JSONResponse({"ok": False, "error": "Credenciales inválidas"}, status_code=401)
    except Exception as exc:  # noqa: BLE001
        # El texto `action=api_login result=error` no termina en `_error`: se conserva y gana la ref.
        ref = nueva_ref()
        logger.exception(
            "action=api_login result=error username=%s ip=%s error=%s ref=%s", username, ip, exc, ref
        )
        return JSONResponse({"ok": False, "error": f"Error interno (ref {ref})"}, status_code=500)

    csrf_token = secrets.token_urlsafe(32)
    request.session["username"] = username
    request.session["role"] = row[1] if row else "user"
    request.session["csrf"] = csrf_token
    _clear_login_rate_limit(ip, username)
    logger.info("action=api_login result=success username=%s role=%s ip=%s", username, row[1] if row else "user", ip)
    return JSONResponse({"ok": True, "username": username, "role": row[1] if row else "user", "csrf": csrf_token})


@router.post("/api/auth/logout")
async def api_auth_logout(request: Request) -> JSONResponse:
    """Cierra la sesión vía API."""
    request.session.clear()
    return JSONResponse({"ok": True})


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Compatibilidad hacia atrás — limpia sesión y redirige al SPA."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@router.get("/api/admin/me")
async def admin_me(usuario: UsuarioSesion = Depends(usuario_admin)) -> JSONResponse:
    """Devuelve datos del usuario admin autenticado. Usado por el SPA Vue para validar sesión."""
    return JSONResponse({"username": usuario.username, "role": "admin"})


@router.post("/api/users/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    csrf_token: str = Form(...),
    usuario: UsuarioSesion = Depends(usuario_sesion),
):
    # Autenticado (Depends) + CSRF
    user = usuario.username
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("change_password", exc, user=user)
    return JSONResponse({"status": "ok"})


ALLOWED_ROLES = {"admin", "ownergroup", "invitado"}


@router.post("/api/admin/users")
async def admin_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("invitado"),
    csrf_token: str = Form(...),
    usuario: UsuarioSesion = Depends(usuario_sesion),
):
    # Admin + CSRF. Con usuario_sesion (y no usuario_admin) para conservar el 403 {"error": "Solo admin"}.
    admin, role_sess = usuario
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("admin_create_user", exc, user=admin, username=username)
    return JSONResponse({"status": "ok"})
