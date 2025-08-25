# Nombre de archivo: main.py
# Ubicación de archivo: web/main.py
# Descripción: Servicio FastAPI básico para el módulo web

"""Módulo principal del servicio web de LAS-FOCAS."""

import base64
import logging
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from core import get_secret
from core.logging import configure_logging
from core.middlewares import RequestIDMiddleware
from core.metrics import Metrics

configure_logging("web")
logger = logging.getLogger("web")
metrics = Metrics()


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Aplica autenticación HTTP básica con soporte de roles."""

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)
        self.admin_user = get_secret("WEB_ADMIN_USERNAME") or get_secret("WEB_USERNAME", "")
        self.admin_pass = get_secret("WEB_ADMIN_PASSWORD") or get_secret("WEB_PASSWORD", "")
        self.reader_user = get_secret("WEB_LECTOR_USERNAME", "")
        self.reader_pass = get_secret("WEB_LECTOR_PASSWORD", "")
        if not self.admin_user or not self.admin_pass:
            logger.warning(
                "action=init_basic_auth falta_env=credenciales_admin",
            )

    async def dispatch(self, request: Request, call_next):
        if request.url.path in {"/health", "/login", "/metrics"}:
            return await call_next(request)

        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Basic "):
            logger.warning("action=basic_auth sin_credenciales")
            return RedirectResponse(url="/login")

        try:
            decoded = base64.b64decode(auth.split(" ")[1]).decode("utf-8")
            user, pwd = decoded.split(":", 1)
        except Exception:  # noqa: BLE001
            logger.warning("action=basic_auth error_decodificar")
            return RedirectResponse(url="/login")

        if user == self.admin_user and pwd == self.admin_pass:
            request.state.role = "admin"
        elif self.reader_user and user == self.reader_user and pwd == self.reader_pass:
            request.state.role = "lector"
        else:
            logger.warning("action=basic_auth credenciales_invalidas usuario=%s", user)
            return Response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Basic"},
            )

        logger.info(
            "action=basic_auth usuario_autorizado usuario=%s rol=%s",
            user,
            request.state.role,
        )
        return await call_next(request)


def require_role(expected: str):
    """Genera una dependencia que valida el rol esperado."""

    async def checker(request: Request) -> None:
        if getattr(request.state, "role", None) != expected:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado")

    return checker


app = FastAPI(title="Servicio Web LAS-FOCAS")
app.add_middleware(RequestIDMiddleware)
app.add_middleware(BasicAuthMiddleware)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.middleware("http")
async def collect_metrics(request: Request, call_next):
    inicio = time.perf_counter()
    response = await call_next(request)
    metrics.record(time.perf_counter() - inicio)
    return response


@app.get("/metrics")
async def metrics_endpoint() -> dict[str, float]:
    """Devuelve métricas básicas del servicio web."""
    return metrics.snapshot()



@app.get("/health")
async def health() -> dict[str, str]:
    """Verifica que el servicio esté disponible."""
    logger.info("action=health_check status=ok")
    return {"status": "ok"}


def login_stub(request: Request) -> HTMLResponse:
    """Stub temporal que devuelve una página de login básica."""
    logger.info("action=login_stub")
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request) -> HTMLResponse:
    """Ruta de acceso al formulario de login."""
    return login_stub(request)


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request) -> HTMLResponse:
    """Renderiza la página principal con el rol del usuario."""
    role = getattr(request.state, "role", "desconocido")
    logger.info("action=read_root rol=%s", role)
    return templates.TemplateResponse("index.html", {"request": request, "role": role})


@app.get("/admin", dependencies=[Depends(require_role("admin"))])
async def admin_panel() -> dict[str, str]:
    """Endpoint restringido al rol de administrador."""
    logger.info("action=admin_panel")
    return {"message": "Panel de administración"}
