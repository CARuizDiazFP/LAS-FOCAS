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
"""

from __future__ import annotations

from typing import NamedTuple

from fastapi import Request

# Se llama vía módulo (comun._require_*) y no con `from .comun import ...`: así un monkeypatch sobre
# comun también alcanza a estas dependencias.
from . import comun


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
