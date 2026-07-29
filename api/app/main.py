# Nombre de archivo: main.py
# Ubicación de archivo: api/app/main.py
# Descripción: Aplicación FastAPI principal (incluye rutas de health)

import os
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app.routes.health import router as health_router
from api.app.routes.reports import router as reports_router
from api.app.routes.ingest import router as ingest_router, alias_router as ingest_alias_router
from api.app.routes.infra import router as infra_router
from api.app.routes.servicios import router as servicios_router
from api.app.security import require_api_key


def create_app() -> FastAPI:
    app = FastAPI(title="LAS-FOCAS API", version="0.1.0")

    # CORS: permitir llamadas desde el frontend (8080) y cualquier origen configurado
    default_origins = [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://172.18.208.162:8080",
    ]
    extra_origins = os.getenv("CORS_ORIGINS", "")
    if extra_origins:
        default_origins.extend([o.strip() for o in extra_origins.split(",") if o.strip()])

    app.add_middleware(
        CORSMiddleware,
        allow_origins=default_origins + ["*"] if os.getenv("CORS_ALLOW_ALL") else default_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, tags=["health"])
    protected = [Depends(require_api_key)]
    app.include_router(reports_router, dependencies=protected)
    app.include_router(ingest_router, dependencies=protected)
    app.include_router(ingest_alias_router, dependencies=protected)
    app.include_router(infra_router, dependencies=protected)
    app.include_router(servicios_router, dependencies=protected)
    return app


app = create_app()
