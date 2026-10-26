# Nombre de archivo: dependencias.py
# Ubicación de archivo: web/app/dependencias.py
# Descripción: Dependencias FastAPI de sesión (usuario logueado / admin) para los routers de la SPA

"""Dependencias de sesión para `Depends(...)`.

La lógica de autenticación vive en un solo lugar: `comun._require_auth` / `comun._require_admin`
(401 "No autenticado", 403 "Permisos insuficientes"). Estas dependencias sólo las envuelven y
devuelven un `UsuarioSesion`.

Uso en un router:

    router = APIRouter(dependencies=[Depends(usuario_sesion)])

    @router.get("/api/x")
    async def x(usuario: UsuarioSesion = Depends(usuario_sesion)) -> JSONResponse:
        username, role = usuario  # NamedTuple: se puede desempaquetar como el tuple de _require_auth

FastAPI cachea cada dependencia por request: declararla en el router y en la firma la evalúa una sola
vez. En tests se reemplazan con `app.dependency_overrides` (fixture `con_sesion` de tests/conftest.py).

CSRF: `requiere_csrf` se declara en cada `APIRouter` de la web (después de la de sesión, para que un
pedido sin sesión siga respondiendo 401) y valida todo POST/PUT/PATCH/DELETE. Los endpoints no
reciben ni comparan el token: `tests/test_web_csrf.py` falla si aparece una ruta mutante sin ella.
"""

from __future__ import annotations

import os
import secrets
from typing import NamedTuple

from fastapi import Request

# Se llama vía módulo (comun._require_*) y no con `from .comun import ...`: así un monkeypatch sobre
# comun también alcanza a estas dependencias.
from . import comun
from .errores import ErrorDeDominio

METODOS_MUTANTES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER = "X-CSRF-Token"
CSRF_CAMPO = "csrf_token"

# (método, path de la ruta) que no pueden exigir CSRF, cada uno con su motivo.
RUTAS_SIN_CSRF: frozenset[tuple[str, str]] = frozenset(
    {
        # Se llama antes de que exista sesión: el token lo emite este mismo endpoint.
        ("POST", "/api/auth/login"),
    }
)


class UsuarioSesion(NamedTuple):
    username: str
    role: str


async def usuario_sesion(request: Request) -> UsuarioSesion:
    """Usuario logueado; 401 si no hay sesión."""
    username, role = comun._require_auth(request)
    return UsuarioSesion(username, role)


async def usuario_admin(request: Request) -> UsuarioSesion:
    """Usuario logueado con rol admin; 401 sin sesión, 403 si no es admin."""
    username = comun._require_admin(request)
    return UsuarioSesion(username, "admin")


def csrf_omitido_en_tests() -> bool:
    """`TESTING=true` saltea la validación (fixture `csrf_real` de tests/conftest.py la reactiva)."""
    return os.getenv("TESTING", "false").lower() == "true"


async def _token_del_body(request: Request) -> str | None:
    """`csrf_token` del body JSON o de formulario (compatibilidad con el envío previo al header).

    FastAPI ya leyó y cacheó el body en el `Request` antes de resolver las dependencias (y si el
    endpoint lo lee a mano, lo hace sobre esa misma caché): leerlo acá no se lo consume al endpoint.
    """
    tipo = request.headers.get("content-type", "")
    try:
        if tipo.startswith("application/json"):
            datos = await request.json()
            valor = datos.get(CSRF_CAMPO) if isinstance(datos, dict) else None
        elif tipo.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
            valor = (await request.form()).get(CSRF_CAMPO)
        else:
            return None
    except Exception:  # noqa: BLE001 — un body ilegible es "sin token"; el endpoint reporta su error
        return None
    return valor if isinstance(valor, str) else None


async def requiere_csrf(request: Request) -> None:
    """403 `{"error": "CSRF inválido"}` si un pedido mutante no trae el token de la sesión.

    Acepta el header `X-CSRF-Token` (canónico) o `csrf_token` en el body (transición). Sin usuario en
    la sesión no decide: no hay sesión que falsificar y la autenticación del endpoint responde 401.
    """
    if request.method not in METODOS_MUTANTES:
        return
    ruta = request.scope.get("route")
    if (request.method, getattr(ruta, "path", request.url.path)) in RUTAS_SIN_CSRF:
        return
    if csrf_omitido_en_tests():
        return
    username = request.session.get("username")
    if not username:
        return
    esperado = request.session.get("csrf")
    token = request.headers.get(CSRF_HEADER) or await _token_del_body(request)
    if not esperado or not token or not secrets.compare_digest(token.encode(), str(esperado).encode()):
        comun.logger.warning(
            "action=csrf result=fail method=%s path=%s user=%s", request.method, request.url.path, username
        )
        raise ErrorDeDominio("CSRF inválido", status_code=403)
