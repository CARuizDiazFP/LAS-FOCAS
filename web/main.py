# Nombre de archivo: main.py
# Ubicación de archivo: web/main.py
# Descripción: Servicio FastAPI básico para el módulo web

"""Módulo principal del servicio web de LAS-FOCAS."""

import base64
import logging
import os
from fastapi import FastAPI, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web")


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Aplica autenticación HTTP básica basada en variables de entorno."""

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)
        self.username = os.getenv("WEB_USERNAME", "")
        self.password = os.getenv("WEB_PASSWORD", "")
        if not self.username or not self.password:
            logger.warning(
                "Variables WEB_USERNAME/WEB_PASSWORD no configuradas; el acceso quedará bloqueado"
            )

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Basic "):
            logger.warning("Solicitud no autorizada sin credenciales")
            return Response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Basic"},
            )

        try:
            decoded = base64.b64decode(auth.split(" ")[1]).decode("utf-8")
            user, pwd = decoded.split(":", 1)
        except Exception:  # noqa: BLE001
            logger.warning("Error al decodificar credenciales básicas")
            return Response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Basic"},
            )

        if user != self.username or pwd != self.password:
            logger.warning("Credenciales inválidas para usuario '%s'", user)
            return Response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Basic"},
            )

        logger.info("Usuario '%s' autorizado", user)
        return await call_next(request)


app = FastAPI(title="Servicio Web LAS-FOCAS")
app.add_middleware(BasicAuthMiddleware)


@app.get("/health")
async def health() -> dict[str, str]:
    """Verifica que el servicio esté disponible."""
    logger.info("Chequeo de salud del servicio web")
    return {"status": "ok"}


@app.get("/")
async def read_root() -> dict[str, str]:
    """Retorna un mensaje inicial."""
    logger.info("Solicitud recibida en la ruta raíz")
    return {"message": "Hola desde el servicio web"}

