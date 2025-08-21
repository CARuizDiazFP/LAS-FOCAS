# Nombre de archivo: middlewares.py
# Ubicación de archivo: core/middlewares.py
# Descripción: Middlewares compartidos para los servicios FastAPI

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from core.logging import request_id_var


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Genera y propaga un identificador de solicitud."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

