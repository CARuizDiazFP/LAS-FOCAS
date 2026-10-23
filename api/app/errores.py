# Nombre de archivo: errores.py
# Ubicación de archivo: api/app/errores.py
# Descripción: Errores de dominio tipados y respuesta 500 con referencia para la API interna (no v1)

"""Errores de la API interna.

Formato: la API interna responde sus errores como FastAPI (`{"detail": ...}`, el mismo cuerpo que
`HTTPException`), y así se conserva para no cambiarles el contrato a sus consumidores (proxies de la
web, bot). Mismo diseño que `web/app/errores.py`, con la clave `detail` en lugar de `error`:

- `ErrorDeDominio` y subclases → `{"detail": <mensaje>}` con su `status_code`.
- Excepción no controlada → 500 `{"detail": "Error interno (ref XXXXXXXX)"}`; el detalle va al log.

API v1 (`/api/v1/...`): su contrato de error no cambia. Una excepción no controlada ahí se loguea con
ref pero responde exactamente lo que respondía Starlette sin handler: 500 `text/plain`
"Internal Server Error". v1 no usa `ErrorDeDominio`.

`HTTPException` y `RequestValidationError` no pasan por acá. El módulo es independiente del de la
web: el contenedor api no incluye `web/`.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

# Logger del servicio (main.py hace setup_logging("api", ...)).
logger = logging.getLogger("api")

PREFIJO_API_V1 = "/api/v1/"


class ErrorDeDominio(Exception):
    """Error esperado del dominio; el handler global lo convierte en `{"detail": mensaje}`."""

    status_code: int = 400

    def __init__(self, mensaje: str, *, status_code: int | None = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        if status_code is not None:
            self.status_code = status_code


class NoEncontrado(ErrorDeDominio):
    status_code = 404


class DatoInvalido(ErrorDeDominio):
    status_code = 422


class Conflicto(ErrorDeDominio):
    status_code = 409


def nueva_ref() -> str:
    """Referencia corta (8 hex) para cruzar la respuesta 500 con su línea de log."""
    return secrets.token_hex(4)


def _loguear(accion: str, exc: BaseException, ref: str, contexto: Mapping[str, Any]) -> None:
    claves = "".join(f" {clave}=%s" for clave in contexto)
    logger.exception(
        "action=%s_error" + claves + " error=%s ref=%s",
        accion,
        *contexto.values(),
        exc,
        ref,
        exc_info=exc,
    )


def error_interno(
    accion: str,
    exc: BaseException,
    /,
    *,
    cuerpo: Mapping[str, Any] | None = None,
    **contexto: Any,
) -> JSONResponse:
    """Loguea la excepción con su contexto y responde 500 sin exponer su texto.

    Log (`logger.exception`, con traceback): `action=<accion>_error <k>=<v> ... error=<exc> ref=<ref>`,
    contexto en el orden en que se pasa, formateado con `%s`.

    Respuesta: 500 `{**cuerpo, "detail": "Error interno (ref <ref>)"}`; `cuerpo` conserva claves
    extra del endpoint (`"detail"` siempre la pone esta función). `accion` y `exc` son sólo
    posicionales; `cuerpo` es el único nombre reservado para el contexto.

        logger.exception("action=search_camaras_error error=%s", exc)
        raise HTTPException(500, detail=f"Error buscando cámaras: {exc!s}") from exc
        →
        return error_interno("search_camaras", exc)
    """
    ref = nueva_ref()
    _loguear(accion, exc, ref, contexto)
    contenido: dict[str, Any] = dict(cuerpo or {})
    contenido["detail"] = f"Error interno (ref {ref})"
    return JSONResponse(contenido, status_code=500)


async def manejar_error_de_dominio(request: Request, exc: ErrorDeDominio) -> JSONResponse:
    """Handler de `ErrorDeDominio`: `{"detail": mensaje}` con el status de la clase."""
    logger.info(
        "action=error_de_dominio method=%s path=%s status=%s tipo=%s",
        request.method,
        request.url.path,
        exc.status_code,
        type(exc).__name__,
    )
    return JSONResponse({"detail": exc.mensaje}, status_code=exc.status_code)


async def manejar_error_no_controlado(request: Request, exc: Exception) -> Response:
    """Handler de `Exception` (lo ejecuta ServerErrorMiddleware); Starlette re-lanza después igual.

    Fuera de v1 → `error_interno`. En v1 se loguea con ref y se responde idéntico al 500 por defecto
    de Starlette, para no cambiar el contrato de error de la API v1.
    """
    path = request.url.path
    if path.startswith(PREFIJO_API_V1):
        _loguear("unhandled", exc, nueva_ref(), {"method": request.method, "path": path})
        return PlainTextResponse("Internal Server Error", status_code=500)
    return error_interno("unhandled", exc, method=request.method, path=path)
