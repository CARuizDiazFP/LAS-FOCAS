# Nombre de archivo: main.py
# Ubicación de archivo: api/app/main.py
# Descripción: Aplicación FastAPI principal (incluye rutas de health)

from fastapi import FastAPI

from api_app.routes.health import router as health_router
from api_app.routes.reports import router as reports_router
from api_app.routes.ingest import router as ingest_router


def create_app() -> FastAPI:
    app = FastAPI(title="LAS-FOCAS API", version="0.1.0")
    app.include_router(health_router, tags=["health"])
    app.include_router(reports_router)
    app.include_router(ingest_router)
    return app


app = create_app()
