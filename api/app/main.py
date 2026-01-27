# Nombre de archivo: main.py
# Ubicación de archivo: api/app/main.py
# Descripción: Aplicación FastAPI principal (incluye rutas de health)

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api_app.routes.health import router as health_router
from api_app.routes.reports import router as reports_router
from api_app.routes.ingest import router as ingest_router
from api_app.routes.infra import router as infra_router


def create_app() -> FastAPI:
    app = FastAPI(title="LAS-FOCAS API", version="0.1.0")

    # CORS: permitir llamadas desde el frontend (8080) y cualquier origen configurado
    default_origins = [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://192.168.241.28:8080",
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
    app.include_router(reports_router)
    app.include_router(ingest_router)
    app.include_router(infra_router)
    return app


app = create_app()
