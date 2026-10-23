# Nombre de archivo: soporte_sesion.py
# Ubicación de archivo: tests/soporte_sesion.py
# Descripción: Sesión simulada de la SPA para tests vía app.dependency_overrides (fixture con_sesion)

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from web.app.dependencias import UsuarioSesion, usuario_admin, usuario_sesion

Activar = Callable[..., "UsuarioSesion | None"]


@contextmanager
def sesion_simulada(app: Any = None) -> Iterator[Activar]:
    """Reemplaza `usuario_sesion` y `usuario_admin` en `app.dependency_overrides` (default: la web).

    Devuelve `activar(rol="user", username="tester")`; `rol=None` simula "sin sesión". Los overrides
    llaman a las dependencias REALES con un request falso (`session={"username", "role"}`), así que
    401/403 salen de `comun._require_*` igual que en producción.

    Alcance: sólo endpoints que usan `Depends(usuario_sesion | usuario_admin)`; los que todavía llaman
    `_require_auth(request)` a mano siguen leyendo la cookie real.

    Al salir (aunque el bloque falle) restaura los overrides previos de esas dos dependencias y no
    toca los demás (p. ej. `get_async_db`).
    """
    if app is None:
        from web.app.main import app

    dependencias = (usuario_sesion, usuario_admin)
    previos = {dep: app.dependency_overrides.get(dep) for dep in dependencias}

    def activar(rol: str | None = "user", username: str = "tester") -> UsuarioSesion | None:
        sesion = {} if rol is None else {"username": username, "role": rol}
        request_falso = SimpleNamespace(session=sesion)

        async def _sesion() -> UsuarioSesion:
            return await usuario_sesion(request_falso)  # type: ignore[arg-type]

        async def _admin() -> UsuarioSesion:
            return await usuario_admin(request_falso)  # type: ignore[arg-type]

        app.dependency_overrides[usuario_sesion] = _sesion
        app.dependency_overrides[usuario_admin] = _admin
        return None if rol is None else UsuarioSesion(username, rol)

    try:
        yield activar
    finally:
        for dep, previo in previos.items():
            if previo is None:
                app.dependency_overrides.pop(dep, None)
            else:
                app.dependency_overrides[dep] = previo
