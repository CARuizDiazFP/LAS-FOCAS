# Nombre de archivo: errores.py
# Ubicación de archivo: web/app/errores.py
# Descripción: Errores de dominio tipados y respuesta 500 con referencia (sin exponer el texto interno)

"""Errores de la app web (SPA + FO Monitor).

Contrato de respuesta (formato `{"error": ...}` de la SPA):

- `ErrorDeDominio` y subclases → `{"error": <mensaje>}` con su `status_code`. El mensaje es para el
  usuario: no debe contener texto de excepciones internas.
- Cualquier excepción no controlada → 500 `{"error": "Error interno (ref XXXXXXXX)"}`; el detalle
  (traceback, contexto y la misma ref) va sólo al log.
- Falla de un servicio externo (Cromo, PROV, SMTP) que hoy se informa con un status propio (p. ej.
  502) → `error_servicio_externo(accion, exc, "<mensaje fijo>")`: mismo status, `{"error": "<mensaje
  fijo> (ref XXXXXXXX)"}`, nunca el texto de la excepción (puede traer rutas o cuerpos del proveedor).
  Loguea igual que `error_interno` (ambos usan `_loguear_con_ref`).

`HTTPException` y `RequestValidationError` NO pasan por acá: FastAPI las sigue manejando igual.

Los handlers se registran en `web/app/main.py`. Dentro de un `try/except Exception` de un endpoint,
un `ErrorDeDominio` (o un `HTTPException`) se tragaría: re-lanzarlo antes con
`except (HTTPException, ErrorDeDominio): raise`.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

# Mismo logger "web" que usan los routers (comun.logger) y que configura main.py.
logger = logging.getLogger("web")


class ErrorDeDominio(Exception):
    """Error esperado del dominio; el handler global lo convierte en `{"error": mensaje}`."""

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


def error_interno(
    accion: str,
    exc: BaseException,
    /,
    *,
    cuerpo: Mapping[str, Any] | None = None,
    **contexto: Any,
) -> JSONResponse:
    """Loguea la excepción con su contexto y responde 500 sin exponer su texto.

    Log (vía `logger.exception`, con traceback), mismo texto `action=` que hoy usan los routers más
    la ref al final:

        action=<accion>_error <k1>=<v1> <k2>=<v2> error=<exc> ref=<8 hex>

    Las claves de `contexto` salen en el orden en que se pasan y se formatean con `%s`.

    Respuesta: 500 `{**cuerpo, "error": "Error interno (ref <8 hex>)"}`. `cuerpo` sirve para conservar
    claves extra que el endpoint devuelve hoy, p. ej. `cuerpo={"success": False}`; su orden se
    respeta y `"error"` siempre la pone esta función (si `cuerpo` trae `"error"`, se reemplaza).

    Ejemplo (antes → después):

        logger.exception("action=create_ban_error user=%s error=%s", username, exc)
        return JSONResponse({"success": False, "error": f"Error creando baneo: {exc!s}"}, 500)
        →
        return error_interno("create_ban", exc, cuerpo={"success": False}, user=username)

    `accion` y `exc` son sólo posicionales, así que el contexto puede usar cualquier nombre salvo
    `cuerpo` (reservado).
    """
    ref = _loguear_con_ref(accion, exc, contexto)
    contenido: dict[str, Any] = dict(cuerpo or {})
    contenido["error"] = f"Error interno (ref {ref})"
    return JSONResponse(contenido, status_code=500)


def error_servicio_externo(
    accion: str,
    exc: BaseException,
    mensaje: str,
    /,
    *,
    status_code: int = 502,
    cuerpo: Mapping[str, Any] | None = None,
    **contexto: Any,
) -> JSONResponse:
    """Falla de un servicio externo (Cromo, PROV, SMTP): status propio y mensaje fijo con ref.

    Mismo log que `error_interno` (`logger.exception`, `action=<accion>_error ... error=<exc> ref=`).
    Respuesta: `status_code` (502 por omisión) con `{**cuerpo, "error": "<mensaje> (ref <8 hex>)"}`.

    Ejemplo (antes → después):

        return JSONResponse({"error": f"Cromo no respondió: {exc}"}, status_code=502)
        →
        return error_servicio_externo("camino_normalizar", exc, "Cromo no respondió", user=username)
    """
    ref = _loguear_con_ref(accion, exc, contexto)
    contenido: dict[str, Any] = dict(cuerpo or {})
    contenido["error"] = f"{mensaje} (ref {ref})"
    return JSONResponse(contenido, status_code=status_code)


def _loguear_con_ref(accion: str, exc: BaseException, contexto: Mapping[str, Any]) -> str:
    """`logger.exception("action=<accion>_error <k>=<v>... error=<exc> ref=<ref>")`; devuelve la ref."""
    ref = nueva_ref()
    claves = "".join(f" {clave}=%s" for clave in contexto)
    logger.exception(
        "action=%s_error" + claves + " error=%s ref=%s",
        accion,
        *contexto.values(),
        exc,
        ref,
        exc_info=exc,
    )
    return ref


async def manejar_error_de_dominio(request: Request, exc: ErrorDeDominio) -> JSONResponse:
    """Handler de `ErrorDeDominio`: `{"error": mensaje}` con el status de la clase."""
    logger.info(
        "action=error_de_dominio method=%s path=%s status=%s tipo=%s",
        request.method,
        request.url.path,
        exc.status_code,
        type(exc).__name__,
    )
    return JSONResponse({"error": exc.mensaje}, status_code=exc.status_code)


async def manejar_error_no_controlado(request: Request, exc: Exception) -> JSONResponse:
    """Handler de `Exception` (lo ejecuta ServerErrorMiddleware): 500 con ref vía `error_interno`.

    Starlette re-lanza la excepción después de enviar esta respuesta: uvicorn la sigue logueando y
    `TestClient(raise_server_exceptions=True)` la sigue propagando al test (igual que sin handler).
    """
    return error_interno("unhandled", exc, method=request.method, path=request.url.path)
