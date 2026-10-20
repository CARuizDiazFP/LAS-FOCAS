# Nombre de archivo: main.py
# Ubicación de archivo: web/app/main.py
# Descripción: Aplicación FastAPI para la UI (página dark, barra y chat REST)

from __future__ import annotations

import asyncio
import io
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import FastAPI, Query, Request, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from core.config import get_secret
from core.logging import setup_logging
from core.utils.tz import TZ_ARG
from web.admin_ws import mount_admin_websocket
from web.fo_monitor_routes import mount_fo_monitor_routes
from web.chat_ws import ChatWebSocketSettings, mount_chat_websocket
import psycopg  # noqa: F401  (los tests parchean web_main.psycopg.connect)
from pathlib import Path

from .routers import admin_datos, chat, servicios, sesion
from .comun import (
    _CROMO_WORKER_RUN_URL,
    BASE_DIR,
    BUILD_VERSION,
    DB_DSN,
    REPORTS_DIR,
    UPLOADS_DIR,
    _encolar_arbitro,
    _env_int,
    _es_destino_slack_valido,
    _marcar_corrida_fallida,
    _require_admin,
    _require_auth,
    _serializar_cromo_corrida,
    _serializar_pelo_semilla,
    _serialize_camara_ingreso,
    _servicio_existe,
    _validar_csrf,
)

# Configuración básica
NLP_INTENT_URL = os.getenv("NLP_INTENT_URL", "http://nlp_intent:8100")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOGS_ROOT = Path(os.getenv("LOGS_DIR", str(Path(__file__).resolve().parents[2] / "Logs")))
logger = setup_logging("web", LOG_LEVEL, enable_file=True, logs_dir=LOGS_ROOT, filename="web.log")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


WEB_SESSION_HTTPS_ONLY = _env_bool("WEB_SESSION_HTTPS_ONLY", False)
WEB_SESSION_MAX_AGE = _env_int("WEB_SESSION_MAX_AGE", 60 * 60 * 8)


def _session_middleware_options() -> dict[str, Any]:
    return {
        "secret_key": get_secret("web_secret_key_v1", "WEB_SECRET_KEY", "cambiar_por_clave_web_segura"),
        "https_only": WEB_SESSION_HTTPS_ONLY,
        "same_site": "lax",
        "max_age": WEB_SESSION_MAX_AGE,
    }

app = FastAPI(title="LAS-FOCAS Web UI", version=BUILD_VERSION)
app.add_middleware(
    SessionMiddleware,
    **_session_middleware_options(),
)

# Middleware de trazabilidad de requests (ayuda a depurar ERR_INVALID_HTTP_RESPONSE en navegador)
@app.middleware("http")
async def log_requests(request, call_next):  # type: ignore
    try:
        logger.debug("action=request_start path=%s client=%s", request.url.path, request.client.host if request.client else "?")
    except Exception:  # noqa: BLE001
        pass
    try:
        response = await call_next(request)
        logger.debug(
            "action=request_end path=%s status=%s len=%s", request.url.path, getattr(response, "status_code", "?"), getattr(response, "body", None) and len(getattr(response, "body"))
        )
        return response
    except Exception as exc:  # noqa: BLE001
        logger.exception("action=request_error path=%s error=%s", getattr(request, 'url', '?'), exc)
        raise

# Rutas absolutas a static/templates basadas en la ubicación de este archivo (web/app/main.py)
DIST_DIR = BASE_DIR / "frontend" / "dist"
SPA_INDEX = DIST_DIR / "index.html"
DEFAULT_TEMPLATES_PATH = Path(__file__).resolve().parents[2] / "Templates"
TEMPLATES_ROOT = os.getenv("TEMPLATES_DIR", str(DEFAULT_TEMPLATES_PATH))
# Variables de entorno para que los módulos de informes respeten rutas
os.environ.setdefault("UPLOADS_DIR", str(UPLOADS_DIR))
os.environ.setdefault("REPORTS_DIR", str(REPORTS_DIR))
os.environ.setdefault("TEMPLATES_DIR", TEMPLATES_ROOT)

# Importar servicio de informes después de setear variables de entorno
from core.services.botella_recompute_queue import (  # noqa: E402
    encolar_recalculo_duplicados_botellas,
    guardar_cache_duplicados,
    leer_cache_duplicados,
)
from .routers import informes  # noqa: E402

# Montar assets del build Vite si existen
_vite_assets = DIST_DIR / "assets"
if _vite_assets.exists():
    app.mount("/assets", StaticFiles(directory=str(_vite_assets)), name="vite-assets")
app.mount("/reports", StaticFiles(directory=str(informes._mount_reports)), name="reports")


def _parse_allowed_origins(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


CHAT_ALLOWED_ORIGINS = _parse_allowed_origins(os.getenv("WEB_CHAT_ALLOWED_ORIGINS"))
if not CHAT_ALLOWED_ORIGINS:
    inferred_origin = os.getenv("WEB_INFERRED_ORIGIN")
    if inferred_origin:
        CHAT_ALLOWED_ORIGINS = [inferred_origin]

mount_chat_websocket(
    app,
    settings=ChatWebSocketSettings(
        dsn=DB_DSN,
        allowed_origins=CHAT_ALLOWED_ORIGINS,
        uploads_dir=str(UPLOADS_DIR),
    ),
    logger=logger,
)
mount_admin_websocket(app, allowed_origins=CHAT_ALLOWED_ORIGINS, logger=logger)
mount_fo_monitor_routes(app)


@dataclass
class IntentResponse:
    intent: str
    confidence: float
    provider: str
    normalized_text: str


async def classify_text(text: str) -> IntentResponse:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{NLP_INTENT_URL}/v1/intent:classify", json={"text": text}
        )
        resp.raise_for_status()
        data = resp.json()
        return IntentResponse(**data)


# =============================================================================
# INFRAESTRUCTURA / CÁMARAS
# =============================================================================

class CamaraResponseModel(BaseModel):
    """Modelo de respuesta para una cámara."""

    id: int
    nombre: str
    fontine_id: Optional[str] = None
    direccion: Optional[str] = None
    estado: str
    origen_datos: str
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    servicios: List[str] = Field(default_factory=list)
    rutas: List[Dict[str, Any]] = Field(default_factory=list)
    tiene_baneo_activo: bool = False
    tiene_ingreso_activo: bool = False
    inconsistente: bool = False
    estado_sugerido: Optional[str] = None
    ticket_baneo: Optional[str] = None
    editable: bool = False
    incidentes_activos: List[Dict[str, Any]] = Field(default_factory=list)


class CamarasListResponseModel(BaseModel):
    """Modelo de respuesta para lista de cámaras."""

    status: str
    total: int
    camaras: List[CamaraResponseModel]


class CamaraEstadoUpdateRequest(BaseModel):
    """Payload para override manual del estado de una cámara."""

    estado: str
    motivo: str = Field(min_length=5, max_length=500)
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


def _serialize_camara_response(
    *,
    camara: Any,
    rutas_info: list[dict[str, Any]],
    servicios_ids: list[str],
    contexto: Any | None,
    editable: bool,
) -> dict[str, Any]:
    ticket_baneo = None
    tiene_baneo_activo = False
    tiene_ingreso_activo = False
    inconsistente = False
    estado_sugerido = None
    incidentes_activos: list[dict[str, Any]] = []

    if contexto is not None:
        ticket_baneo = contexto.ticket_baneo
        tiene_baneo_activo = contexto.tiene_baneo_activo
        tiene_ingreso_activo = contexto.tiene_ingreso_activo
        inconsistente = contexto.inconsistente
        estado_sugerido = contexto.estado_sugerido.value
        incidentes_activos = [incidente.to_dict() for incidente in contexto.incidentes_activos]

    # Navegación cruzada Botella→Cámara padre (2026-08-13): sólo tiene datos si `camara_padre_id`
    # está seteado (es una Botella legado) — el acceso a `.camara_padre` es lazy-load, pero acá
    # nunca dispara N+1 real: los listados batch (smart-search/search) sólo traen cámaras raíz
    # (`camara_padre_id IS NULL`), así que este branch sólo se ejecuta en fetches de una Botella
    # puntual (GET /api/infra/camaras/{id} con un id de Botella).
    camara_padre_id = getattr(camara, "camara_padre_id", None)
    camara_padre_nombre = None
    if camara_padre_id:
        camara_padre = getattr(camara, "camara_padre", None)
        camara_padre_nombre = camara_padre.nombre if camara_padre is not None else None

    return {
        "id": camara.id,
        "nombre": camara.nombre or "",
        "fontine_id": camara.fontine_id,
        "direccion": camara.direccion,
        "estado": camara.estado.value if camara.estado else "LIBRE",
        "origen_datos": camara.origen_datos.value if camara.origen_datos else "MANUAL",
        "latitud": camara.latitud,
        "longitud": camara.longitud,
        "servicios": servicios_ids,
        "rutas": rutas_info,
        "tiene_baneo_activo": tiene_baneo_activo,
        "tiene_ingreso_activo": tiene_ingreso_activo,
        "inconsistente": inconsistente,
        "estado_sugerido": estado_sugerido,
        "ticket_baneo": ticket_baneo,
        "editable": editable,
        "incidentes_activos": incidentes_activos,
        # Etapa Cámara/Botella: `es_botella`/`botellas_count` sólo tienen sentido si `camara` trae
        # cargada la columna/relación nueva — con getattr por si algún caller viejo pasa un objeto
        # sin esos atributos (tests con SimpleNamespace, por ejemplo).
        "es_botella": bool(camara_padre_id),
        "camara_padre_id": camara_padre_id,
        "camara_padre_nombre": camara_padre_nombre,
        "botellas_count": len(getattr(camara, "botellas", None) or []),
    }


def _serialize_cromo_botella_hija(cromo_botella: Any) -> dict[str, Any]:
    """Serializa una `CromoBotella` como hija de grupo para `get_camara_botellas_web`. Shape
    reducido a lo que el único consumidor confirmado (`ModalBotellas.vue`) necesita — Cromo no
    asocia botellas a rutas/empalmes/incidentes (conceptos del módulo Infra/Baneos, ya cubiertos
    por `_serialize_camara_response` para el origen "legado")."""
    return {
        "origen": "cromo",
        "id": cromo_botella.n_id,
        "nombre": cromo_botella.nombre,
        "estado": cromo_botella.estado.value if cromo_botella.estado else None,
        "servicios": [],
    }


def _collect_camara_rutas_info(camara: Any, *, incluir_botellas: bool = False) -> list[dict[str, Any]]:
    """Obtiene las rutas asociadas a una cámara a través de sus empalmes.

    `incluir_botellas=True` (Etapa Cámara/Botella) también recorre los empalmes de todas las Botellas
    de `camara` — para que una cámara-raíz muestre los servicios de todo su grupo físico, no sólo los
    que pasan por su propia fila (los empalmes reales de un grupo suelen vivir en las botellas, no en
    la cámara padre sintetizada por el backfill)."""

    camaras_a_recorrer = [camara]
    if incluir_botellas:
        camaras_a_recorrer.extend(getattr(camara, "botellas", None) or [])

    rutas_info: list[dict[str, Any]] = []
    seen_rutas: set[int] = set()
    for cam in camaras_a_recorrer:
        for empalme in cam.empalmes:
            for ruta in empalme.rutas:
                if ruta.id in seen_rutas:
                    continue
                seen_rutas.add(ruta.id)
                alias_ids = ruta.servicio.alias_ids or []
                transitos_count = sum(1 for item in ruta.empalmes if item.es_transito)
                punta_a_sitio = ruta.punta_a.sitio if ruta.punta_a else None
                punta_b_sitio = ruta.punta_b.sitio if ruta.punta_b else None
                rutas_info.append(
                    {
                        "ruta_id": ruta.id,
                        "servicio_id": ruta.servicio.servicio_id,
                        "ruta_nombre": ruta.nombre,
                        "ruta_tipo": ruta.tipo.value,
                        "alias_ids": alias_ids,
                        "transitos_count": transitos_count,
                        "punta_a_sitio": punta_a_sitio,
                        "punta_b_sitio": punta_b_sitio,
                    }
                )
    return rutas_info


def _collect_camara_servicios_ids(camara: Any, rutas_info: list[dict[str, Any]] | None = None) -> list[str]:
    """Obtiene servicios asociados a una cámara desde rutas o relación legacy."""

    if rutas_info:
        return sorted({str(ruta["servicio_id"]) for ruta in rutas_info if ruta.get("servicio_id")})

    servicios_ids: list[str] = []
    for empalme in camara.empalmes:
        for servicio in empalme.servicios:
            if servicio.servicio_id and servicio.servicio_id not in servicios_ids:
                servicios_ids.append(servicio.servicio_id)
    return servicios_ids


def _serialize_camara_alias(alias: Any) -> dict[str, Any]:
    return {
        "id": alias.id,
        "nombre": alias.alias_nombre,
        "created_at": alias.created_at.isoformat() if alias.created_at else None,
    }


def _serialize_camara_auditoria(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "usuario": item.usuario,
        "motivo": item.motivo,
        "estado_anterior": item.estado_anterior.value if item.estado_anterior else None,
        "estado_nuevo": item.estado_nuevo.value if item.estado_nuevo else None,
        "estado_sugerido": item.estado_sugerido.value if item.estado_sugerido else None,
        "incidentes_activos": item.incidentes_activos or [],
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _serialize_camara_baneo(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "ticket_asociado": item.ticket_asociado,
        "servicio_afectado_id": item.servicio_afectado_id,
        "servicio_protegido_id": item.servicio_protegido_id,
        "ruta_protegida_id": item.ruta_protegida_id,
        "motivo": item.motivo,
        "activo": bool(item.activo),
        "fecha_inicio": item.fecha_inicio.isoformat() if item.fecha_inicio else None,
        "fecha_fin": item.fecha_fin.isoformat() if item.fecha_fin else None,
    }


@app.get("/api/infra/camaras")
async def search_camaras_web(
    request: Request,
    q: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = 100,
) -> JSONResponse:
    """Busca cámaras por query y/o estado (proxy al API interno)."""

    username, role = _require_auth(request)
    limit = min(limit, 500)

    try:
        from core.services.camara_estado_service import get_camara_estado_contexto
        from db.models.infra import Camara, CamaraEstado, Servicio
        from db.session import SessionLocal

        with SessionLocal() as session:
            query = session.query(Camara)

            # Filtro por estado
            if estado:
                estado_upper = estado.upper()
                if estado_upper in [e.value for e in CamaraEstado]:
                    query = query.filter(Camara.estado == CamaraEstado(estado_upper))

            # Filtro por texto
            if q and q.strip():
                search_term = f"%{q.strip()}%"
                query = query.filter(
                    (Camara.nombre.ilike(search_term)) |
                    (Camara.direccion.ilike(search_term)) |
                    (Camara.fontine_id.ilike(search_term))
                )

            camaras_db = query.order_by(Camara.nombre).limit(limit).all()

            # Construir respuesta con servicios y rutas
            camaras_response = []
            for cam in camaras_db:
                # Obtener rutas asociadas a esta cámara a través de empalmes
                rutas_info = []
                seen_rutas = set()
                
                for empalme in cam.empalmes:
                    for ruta in empalme.rutas:
                        if ruta.id not in seen_rutas:
                            seen_rutas.add(ruta.id)
                            rutas_info.append({
                                "ruta_id": ruta.id,
                                "servicio_id": ruta.servicio.servicio_id,
                                "ruta_nombre": ruta.nombre,
                                "ruta_tipo": ruta.tipo.value,
                            })

                # Para retrocompatibilidad, mantener lista simple de servicios
                servicios_ids = list(set(r["servicio_id"] for r in rutas_info))

                camaras_response.append(
                    _serialize_camara_response(
                        camara=cam,
                        rutas_info=rutas_info,
                        servicios_ids=servicios_ids,
                        contexto=get_camara_estado_contexto(session, cam.id),
                        editable=role == "admin",
                    )
                )

            # Buscar por servicio_id si no se encontraron cámaras
            if q and q.strip() and not camaras_response:
                servicio = session.query(Servicio).filter(
                    Servicio.servicio_id.ilike(f"%{q.strip()}%")
                ).first()

                if servicio:
                    # Obtener cámaras a través de las rutas del servicio
                    seen_cam_ids = set()
                    for ruta in servicio.rutas:
                        for empalme in ruta.empalmes:
                            if empalme.camara and empalme.camara.id not in seen_cam_ids:
                                seen_cam_ids.add(empalme.camara.id)
                                cam = empalme.camara
                                
                                # Obtener todas las rutas de esta cámara
                                rutas_info = []
                                seen_rutas = set()
                                for emp in cam.empalmes:
                                    for r in emp.rutas:
                                        if r.id not in seen_rutas:
                                            seen_rutas.add(r.id)
                                            rutas_info.append({
                                                "ruta_id": r.id,
                                                "servicio_id": r.servicio.servicio_id,
                                                "ruta_nombre": r.nombre,
                                                "ruta_tipo": r.tipo.value,
                                            })
                                
                                servicios_ids = list(set(r["servicio_id"] for r in rutas_info))

                                camaras_response.append(
                                    _serialize_camara_response(
                                        camara=cam,
                                        rutas_info=rutas_info,
                                        servicios_ids=servicios_ids,
                                        contexto=get_camara_estado_contexto(session, cam.id),
                                        editable=role == "admin",
                                    )
                                )

            logger.info(
                "action=search_camaras user=%s query=%s estado=%s results=%d",
                username,
                q,
                estado,
                len(camaras_response),
            )

            return JSONResponse({
                "status": "ok",
                "total": len(camaras_response),
                "camaras": camaras_response,
            })

    except Exception as exc:
        logger.exception("action=search_camaras_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"error": f"Error buscando cámaras: {exc!s}"},
            status_code=500
        )


@app.get("/api/infra/camaras/buscar")
async def camaras_buscar_ligero_web(
    request: Request,
    q: Optional[str] = None,
    limit: int = 10,
    excluir_id: Optional[int] = None,
    solo_raiz: bool = True,
) -> JSONResponse:
    """Búsqueda liviana de Cámaras raíz por nombre — para selectores/autocomplete (picker de
    "Unificar Cámara", picker de "Asociar a Cámara existente" de Botellas huérfanas). Deliberadamente
    no reusa `smart-search` (N+1 de rutas/servicios/cables por cámara, pensado para el dashboard, no
    para un selector liviano). Sólo lectura, cualquier usuario autenticado.

    `solo_raiz=False` (picker de asociación manual de la ingesta de Excel, Tarea 5) incluye también
    Botellas legado en los resultados, con `es_botella`/`camara_padre_id`/`camara_padre_nombre`
    poblados — así el admin ve a qué grupo (padre + hermanas) se va a aplicar el baneo antes de
    confirmar. Default `True` preserva el comportamiento histórico (sólo Cámaras raíz).

    Registrada ANTES de `GET /api/infra/camaras/{camara_id}` a propósito (hallazgo real durante la
    verificación): FastAPI/Starlette matchea rutas en orden de registro, y `/camaras/buscar` tiene la
    misma forma de un segmento que `/camaras/{camara_id}` — si esta ruta se registrara después, esa
    otra la interceptaría primero e intentaría parsear "buscar" como `camara_id: int`, devolviendo
    422 en vez de ejecutar esta búsqueda."""
    from core.services.camara_busqueda_service import buscar_camaras_ligero
    from db.session import SessionLocal

    _require_auth(request)
    try:
        with SessionLocal() as session:
            candidatas = buscar_camaras_ligero(
                session, q, limit=limit, excluir_id=excluir_id, solo_raiz=solo_raiz
            )
            return JSONResponse({
                "camaras": [
                    {
                        "id": c.id,
                        "nombre": c.nombre,
                        "direccion": c.direccion,
                        "estado": c.estado,
                        "botellas_count": c.botellas_count,
                        "cables_count": c.cables_count,
                        "es_botella": c.es_botella,
                        "camara_padre_id": c.camara_padre_id,
                        "camara_padre_nombre": c.camara_padre_nombre,
                    }
                    for c in candidatas
                ]
            })
    except Exception as exc:
        logger.exception("action=camaras_buscar_ligero_error error=%s", exc)
        return JSONResponse({"error": "No se pudo buscar cámaras"}, status_code=500)


@app.get("/api/infra/camaras/{camara_id}")
async def get_camara_detail_web(request: Request, camara_id: int) -> JSONResponse:
    """Obtiene el resumen operativo base de una cámara para la vista de detalle."""

    _, role = _require_auth(request)

    try:
        from core.services.camara_estado_service import get_camara_estado_contexto
        from db.models.infra import Camara
        from db.session import SessionLocal

        with SessionLocal() as session:
            camara = session.query(Camara).filter(Camara.id == camara_id).first()
            if not camara:
                return JSONResponse({"error": "Cámara no encontrada"}, status_code=404)

            rutas_info = _collect_camara_rutas_info(camara, incluir_botellas=True)
            servicios_ids = _collect_camara_servicios_ids(camara, rutas_info)
            payload = _serialize_camara_response(
                camara=camara,
                rutas_info=rutas_info,
                servicios_ids=servicios_ids,
                contexto=get_camara_estado_contexto(session, camara.id),
                editable=role == "admin",
            )
            return JSONResponse({"status": "ok", "camara": payload})
    except Exception as exc:
        logger.exception("action=get_camara_detail_error camara_id=%s error=%s", camara_id, exc)
        return JSONResponse({"error": "No se pudo obtener el detalle de la cámara"}, status_code=500)


@app.get("/api/infra/camaras/{camara_id}/aliases")
async def get_camara_aliases_web(request: Request, camara_id: int) -> JSONResponse:
    """Obtiene los alias conocidos de una cámara."""

    _require_auth(request)

    try:
        from db.models.infra import Camara, CamaraAlias
        from db.session import SessionLocal

        with SessionLocal() as session:
            camara = session.query(Camara.id, Camara.nombre).filter(Camara.id == camara_id).first()
            if not camara:
                return JSONResponse({"error": "Cámara no encontrada"}, status_code=404)

            aliases = (
                session.query(CamaraAlias)
                .filter(CamaraAlias.camara_id == camara_id)
                .order_by(CamaraAlias.alias_nombre.asc())
                .all()
            )
            return JSONResponse(
                {
                    "status": "ok",
                    "camara_id": camara_id,
                    "camara_nombre": camara.nombre,
                    "total": len(aliases),
                    "aliases": [_serialize_camara_alias(alias) for alias in aliases],
                }
            )
    except Exception as exc:
        logger.exception("action=get_camara_aliases_error camara_id=%s error=%s", camara_id, exc)
        return JSONResponse({"error": "No se pudieron obtener los alias de la cámara"}, status_code=500)


@app.get("/api/infra/camaras/{camara_id}/botellas")
async def get_camara_botellas_web(request: Request, camara_id: int) -> JSONResponse:
    """Obtiene las Botellas (jerarquía Cámara/Botella) de una cámara — sólo lectura. Une las dos
    fuentes que pueden colgar de una Cámara padre: Botellas legado (`camara.botellas`, self-FK) y
    Botellas Cromo (`CromoBotella.camara_id`, vigentes, backfilleadas por
    `scripts/cromo_backfill_camara_padre.py`) — cada una etiquetada con su `origen`.

    Nunca aplica un filtro de "no operativa": es un drill-down sobre un grupo ya identificado por
    ID (el usuario ya abrió el detalle de esta Cámara puntual) — ocultar una hija NO_OPERATIVA en
    el detalle de su propio padre haría creer que el grupo físico tiene menos botellas de las que
    tiene realmente.

    Si `camara_id` es en sí una Botella legado (`camara_padre_id` seteado), devuelve una lista
    vacía para ese origen — el modelo self-FK es de exactamente 2 niveles, una Botella no tiene sus
    propias botellas."""

    _, role = _require_auth(request)

    try:
        from core.services.camara_estado_service import get_camara_estado_contexto
        from db.models.cromo import CromoBotella
        from db.models.infra import Camara
        from db.session import SessionLocal

        with SessionLocal() as session:
            camara = session.query(Camara).filter(Camara.id == camara_id).first()
            if not camara:
                return JSONResponse({"error": "Cámara no encontrada"}, status_code=404)

            botellas_legado = [
                {
                    **_serialize_camara_response(
                        camara=botella,
                        rutas_info=_collect_camara_rutas_info(botella),
                        servicios_ids=_collect_camara_servicios_ids(botella),
                        contexto=get_camara_estado_contexto(session, botella.id),
                        editable=role == "admin",
                    ),
                    "origen": "legado",
                }
                for botella in camara.botellas
            ]

            cromo_hijas = (
                session.query(CromoBotella)
                .filter(CromoBotella.camara_id == camara_id, CromoBotella.vigente.is_(True))
                .order_by(CromoBotella.nombre)
                .all()
            )
            botellas_cromo = [_serialize_cromo_botella_hija(cb) for cb in cromo_hijas]

            botellas = botellas_legado + botellas_cromo
            return JSONResponse(
                {
                    "status": "ok",
                    "camara_id": camara_id,
                    "camara_nombre": camara.nombre,
                    "total": len(botellas),
                    "botellas": botellas,
                }
            )
    except Exception as exc:
        logger.exception("action=get_camara_botellas_error camara_id=%s error=%s", camara_id, exc)
        return JSONResponse({"error": "No se pudieron obtener las botellas de la cámara"}, status_code=500)


@app.get("/api/infra/camaras/{camara_id}/registros")
async def get_camara_registros_web(request: Request, camara_id: int) -> JSONResponse:
    """Obtiene registros operativos parciales de una cámara para la vista dedicada."""

    _require_auth(request)

    try:
        from core.services.camara_estado_service import get_camara_estado_contexto, miembros_del_grupo
        from db.models.infra import Camara, CamaraEstadoAuditoria, IncidenteBaneo, Ingreso
        from db.session import SessionLocal
        from sqlalchemy import nullslast

        with SessionLocal() as session:
            camara = session.query(Camara).filter(Camara.id == camara_id).first()
            if not camara:
                return JSONResponse({"error": "Cámara no encontrada"}, status_code=404)

            rutas_info = _collect_camara_rutas_info(camara, incluir_botellas=True)
            rutas_ids = {int(ruta["ruta_id"]) for ruta in rutas_info if ruta.get("ruta_id") is not None}
            servicios_ids = _collect_camara_servicios_ids(camara, rutas_info)

            auditoria = (
                session.query(CamaraEstadoAuditoria)
                .filter(CamaraEstadoAuditoria.camara_id == camara_id)
                .order_by(CamaraEstadoAuditoria.created_at.desc())
                .limit(20)
                .all()
            )

            baneos: list[Any] = []
            if servicios_ids:
                candidatos = (
                    session.query(IncidenteBaneo)
                    .filter(IncidenteBaneo.servicio_protegido_id.in_(servicios_ids))
                    .order_by(IncidenteBaneo.fecha_inicio.desc())
                    .limit(50)
                    .all()
                )
                baneos = [
                    incidente
                    for incidente in candidatos
                    if incidente.ruta_protegida_id is None or incidente.ruta_protegida_id in rutas_ids
                ][:20]

            # Mismo grupo (cámara + botellas hermanas) que usa `tiene_ingreso_activo` en
            # `camara_estado_service`, para que los ingresos mostrados acá sean consistentes con
            # el estado sugerido de la cámara.
            ids_grupo = [miembro.id for miembro in miembros_del_grupo(camara)]
            ingresos_db = (
                session.query(Ingreso)
                .filter(Ingreso.camara_id.in_(ids_grupo))
                .order_by(nullslast(Ingreso.fecha_inicio.desc()))
                .limit(50)
                .all()
            )

            contexto = get_camara_estado_contexto(session, camara_id)
            return JSONResponse(
                {
                    "status": "ok",
                    "camara_id": camara_id,
                    "contexto": contexto.to_dict() if contexto else None,
                    "auditoria": [_serialize_camara_auditoria(item) for item in auditoria],
                    "baneos": [_serialize_camara_baneo(item) for item in baneos],
                    "ingresos": [_serialize_camara_ingreso(item) for item in ingresos_db],
                }
            )
    except Exception as exc:
        logger.exception("action=get_camara_registros_error camara_id=%s error=%s", camara_id, exc)
        return JSONResponse({"error": "No se pudieron obtener los registros de la cámara"}, status_code=500)


# -----------------------------------------------------------------------------
# ALIAS: TRACKING DOWNLOAD (para compatibilidad con panel.js)
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# ENDPOINTS DE BANEO (Protocolo de Protección)
# -----------------------------------------------------------------------------

class BanCreateRequestModel(BaseModel):
    """Request para crear un baneo."""
    ticket_asociado: Optional[str] = None
    servicio_afectado_id: str
    servicio_protegido_id: str
    ruta_protegida_id: Optional[int] = None
    motivo: Optional[str] = None


@app.post("/api/infra/ban/create")
async def create_ban_web(
    request: Request,
    ban_request: BanCreateRequestModel,
) -> JSONResponse:
    """Crea un incidente de baneo y marca las cámaras como BANEADAS."""
    
    username, _ = _require_auth(request)
    
    try:
        from core.services.protection_service import create_ban as do_create_ban
        from db.session import SessionLocal
        
        with SessionLocal() as session:
            result = do_create_ban(
                session,
                ticket_asociado=ban_request.ticket_asociado,
                servicio_afectado_id=ban_request.servicio_afectado_id,
                servicio_protegido_id=ban_request.servicio_protegido_id,
                ruta_protegida_id=ban_request.ruta_protegida_id,
                usuario_ejecutor=username,
                motivo=ban_request.motivo,
            )
            
            if result.success:
                session.commit()
                try:
                    from core.config import get_settings
                    from modules.slack_baneo_notifier.eventos import notificar_evento_baneo

                    datos_evento = result.to_dict()
                    datos_evento["servicio_afectado_id"] = ban_request.servicio_afectado_id
                    datos_evento["servicio_protegido_id"] = ban_request.servicio_protegido_id
                    datos_evento["ticket_asociado"] = ban_request.ticket_asociado
                    datos_evento["usuario_ejecutor"] = username
                    datos_evento["motivo"] = ban_request.motivo
                    notificar_evento_baneo(session, "create", datos_evento, get_settings().slack.bot_token)
                except Exception as slack_exc:
                    logger.warning("Error enviando aviso Slack de baneo creado desde web: %s", slack_exc)
                logger.info(
                    "action=create_ban user=%s ticket=%s servicio_afectado=%s servicio_protegido=%s camaras=%d",
                    username,
                    ban_request.ticket_asociado,
                    ban_request.servicio_afectado_id,
                    ban_request.servicio_protegido_id,
                    result.camaras_baneadas,
                )
            else:
                session.rollback()
                logger.warning(
                    "action=create_ban_failed user=%s error=%s",
                    username,
                    result.message,
                )
            
            return JSONResponse(result.to_dict())
            
    except Exception as exc:
        logger.exception("action=create_ban_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"success": False, "error": f"Error creando baneo: {exc!s}"},
            status_code=500
        )


@app.get("/api/infra/ban/active")
async def get_active_bans_web(request: Request) -> JSONResponse:
    """Obtiene todos los incidentes de baneo activos con conteo de cámaras."""
    
    username, _ = _require_auth(request)
    
    try:
        from core.services.protection_service import get_incidentes_activos, ProtectionService
        from db.models.infra import Camara, CamaraEstado
        from db.session import SessionLocal
        
        with SessionLocal() as session:
            incidentes = get_incidentes_activos(session)
            protection_svc = ProtectionService(session)
            total_camaras_baneadas = session.query(Camara.id).filter(Camara.estado == CamaraEstado.BANEADA).count()
            
            incidentes_data = []
            for inc in incidentes:
                duracion = None
                if inc.fecha_inicio:
                    from datetime import datetime, timezone
                    ahora = datetime.now(timezone.utc)
                    duracion = (ahora - inc.fecha_inicio).total_seconds() / 3600
                
                # Contar cámaras afectadas para cada incidente
                camaras = protection_svc.get_camaras_for_servicio(
                    inc.servicio_protegido_id,
                    inc.ruta_protegida_id
                )
                camaras_count = len(camaras)
                camaras_baneadas_count = sum(1 for camara in camaras if camara.estado == CamaraEstado.BANEADA)
                
                incidentes_data.append({
                    "id": inc.id,
                    "ticket_asociado": inc.ticket_asociado,
                    "servicio_afectado_id": inc.servicio_afectado_id,
                    "servicio_protegido_id": inc.servicio_protegido_id,
                    "ruta_protegida_id": inc.ruta_protegida_id,
                    "usuario_ejecutor": inc.usuario_ejecutor,
                    "motivo": inc.motivo,
                    "fecha_inicio": inc.fecha_inicio.isoformat() if inc.fecha_inicio else None,
                    "activo": inc.activo,
                    "duracion_horas": round(duracion, 1) if duracion else None,
                    "camaras_count": camaras_count,
                    "camaras_baneadas_count": camaras_baneadas_count,
                })
            
            logger.info("action=get_active_bans user=%s count=%d", username, len(incidentes_data))
            
            return JSONResponse({
                "status": "ok",
                "incidentes": incidentes_data,
                "total": len(incidentes_data),
                "total_camaras_baneadas": total_camaras_baneadas,
            })
            
    except Exception as exc:
        logger.exception("action=get_active_bans_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"error": f"Error obteniendo baneos activos: {exc!s}"},
            status_code=500
        )


class BanLiftRequestModel(BaseModel):
    """Request para levantar un baneo."""
    incidente_id: int
    motivo_cierre: Optional[str] = None


@app.post("/api/infra/ban/lift")
async def lift_ban_web(
    request: Request,
    lift_request: BanLiftRequestModel,
) -> JSONResponse:
    """Levanta un baneo y restaura el estado de las cámaras."""
    
    username, _ = _require_auth(request)
    
    try:
        from core.services.protection_service import lift_ban as do_lift_ban
        from db.session import SessionLocal
        
        with SessionLocal() as session:
            result = do_lift_ban(
                session,
                lift_request.incidente_id,
                usuario_ejecutor=username,
                motivo_cierre=lift_request.motivo_cierre,
            )
            
            if result.success:
                session.commit()
                try:
                    from core.config import get_settings
                    from modules.slack_baneo_notifier.eventos import notificar_evento_baneo

                    datos_evento = result.to_dict()
                    datos_evento["usuario_ejecutor"] = username
                    datos_evento["motivo_cierre"] = lift_request.motivo_cierre
                    notificar_evento_baneo(session, "lift", datos_evento, get_settings().slack.bot_token)
                except Exception as slack_exc:
                    logger.warning("Error enviando aviso Slack de baneo levantado desde web: %s", slack_exc)
                logger.info(
                    "action=lift_ban user=%s incidente_id=%d camaras_restauradas=%d",
                    username,
                    lift_request.incidente_id,
                    result.camaras_restauradas,
                )
            else:
                session.rollback()
                logger.warning(
                    "action=lift_ban_failed user=%s incidente_id=%d error=%s",
                    username,
                    lift_request.incidente_id,
                    result.message,
                )
            
            return JSONResponse(result.to_dict())
            
    except Exception as exc:
        logger.exception("action=lift_ban_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"success": False, "error": f"Error levantando baneo: {exc!s}"},
            status_code=500
        )


# -----------------------------------------------------------------------------
# ENDPOINTS DE GRUPOS BANEADOS (Cámara padre + Botellas) — listado admin y liberación masiva.
# Distinto del Protocolo de Protección arriba (`/api/infra/ban/*`, `IncidenteBaneo`): este listado
# agrupa por Cámara padre TODO baneo activo (incidente o no — override manual/import Excel también
# entran) y su única acción es "liberar" (= cambiar estado a LIBRE/estado_sugerido), nunca borrar
# filas — ver `core/services/baneos_grupos_service.py`.
# -----------------------------------------------------------------------------


@app.get("/api/admin/baneos/grupos")
async def baneos_grupos_listar_web(
    request: Request,
    q: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> JSONResponse:
    """Lista grupos baneados (Cámara padre raíz + sus Botellas legado/Cromo), paginado. `limit`
    siempre viene de query param acá (int) — el `limit=None` sin paginar de
    `listar_grupos_baneados` sólo lo usa internamente el reporte Excel de la Tarea 8, nunca este
    endpoint web."""
    _require_admin(request)

    try:
        from core.services.baneos_grupos_service import listar_grupos_baneados
        from db.session import SessionLocal

        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        with SessionLocal() as session:
            resultado = listar_grupos_baneados(session, q=q, limit=limit, offset=offset)
            return JSONResponse({"status": "ok", "limit": limit, "offset": offset, **resultado.to_dict()})
    except Exception as exc:
        logger.exception("action=baneos_grupos_listar_error error=%s", exc)
        return JSONResponse({"error": "No se pudo obtener el listado de grupos baneados"}, status_code=500)


class BaneosLiberarMasivoRequestModel(BaseModel):
    """Payload para liberar (desbanear) varios grupos de una — NO es un borrado físico."""

    camara_ids: list[int]
    motivo: str
    forzar: bool = False
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.post("/api/admin/baneos/grupos/liberar")
async def baneos_grupos_liberar_web(request: Request, body: BaneosLiberarMasivoRequestModel) -> JSONResponse:
    """Libera (desbanea) varios grupos de una — la única acción masiva nueva de este dominio.
    Guard de incidente activo por grupo (`core.services.baneos_grupos_service.liberar_grupos_masivo`):
    sin `forzar`, un grupo con un `IncidenteBaneo` activo detrás se omite en vez de desbanearse."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=baneos_grupos_liberar result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    if not body.camara_ids:
        return JSONResponse({"error": "No se especificaron grupos a liberar"}, status_code=400)
    motivo = body.motivo.strip()
    if not motivo:
        return JSONResponse({"error": "El motivo es obligatorio"}, status_code=400)

    try:
        from core.services.baneos_grupos_service import liberar_grupos_masivo
        from db.session import SessionLocal

        with SessionLocal() as session:
            resultado = liberar_grupos_masivo(
                session,
                body.camara_ids,
                usuario=username,
                motivo=motivo,
                forzar=body.forzar,
            )
            session.commit()
            logger.info(
                "action=baneos_grupos_liberar user=%s solicitados=%d liberados=%d omitidos=%d forzar=%s",
                username,
                resultado.total_solicitados,
                resultado.liberados,
                resultado.omitidos,
                body.forzar,
            )
            return JSONResponse({"ok": True, **resultado.to_dict()})
    except Exception as exc:
        logger.exception("action=baneos_grupos_liberar_error user=%s error=%s", username, exc)
        return JSONResponse({"error": "No se pudieron liberar los grupos"}, status_code=500)


# -----------------------------------------------------------------------------
# ENDPOINTS DE NOTIFICACIÓN POR EMAIL
# -----------------------------------------------------------------------------

class EmailNotifyRequestModel(BaseModel):
    """Request para enviar notificación por email."""
    to: list[str]
    cc: Optional[list[str]] = None
    subject: str
    body: str
    incidente_ids: list[int] = []
    include_xls: bool = False
    include_txt: bool = False


@app.post("/api/infra/notify/email")
async def send_email_notification_web(
    request: Request,
    email_request: EmailNotifyRequestModel,
) -> JSONResponse:
    """Envía un correo electrónico con información de baneos."""
    
    username, _ = _require_auth(request)
    
    try:
        from core.services.email_service import EmailAttachment, get_email_service
        from db.models.infra import IncidenteBaneo
        from db.session import SessionLocal
        from core.services.protection_service import ProtectionService
        import io
        
        email_service = get_email_service()
        
        if not email_service.is_configured():
            return JSONResponse({
                "success": False,
                "message": "Servicio de email no configurado",
                "error": "SMTP no está configurado en el servidor",
            }, status_code=500)
        
        attachments: list = []
        
        with SessionLocal() as session:
            protection_svc = ProtectionService(session)
            # Obtener incidentes
            incidentes = []
            if email_request.incidente_ids:
                incidentes = (
                    session.query(IncidenteBaneo)
                    .filter(IncidenteBaneo.id.in_(email_request.incidente_ids))
                    .all()
                )
            
            # Generar XLS si se solicita
            if email_request.include_xls and incidentes:
                try:
                    import pandas as pd
                    
                    rows = []
                    for incidente in incidentes:
                        # Se corrige el acceso a camaras_afectadas usando ProtectionService
                        camaras = protection_svc.get_camaras_for_servicio(incidente.servicio_protegido_id, incidente.ruta_protegida_id)
                        for camara in camaras:
                            rows.append({
                                "Incidente ID": incidente.id,
                                "Ticket": incidente.ticket_asociado or "-",
                                "Servicio Afectado": incidente.servicio_afectado_id,
                                "Servicio Protegido": incidente.servicio_protegido_id,
                                "Cámara ID": camara.id,
                                "Cámara Nombre": camara.nombre,
                                "Estado": camara.estado.value if camara.estado else "-",
                                "Fecha Inicio": (
                                    incidente.fecha_inicio.astimezone(TZ_ARG).strftime("%d/%m/%Y %H:%M")
                                    if incidente.fecha_inicio else "-"
                                ),
                                "Motivo": incidente.motivo or "-",
                            })
                    
                    if rows:
                        df = pd.DataFrame(rows)
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine="openpyxl") as writer:
                            df.to_excel(writer, sheet_name="Baneos_Activos", index=False)
                        output.seek(0)
                        
                        attachments.append(
                            EmailAttachment(
                                filename="baneos_activos.xlsx",
                                content=output.getvalue(),
                                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )
                        )
                
                except ImportError:
                    logger.warning("action=notify_email warning=pandas_not_available skipping_xls=true")
            
            # Obtener TXT original si se solicita
            if email_request.include_txt and incidentes:
                from db.models.infra import Servicio
                
                for incidente in incidentes:
                    servicio = (
                        session.query(Servicio)
                        .filter(Servicio.servicio_id == incidente.servicio_protegido_id)
                        .first()
                    )
                    if servicio and servicio.rutas:
                        for ruta in servicio.rutas:
                            if ruta.raw_file_content:
                                filename = (
                                    ruta.nombre_archivo_origen
                                    or f"tracking_{servicio.servicio_id}.txt"
                                )
                                attachments.append(
                                    EmailAttachment(
                                        filename=filename,
                                        content=ruta.raw_file_content.encode("utf-8"),
                                        mime_type="text/plain; charset=utf-8",
                                    )
                                )
                                break
                        break
        
        # Enviar correo
        result = email_service.send_email(
            to=email_request.to,
            cc=email_request.cc,
            subject=email_request.subject,
            body=email_request.body,
            attachments=attachments if attachments else None,
        )
        
        logger.info(
            "action=send_email user=%s to=%s success=%s attachments=%d",
            username,
            email_request.to,
            result.success,
            len(attachments),
        )
        
        return JSONResponse({
            "success": result.success,
            "message": result.message,
            "error": result.error,
            "recipients_count": len(email_request.to) + len(email_request.cc or []),
        })
        
    except Exception as exc:
        logger.exception("action=send_email_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"success": False, "message": "Error enviando email", "error": str(exc)},
            status_code=500
        )


@app.get("/api/infra/notify/email/config")
async def get_email_config_web(request: Request) -> JSONResponse:
    """Obtiene el estado de configuración del email."""
    
    _require_auth(request)
    
    try:
        from core.services.email_service import get_email_service
        
        email_service = get_email_service()
        settings = email_service.settings
        
        return JSONResponse({
            "configured": email_service.is_configured(),
            "from_email": settings.from_email if email_service.is_configured() else None,
            "from_name": settings.from_name if email_service.is_configured() else None,
        })
        
    except Exception as exc:
        logger.exception("action=get_email_config_error error=%s", exc)
        return JSONResponse({"configured": False, "error": str(exc)})


# -----------------------------------------------------------------------------
# GENERACIÓN DE ARCHIVO EML (ALTERNATIVA A SMTP)
# -----------------------------------------------------------------------------

class EmlDownloadRequestModel(BaseModel):
    """Request para generar archivo .eml descargable."""
    incident_id: int
    recipients: str  # Emails separados por coma o punto y coma
    subject: str
    html_body: str = ""  # HTML completo del correo
    include_xls: bool = True
    include_txt: bool = True


DEFAULT_EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .header { background: #2563eb; color: white; padding: 20px; border-radius: 8px 8px 0 0; }
        .content { padding: 20px; background: #f8fafc; border: 1px solid #e2e8f0; }
        .footer { padding: 15px; background: #f1f5f9; border-radius: 0 0 8px 8px; font-size: 12px; color: #64748b; }
        table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #e2e8f0; }
        th { background: #f1f5f9; font-weight: 600; }
        .badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; }
        .badge-warning { background: #fef3c7; color: #92400e; }
    </style>
</head>
<body>
    <div class="header">
        <h2>🔒 Notificación de Protocolo de Protección</h2>
    </div>
    <div class="content">
        <p>Se ha activado el Protocolo de Protección en la red de fibra óptica.</p>
        <table>
            <tr><th>Ticket</th><td>{{ticket}}</td></tr>
            <tr><th>Servicio Afectado</th><td>{{servicio_afectado}}</td></tr>
            <tr><th>Servicio Protegido</th><td>{{servicio_protegido}}</td></tr>
            <tr><th>Cámaras Baneadas</th><td>{{total_camaras}}</td></tr>
            <tr><th>Fecha</th><td>{{fecha}}</td></tr>
            <tr><th>Motivo</th><td>{{motivo}}</td></tr>
        </table>
        <p>Se adjunta el detalle de las cámaras afectadas.</p>
    </div>
    <div class="footer">
        <p>Este mensaje fue generado automáticamente por LAS-FOCAS - Metrotel</p>
    </div>
</body>
</html>
"""


@app.post("/api/infra/notify/download-eml")
async def generate_eml_file(
    request: Request,
    eml_request: EmlDownloadRequestModel,
) -> Response:
    """Genera un archivo .eml descargable con el correo de notificación.
    
    Este endpoint es una alternativa cuando no se puede usar SMTP directamente
    (ej: Office 365 sin App Password). El usuario puede abrir el .eml con su
    cliente de correo y enviarlo manualmente.
    
    Args:
        eml_request: Datos del correo a generar
        
    Returns:
        Archivo .eml para descarga
    """
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.utils import formataddr, formatdate
    from datetime import datetime, timezone
    import io
    import re
    
    username, _ = _require_auth(request)
    
    try:
        from db.models.infra import Servicio
        from db.session import SessionLocal
        from core.config import get_settings
        from core.services.protection_service import ProtectionService
        
        settings = get_settings()
        
        # Parsear destinatarios (soporta coma, punto y coma, espacios)
        recipients_raw = re.split(r'[,;\s]+', eml_request.recipients.strip())
        recipients = [r.strip() for r in recipients_raw if r.strip() and '@' in r]
        
        if not recipients:
            return JSONResponse(
                {"error": "No se especificaron destinatarios válidos"},
                status_code=400
            )
        
        with SessionLocal() as session:
            # Obtener datos del incidente
            protection_svc = ProtectionService(session)
            incidente = protection_svc.get_incidente_by_id(eml_request.incident_id)
            
            if not incidente:
                return JSONResponse(
                    {"error": f"Incidente {eml_request.incident_id} no encontrado"},
                    status_code=404
                )
            
            # Obtener cámaras afectadas
            camaras_afectadas = protection_svc.get_camaras_for_servicio(
                incidente.servicio_protegido_id,
                incidente.ruta_protegida_id
            )
            
            # Preparar variables para el template
            template_vars = {
                "ticket": incidente.ticket_asociado or f"INC-{incidente.id}",
                "servicio_afectado": incidente.servicio_afectado_id or "-",
                "servicio_protegido": incidente.servicio_protegido_id or "-",
                "total_camaras": len(camaras_afectadas),
                "fecha": incidente.fecha_inicio.astimezone(TZ_ARG).strftime("%d/%m/%Y %H:%M") if incidente.fecha_inicio else "-",
                "motivo": incidente.motivo or "Sin especificar",
            }
            
            # Determinar el cuerpo HTML
            html_body = eml_request.html_body.strip()
            
            if not html_body:
                # Usar template por defecto
                html_body = DEFAULT_EMAIL_TEMPLATE
            
            # Reemplazar variables residuales {{variable}}
            for key, value in template_vars.items():
                html_body = html_body.replace(f"{{{{{key}}}}}", str(value))
            
            # Crear mensaje MIME
            msg = MIMEMultipart("mixed")
            msg["From"] = formataddr((
                settings.smtp.from_name or "LAS-FOCAS",
                settings.smtp.from_email or "notificaciones@lasfocas.local"
            ))
            msg["To"] = ", ".join(recipients)
            msg["Subject"] = eml_request.subject
            msg["Date"] = formatdate(localtime=True)
            msg["X-Mailer"] = "LAS-FOCAS Notification System"
            
            # Cuerpo HTML
            html_part = MIMEText(html_body, "html", "utf-8")
            msg.attach(html_part)
            
            attachments_info = []
            
            # Adjuntar Excel con cámaras baneadas
            if eml_request.include_xls:
                try:
                    import pandas as pd
                    
                    rows = []
                    for camara in camaras_afectadas:
                        rows.append({
                            "ID": camara.id,
                            "Nombre": camara.nombre or "",
                            "Fontine_ID": camara.fontine_id or "",
                            "Dirección": camara.direccion or "",
                            "Estado": camara.estado.value if camara.estado else "-",
                            "Ticket": incidente.ticket_asociado or f"INC-{incidente.id}",
                        })
                    
                    if rows:
                        df = pd.DataFrame(rows)
                        xls_buffer = io.BytesIO()
                        with pd.ExcelWriter(xls_buffer, engine="openpyxl") as writer:
                            df.to_excel(writer, sheet_name="Camaras_Baneadas", index=False)
                        xls_buffer.seek(0)
                        
                        xls_part = MIMEApplication(xls_buffer.getvalue())
                        xls_filename = f"camaras_baneadas_{incidente.ticket_asociado or incidente.id}.xlsx"
                        xls_part.add_header(
                            "Content-Disposition",
                            "attachment",
                            filename=xls_filename
                        )
                        msg.attach(xls_part)
                        attachments_info.append(xls_filename)
                        
                except ImportError:
                    logger.warning("action=generate_eml warning=pandas_not_available skipping_xls=true")
            
            # Adjuntar TXT original de tracking
            if eml_request.include_txt:
                servicio = session.query(Servicio).filter(
                    Servicio.servicio_id == incidente.servicio_protegido_id
                ).first()
                
                if servicio and servicio.rutas:
                    for ruta in servicio.rutas:
                        if ruta.raw_file_content:
                            txt_filename = (
                                ruta.nombre_archivo_origen
                                or f"tracking_{servicio.servicio_id}.txt"
                            )
                            txt_part = MIMEApplication(
                                ruta.raw_file_content.encode("utf-8"),
                                Name=txt_filename
                            )
                            txt_part.add_header(
                                "Content-Disposition",
                                "attachment",
                                filename=txt_filename
                            )
                            msg.attach(txt_part)
                            attachments_info.append(txt_filename)
                            break  # Solo un TXT
            
            # Generar contenido del .eml
            eml_content = msg.as_bytes()
            
            # Nombre del archivo .eml
            ticket_safe = re.sub(r'[^\w\-]', '_', incidente.ticket_asociado or f"INC_{incidente.id}")
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            eml_filename = f"notificacion_{ticket_safe}_{timestamp}.eml"
            
            logger.info(
                "action=generate_eml user=%s incident_id=%d recipients=%d attachments=%s",
                username,
                eml_request.incident_id,
                len(recipients),
                attachments_info,
            )
            
            return Response(
                content=eml_content,
                media_type="message/rfc822",
                headers={
                    "Content-Disposition": f'attachment; filename="{eml_filename}"',
                }
            )
            
    except Exception as exc:
        logger.exception("action=generate_eml_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"error": f"Error generando archivo EML: {exc!s}"},
            status_code=500
        )


# -----------------------------------------------------------------------------
# EXPORTACIÓN DE CÁMARAS
# -----------------------------------------------------------------------------

@app.get("/api/infra/export/cameras")
async def export_cameras_web(  # noqa: C901
    request: Request,
    filter_status: Optional[str] = None,
    servicio_id: Optional[str] = None,
    format: str = "csv",
) -> Response:
    """Exporta listado de cámaras a CSV o XLSX."""
    
    username, _ = _require_auth(request)
    
    try:
        from db.models.infra import Camara, CamaraEstado, IncidenteBaneo, Servicio
        from db.session import SessionLocal
        from datetime import datetime, timezone
        import csv
        import io
        
        with SessionLocal() as session:
            query = session.query(Camara)
            
            # Filtrar por estado
            if filter_status and filter_status.upper() != "ALL":
                estado_upper = filter_status.upper()
                if estado_upper in [e.value for e in CamaraEstado]:
                    query = query.filter(Camara.estado == CamaraEstado(estado_upper))
            
            # Filtrar por servicio
            if servicio_id:
                servicio = session.query(Servicio).filter(
                    Servicio.servicio_id == servicio_id
                ).first()
                
                if servicio:
                    camara_ids = set()
                    for ruta in servicio.rutas_activas:
                        for empalme in ruta.empalmes:
                            if empalme.camara:
                                camara_ids.add(empalme.camara.id)
                    
                    if camara_ids:
                        query = query.filter(Camara.id.in_(camara_ids))
                    else:
                        query = query.filter(Camara.id == -1)
            
            camaras = query.order_by(Camara.nombre).all()
            
            # Obtener tickets de baneo activos
            baneos_activos = session.query(IncidenteBaneo).filter(
                IncidenteBaneo.activo == True
            ).all()
            
            ticket_por_servicio: dict = {}
            for baneo in baneos_activos:
                ticket_por_servicio[baneo.servicio_protegido_id] = baneo.ticket_asociado or f"INC-{baneo.id}"
            
            # Preparar datos
            rows = []
            for cam in camaras:
                servicios_cat6 = []
                for empalme in cam.empalmes:
                    for srv in empalme.servicios:
                        if srv.servicio_id and srv.servicio_id not in servicios_cat6:
                            servicios_cat6.append(srv.servicio_id)
                
                ticket_baneo = ""
                if cam.estado == CamaraEstado.BANEADA:
                    for svc_id in servicios_cat6:
                        if svc_id in ticket_por_servicio:
                            ticket_baneo = ticket_por_servicio[svc_id]
                            break
                
                rows.append({
                    "ID": cam.id,
                    "Nombre": cam.nombre or "",
                    "Fontine_ID": cam.fontine_id or "",
                    "Dirección": cam.direccion or "",
                    "Estado": cam.estado.value if cam.estado else "LIBRE",
                    "Servicios_Cat6": ", ".join(servicios_cat6),
                    "Ticket_Baneo": ticket_baneo,
                    "Latitud": cam.latitud or "",
                    "Longitud": cam.longitud or "",
                    "Origen_Datos": cam.origen_datos.value if cam.origen_datos else "MANUAL",
                })
            
            logger.info(
                "action=export_cameras user=%s filter_status=%s format=%s rows=%d",
                username,
                filter_status,
                format,
                len(rows),
            )
            
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            
            if format.lower() == "xlsx":
                try:
                    import pandas as pd
                    
                    df = pd.DataFrame(rows)
                    output = io.BytesIO()
                    
                    with pd.ExcelWriter(output, engine="openpyxl") as writer:
                        df.to_excel(writer, sheet_name="Cámaras", index=False)
                    
                    output.seek(0)
                    
                    return Response(
                        content=output.getvalue(),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={
                            "Content-Disposition": f'attachment; filename="camaras_{timestamp}.xlsx"',
                        },
                    )
                    
                except ImportError:
                    logger.warning("action=export_cameras warning=pandas_not_available fallback=csv")
            
            # CSV (default)
            output = io.StringIO()
            if rows:
                writer = csv.DictWriter(output, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            else:
                output.write("Sin datos\\n")
            
            content = output.getvalue().encode("utf-8-sig")
            
            return Response(
                content=content,
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="camaras_{timestamp}.csv"',
                },
            )
            
    except Exception as exc:
        logger.exception("action=export_cameras_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"error": f"Error exportando cámaras: {exc!s}"},
            status_code=500
        )


class SearchFilterModel(BaseModel):
    """Filtro individual para búsqueda avanzada."""
    field: str
    operator: str = "contains"
    value: str | list[str]


class SearchRequestModel(BaseModel):
    """Request para búsqueda avanzada de cámaras."""
    filters: list[SearchFilterModel] = []
    limit: int = 100
    offset: int = 0


@app.post("/api/infra/search")
async def advanced_search_camaras_web(  # noqa: C901
    request: Request,
    body: SearchRequestModel,
) -> JSONResponse:
    """Búsqueda avanzada de cámaras con filtros combinables (AND).

    Campos: service_id, address, status, cable, origen
    Operadores: eq, contains, starts_with, ends_with, in
    """

    username, _ = _require_auth(request)

    try:
        from db.models.infra import Camara
        from db.session import SessionLocal

        limit = min(body.limit, 500)
        offset = max(body.offset, 0)

        with SessionLocal() as session:
            all_camaras = session.query(Camara).order_by(Camara.nombre).all()

            def apply_text_filter(value: str, operator: str, db_value: str | None) -> bool:
                if db_value is None:
                    return False
                db_lower = db_value.lower()
                val_lower = value.lower() if isinstance(value, str) else value

                if operator == "eq":
                    return db_lower == val_lower
                elif operator == "contains":
                    return val_lower in db_lower
                elif operator == "starts_with":
                    return db_lower.startswith(val_lower)
                elif operator == "ends_with":
                    return db_lower.endswith(val_lower)
                elif operator == "in":
                    if isinstance(value, list):
                        return db_lower in [v.lower() for v in value]
                    return db_lower == val_lower
                return False

            def get_camara_servicios(camara: Camara) -> list[str]:
                servicios_ids = []
                for empalme in camara.empalmes:
                    for servicio in empalme.servicios:
                        if servicio.servicio_id and servicio.servicio_id not in servicios_ids:
                            servicios_ids.append(servicio.servicio_id)
                return servicios_ids

            def get_camara_cables(camara: Camara) -> list[str]:
                cables_nombres = []
                for cable in camara.cables:
                    if cable.nombre and cable.nombre not in cables_nombres:
                        cables_nombres.append(cable.nombre)
                return cables_nombres

            def camara_matches_filter(camara, flt, servicios_ids, cables_nombres) -> bool:
                value = flt.value if isinstance(flt.value, str) else (flt.value[0] if flt.value else "")

                if flt.field == "service_id":
                    for svc_id in servicios_ids:
                        if apply_text_filter(value, flt.operator, svc_id):
                            return True
                    return False

                elif flt.field == "address":
                    return (
                        apply_text_filter(value, flt.operator, camara.nombre) or
                        apply_text_filter(value, flt.operator, camara.direccion)
                    )

                elif flt.field == "status":
                    estado_actual = camara.estado.value if camara.estado else "LIBRE"
                    if flt.operator == "in" and isinstance(flt.value, list):
                        return estado_actual.upper() in [v.upper() for v in flt.value]
                    return estado_actual.upper() == value.upper()

                elif flt.field == "cable":
                    for cable_nombre in cables_nombres:
                        if apply_text_filter(value, flt.operator, cable_nombre):
                            return True
                    return False

                elif flt.field == "origen":
                    origen_actual = camara.origen_datos.value if camara.origen_datos else "MANUAL"
                    if flt.operator == "in" and isinstance(flt.value, list):
                        return origen_actual.upper() in [v.upper() for v in flt.value]
                    return origen_actual.upper() == value.upper()

                return False

            # Si no hay filtros, devolver todas
            if not body.filters:
                total = len(all_camaras)
                paginated = all_camaras[offset:offset + limit]
                camaras_response = []
                for cam in paginated:
                    servicios_ids = get_camara_servicios(cam)
                    camaras_response.append({
                        "id": cam.id,
                        "nombre": cam.nombre or "",
                        "fontine_id": cam.fontine_id,
                        "direccion": cam.direccion,
                        "estado": cam.estado.value if cam.estado else "LIBRE",
                        "origen_datos": cam.origen_datos.value if cam.origen_datos else "MANUAL",
                        "latitud": cam.latitud,
                        "longitud": cam.longitud,
                        "servicios": servicios_ids,
                    })

                return JSONResponse({
                    "status": "ok",
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "filters_applied": 0,
                    "camaras": camaras_response,
                })

            # Aplicar filtros con lógica AND
            matching_camaras = []
            for camara in all_camaras:
                servicios_ids = get_camara_servicios(camara)
                cables_nombres = get_camara_cables(camara)

                matches_all = True
                for flt in body.filters:
                    if not camara_matches_filter(camara, flt, servicios_ids, cables_nombres):
                        matches_all = False
                        break

                if matches_all:
                    matching_camaras.append((camara, servicios_ids))

            total = len(matching_camaras)
            paginated = matching_camaras[offset:offset + limit]
            camaras_response = []
            for cam, svc_ids in paginated:
                camaras_response.append({
                    "id": cam.id,
                    "nombre": cam.nombre or "",
                    "fontine_id": cam.fontine_id,
                    "direccion": cam.direccion,
                    "estado": cam.estado.value if cam.estado else "LIBRE",
                    "origen_datos": cam.origen_datos.value if cam.origen_datos else "MANUAL",
                    "latitud": cam.latitud,
                    "longitud": cam.longitud,
                    "servicios": svc_ids,
                })

            logger.info(
                "action=advanced_search user=%s filters=%d total=%d returned=%d",
                username,
                len(body.filters),
                total,
                len(camaras_response),
            )

            return JSONResponse({
                "status": "ok",
                "total": total,
                "limit": limit,
                "offset": offset,
                "filters_applied": len(body.filters),
                "camaras": camaras_response,
            })

    except Exception as exc:
        logger.exception("action=advanced_search_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"error": f"Error en búsqueda avanzada: {exc!s}"},
            status_code=500
        )


class SmartSearchRequestModel(BaseModel):
    """Request para Smart Search con términos libres."""
    terms: list[str] = []
    limit: int = 100
    offset: int = 0
    estado: Optional[str] = None
    incluir_no_operativas: bool = False


@app.get("/api/infra/camaras/{camara_id}/estado")
async def get_camara_estado_web(request: Request, camara_id: int) -> JSONResponse:
    """Obtiene el contexto operativo del estado de una cámara."""

    _require_admin(request)

    try:
        from core.services.camara_estado_service import get_camara_estado_contexto
        from db.models.infra import CamaraEstado
        from db.session import SessionLocal

        with SessionLocal() as session:
            contexto = get_camara_estado_contexto(session, camara_id)
            if contexto is None:
                return JSONResponse({"error": "Cámara no encontrada"}, status_code=404)

            return JSONResponse(
                {
                    "status": "ok",
                    "editable": True,
                    # Estado operable de Cámara/Botella (2026-08-11): sólo estos 4 valores son
                    # seteables por un admin. DETECTADA y PENDIENTE_REVISION siguen existiendo en el
                    # enum de Postgres (filas legado, no removibles sin recrear el tipo) pero ya no
                    # deben poder asignarse manualmente — ver scripts/retirar_estado_detectada.py.
                    "estados_disponibles": [
                        CamaraEstado.LIBRE.value,
                        CamaraEstado.OCUPADA.value,
                        CamaraEstado.BANEADA.value,
                        CamaraEstado.NO_OPERATIVA.value,
                    ],
                    "contexto": contexto.to_dict(),
                }
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=get_camara_estado_error camara_id=%s error=%s", camara_id, exc)
        return JSONResponse({"error": "No se pudo obtener el estado de la cámara"}, status_code=500)


@app.post("/api/infra/camaras/{camara_id}/estado")
async def update_camara_estado_web(
    request: Request,
    camara_id: int,
    body: CamaraEstadoUpdateRequest,
) -> JSONResponse:
    """Permite a un administrador aplicar un override manual del estado."""

    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=update_camara_estado result=fail reason=csrf user=%s camara_id=%s", username, camara_id)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.camara_estado_service import override_camara_estado_manual
        from db.models.infra import CamaraEstado
        from db.session import SessionLocal

        # Estado operable de Cámara/Botella (2026-08-11): un override manual sólo puede apuntar a
        # estos 4 valores — DETECTADA/PENDIENTE_REVISION quedaron retirados de la asignación activa
        # (siguen existiendo en el enum de Postgres sólo por filas legado, ver
        # scripts/retirar_estado_detectada.py), aunque alguien llame a este endpoint directo sin
        # pasar por el modal (que ya sólo ofrece estos 4 en `estados_disponibles`).
        _ESTADOS_OVERRIDE_VALIDOS = {
            CamaraEstado.LIBRE.value,
            CamaraEstado.OCUPADA.value,
            CamaraEstado.BANEADA.value,
            CamaraEstado.NO_OPERATIVA.value,
        }
        estado_normalizado = body.estado.strip().upper()
        if estado_normalizado not in _ESTADOS_OVERRIDE_VALIDOS:
            return JSONResponse({"error": "Estado inválido"}, status_code=400)

        with SessionLocal() as session:
            result = override_camara_estado_manual(
                session,
                camara_id,
                CamaraEstado(estado_normalizado),
                usuario=username,
                motivo=body.motivo.strip(),
            )
            if not result.success:
                session.rollback()
                return JSONResponse({"error": result.error or "No se pudo actualizar el estado"}, status_code=400)

            if result.changed:
                session.commit()
            else:
                session.rollback()

            return JSONResponse(result.to_dict())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=update_camara_estado_error user=%s camara_id=%s error=%s", username, camara_id, exc)
        return JSONResponse({"error": "No se pudo actualizar el estado de la cámara"}, status_code=500)


# ── Endpoints admin: gestión de cámaras PENDIENTE_REVISION ───────────────


class RegistrarEgresoWebRequestModel(BaseModel):
    """Payload del botón "Registrar egreso" (vista Ingresos del Servicio). `momento` debe traer zona
    horaria — el frontend envía ISO 8601 en UTC; un valor naive se rechaza con 422 en vez de
    adivinar si era hora local o UTC."""

    momento: datetime
    motivo: str = Field(min_length=3, max_length=500)
    csrf_token: str | None = None


# Resultado de `registrar_egreso_web` → status HTTP. Todo lo que no es OK es un rechazo de negocio
# ya auditado en `app.ingresos_correcciones`, no un error del servidor.
_EGRESO_WEB_STATUS = {
    "OK_EGRESO_CERRADO": 200,
    "INGRESO_NO_ENCONTRADO": 404,
    "INGRESO_YA_CERRADO": 409,
    "MOMENTO_INVALIDO": 422,
    "EGRESO_ANTERIOR_AL_INGRESO": 422,
}


@app.post("/api/infra/ingresos/{ingreso_id}/egreso")
async def registrar_egreso_ingreso_web(
    request: Request, ingreso_id: int, body: RegistrarEgresoWebRequestModel,
) -> JSONResponse:
    """Registra el egreso de un `Ingreso` que quedó "en curso" (el formulario de Egreso nunca llegó
    por Slack). Delegado entero en `ingreso_correccion_service.registrar_egreso_web` — mismas reglas
    y mismo log de auditoría que el comando Slack `Forzar egreso #<id>`, con `origen='web'`.

    Sin restricción de rol más allá de estar autenticado: mismo criterio que los comandos de Slack
    (cualquiera del canal puede corregir; la auditoría es el control — ver docstring del servicio)."""
    username, _ = _require_auth(request)
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != request.session.get("csrf")):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    if body.momento.tzinfo is None:
        return JSONResponse({"error": "La fecha de egreso debe incluir zona horaria"}, status_code=422)
    motivo = body.motivo.strip()
    if len(motivo) < 3:
        return JSONResponse({"error": "El motivo es obligatorio"}, status_code=422)

    try:
        from core.services.ingreso_correccion_service import registrar_egreso_web
        from db.session import SessionLocal

        with SessionLocal() as session:
            resultado = registrar_egreso_web(
                session,
                ingreso_id=ingreso_id,
                momento=body.momento,
                motivo=motivo,
                usuario_web=username,
            )
            status = _EGRESO_WEB_STATUS.get(resultado.resultado, 500)
            logger.info(
                "action=registrar_egreso_web user=%s ingreso_id=%s resultado=%s",
                username,
                ingreso_id,
                resultado.resultado,
            )
            if status != 200:
                return JSONResponse(
                    {"error": resultado.respuesta, "resultado": resultado.resultado}, status_code=status
                )
            ingreso = resultado.ingreso
            return JSONResponse(
                {
                    "ok": True,
                    "resultado": resultado.resultado,
                    "mensaje": resultado.respuesta,
                    "ingreso": {
                        "id": ingreso.id,
                        "fecha_inicio": ingreso.fecha_inicio.isoformat() if ingreso.fecha_inicio else None,
                        "fecha_fin": ingreso.fecha_fin.isoformat() if ingreso.fecha_fin else None,
                    },
                }
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=registrar_egreso_web_error user=%s ingreso_id=%s error=%s", username, ingreso_id, exc)
        return JSONResponse({"error": "Error al registrar el egreso"}, status_code=500)


@app.get("/api/admin/infra/ingresos-sin-match")
async def admin_ingresos_sin_match(
    request: Request, revisado: Optional[bool] = None, origen: Optional[str] = None,
) -> JSONResponse:
    """Lista casos de ingreso (bot de Slack o carga de tracking) cuya cámara no matcheó contra el
    inventario (2026-08-11) — reemplaza el auto-registro `PENDIENTE_REVISION`. Es información de
    sólo lectura para revisión manual y mejora del regex, no crea ninguna Cámara. `revisado` filtra
    por el flag (default: todos, sin filtrar). `origen` filtra por uno o más valores separados por
    coma (ej. `?origen=excel_camaras` o `?origen=slack,tracking`; default: todos, sin filtrar)."""
    _require_admin(request)
    try:
        from db.models.infra import IngresoSinMatch
        from db.session import SessionLocal

        with SessionLocal() as session:
            query = session.query(IngresoSinMatch)
            if revisado is not None:
                query = query.filter(IngresoSinMatch.revisado == revisado)
            if origen:
                origenes = [o.strip() for o in origen.split(",") if o.strip()]
                if origenes:
                    query = query.filter(IngresoSinMatch.origen.in_(origenes))
            casos = query.order_by(IngresoSinMatch.created_at.desc()).limit(200).all()
            return JSONResponse([
                {
                    "id": caso.id,
                    "texto_original": caso.texto_original,
                    "origen": caso.origen,
                    "contexto": caso.contexto,
                    "revisado": caso.revisado,
                    "created_at": caso.created_at.isoformat() if caso.created_at else None,
                }
                for caso in casos
            ])
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=admin_ingresos_sin_match error=%s", exc)
        return JSONResponse({"error": "Error al obtener ingresos sin match"}, status_code=500)


@app.post("/api/admin/infra/ingresos-sin-match/{caso_id}/marcar-revisado")
async def admin_marcar_revisado_ingreso_sin_match(request: Request, caso_id: int) -> JSONResponse:
    """Marca un caso de ingreso sin match como revisado — no muta ningún dato de infraestructura,
    sólo el flag de triage."""
    _require_admin(request)
    try:
        from db.models.infra import IngresoSinMatch
        from db.session import SessionLocal

        with SessionLocal() as session:
            caso = session.query(IngresoSinMatch).filter(IngresoSinMatch.id == caso_id).first()
            if not caso:
                return JSONResponse({"error": "Caso no encontrado"}, status_code=404)
            caso.revisado = True
            session.commit()
            return JSONResponse({"ok": True, "id": caso.id})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=admin_marcar_revisado_ingreso_sin_match error=%s", exc)
        return JSONResponse({"error": "Error al marcar el caso como revisado"}, status_code=500)


class MarcarRevisadoMasivoRequestModel(BaseModel):
    """Payload para marcar en lote varios `IngresoSinMatch` como revisados."""

    ids: list[int]
    csrf_token: str | None = None


@app.post("/api/admin/infra/ingresos-sin-match/marcar-revisado-masivo")
async def admin_marcar_revisado_masivo_web(request: Request, body: MarcarRevisadoMasivoRequestModel) -> JSONResponse:
    """Marca en lote varios casos de ingreso sin match como revisados — es el 'Borrado' del visor de
    ingesta: sólo descarta de la vista, no muta ningún dato de infraestructura, la fila queda en la
    base para poder ajustar a futuro el regex/normalización de búsqueda."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    if not body.ids:
        return JSONResponse({"error": "No se especificaron casos"}, status_code=400)

    try:
        from db.models.infra import IngresoSinMatch
        from db.session import SessionLocal

        with SessionLocal() as session:
            actualizados = (
                session.query(IngresoSinMatch)
                .filter(IngresoSinMatch.id.in_(body.ids))
                .update({IngresoSinMatch.revisado: True}, synchronize_session=False)
            )
            session.commit()
            return JSONResponse({"ok": True, "actualizados": actualizados})
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("action=admin_marcar_revisado_masivo_error user=%s error=%s", username, exc)
        return JSONResponse({"error": "No se pudo marcar los casos como revisados"}, status_code=500)


@app.get("/api/admin/infra/camaras/pendientes")
async def admin_camaras_pendientes(request: Request) -> JSONResponse:
    """Lista cámaras auto-registradas en estado PENDIENTE_REVISION."""
    _require_admin(request)
    try:
        from db.models.infra import Camara, CamaraEstado
        from db.session import SessionLocal

        with SessionLocal() as session:
            camaras = (
                session.query(Camara)
                .filter(Camara.estado == CamaraEstado.PENDIENTE_REVISION)
                .order_by(Camara.last_update.desc())
                .all()
            )
            return JSONResponse([
                {
                    "id": c.id,
                    "nombre": c.nombre,
                    "last_update": c.last_update.isoformat() if c.last_update else None,
                    "estado": c.estado.value if c.estado else None,
                }
                for c in camaras
            ])
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=admin_camaras_pendientes error=%s", exc)
        return JSONResponse({"error": "Error al obtener cámaras pendientes"}, status_code=500)


@app.post("/api/admin/infra/camaras/{camara_id}/aprobar")
async def admin_aprobar_camara(request: Request, camara_id: int) -> JSONResponse:
    """Aprueba una cámara PENDIENTE_REVISION, cambiando su estado a LIBRE."""
    _require_admin(request)
    try:
        from db.models.infra import Camara, CamaraEstado
        from db.session import SessionLocal

        with SessionLocal() as session:
            camara = session.query(Camara).filter(Camara.id == camara_id).first()
            if not camara:
                return JSONResponse({"error": "Cámara no encontrada"}, status_code=404)
            if camara.estado != CamaraEstado.PENDIENTE_REVISION:
                return JSONResponse(
                    {"error": f"La cámara no está en estado PENDIENTE_REVISION (estado actual: {camara.estado.value})"},
                    status_code=400,
                )
            camara.estado = CamaraEstado.LIBRE

            # Jerarquía Cámara/Botella: si el nombre ya registrado matchea el sufijo "Bot N",
            # resolver (o crear) la cámara padre y vincularla — ver camara_hierarchy_service.py.
            from core.services.camara_hierarchy_service import resolver_o_crear_padre

            padre = resolver_o_crear_padre(session, camara.nombre, usuario="admin:aprobar")
            if padre is not None:
                camara.camara_padre_id = padre.id
                if padre.estado == CamaraEstado.BANEADA:
                    camara.estado = CamaraEstado.BANEADA

            session.commit()
            logger.info("action=aprobar_camara camara_id=%s nombre='%s'", camara_id, camara.nombre)
            return JSONResponse({"ok": True, "camara_id": camara_id, "estado": camara.estado.value})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=admin_aprobar_camara_error camara_id=%s error=%s", camara_id, exc)
        return JSONResponse({"error": "Error al aprobar la cámara"}, status_code=500)


class _ConvertirAliasRequest(BaseModel):
    camara_destino_id: int


@app.post("/api/admin/infra/camaras/{camara_id}/convertir-alias")
async def admin_convertir_alias(
    request: Request,
    camara_id: int,
    body: _ConvertirAliasRequest,
) -> JSONResponse:
    """Convierte una cámara PENDIENTE_REVISION en alias de otra cámara existente.

    - Crea un registro en ``app.camara_alias`` asociando el nombre de la cámara
      pendiente como alias de la cámara destino.
    - Elimina físicamente el registro pendiente.
    """
    _require_admin(request)
    try:
        from db.models.infra import Camara, CamaraAlias, CamaraEstado
        from db.session import SessionLocal

        with SessionLocal() as session:
            pendiente = session.query(Camara).filter(Camara.id == camara_id).first()
            if not pendiente:
                return JSONResponse({"error": "Cámara pendiente no encontrada"}, status_code=404)
            if pendiente.estado != CamaraEstado.PENDIENTE_REVISION:
                return JSONResponse(
                    {"error": f"La cámara no está en estado PENDIENTE_REVISION (estado actual: {pendiente.estado.value})"},
                    status_code=400,
                )
            destino = session.query(Camara).filter(Camara.id == body.camara_destino_id).first()
            if not destino:
                return JSONResponse({"error": "Cámara destino no encontrada"}, status_code=404)

            alias = CamaraAlias(
                camara_id=destino.id,
                alias_nombre=pendiente.nombre,
            )
            session.add(alias)
            session.delete(pendiente)
            session.commit()
            logger.info(
                "action=convertir_alias pendiente_id=%s nombre='%s' destino_id=%s",
                camara_id, pendiente.nombre, destino.id,
            )
            return JSONResponse({
                "ok": True,
                "alias_nombre": pendiente.nombre,
                "camara_destino_id": destino.id,
            })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=admin_convertir_alias_error camara_id=%s error=%s", camara_id, exc)
        return JSONResponse({"error": "Error al convertir alias"}, status_code=500)


class _DarDeAltaRequest(BaseModel):
    nombre_canon: str


@app.post("/api/admin/infra/camaras/{camara_id}/dar-de-alta")
async def admin_dar_de_alta_camara(
    request: Request,
    camara_id: int,
    body: _DarDeAltaRequest,
) -> JSONResponse:
    """Promueve una cámara PENDIENTE_REVISION a cámara oficial (estado LIBRE).

    Actualiza el nombre al nombre canónico provisto por el admin, cambia el
    estado de ``PENDIENTE_REVISION`` a ``LIBRE``, y guarda el nombre original
    (el que ingresó el técnico) como un alias en ``app.camara_alias``, siempre
    que sea diferente al nombre canónico.
    """
    _require_admin(request)
    nombre_canon = body.nombre_canon.strip()
    if not nombre_canon:
        return JSONResponse({"error": "El nombre canónico no puede estar vacío"}, status_code=400)
    try:
        from db.models.infra import Camara, CamaraAlias, CamaraEstado
        from db.session import SessionLocal

        with SessionLocal() as session:
            camara = session.query(Camara).filter(Camara.id == camara_id).first()
            if not camara:
                return JSONResponse({"error": "Cámara no encontrada"}, status_code=404)
            if camara.estado != CamaraEstado.PENDIENTE_REVISION:
                return JSONResponse(
                    {"error": f"La cámara no está en estado PENDIENTE_REVISION (estado actual: {camara.estado.value})"},
                    status_code=409,
                )
            nombre_original = camara.nombre or ""
            camara.nombre = nombre_canon
            camara.estado = CamaraEstado.LIBRE

            # Guardar el nombre original como alias si difiere del canónico
            alias_creado = False
            if nombre_original and nombre_original.strip().lower() != nombre_canon.lower():
                alias_existente = (
                    session.query(CamaraAlias)
                    .filter(
                        CamaraAlias.camara_id == camara_id,
                        CamaraAlias.alias_nombre == nombre_original,
                    )
                    .first()
                )
                if not alias_existente:
                    session.add(CamaraAlias(camara_id=camara_id, alias_nombre=nombre_original))
                    alias_creado = True

            # Jerarquía Cámara/Botella: recién ahora se conoce el nombre FINAL de la cámara — si
            # matchea el sufijo "Bot N", resolver (o crear) la cámara padre y vincularla.
            from core.services.camara_hierarchy_service import resolver_o_crear_padre

            padre = resolver_o_crear_padre(session, nombre_canon, usuario="admin:dar-de-alta")
            if padre is not None:
                camara.camara_padre_id = padre.id
                if padre.estado == CamaraEstado.BANEADA:
                    camara.estado = CamaraEstado.BANEADA

            session.commit()
            logger.info(
                "action=definir_nombre_canon camara_id=%s nombre_original='%s' nombre_canon='%s' alias_creado=%s",
                camara_id, nombre_original, nombre_canon, alias_creado,
            )
            return JSONResponse({
                "ok": True,
                "id": camara_id,
                "nombre": nombre_canon,
                "alias_creado": alias_creado,
                "alias_nombre": nombre_original if alias_creado else None,
            })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=admin_dar_de_alta_error camara_id=%s error=%s", camara_id, exc)
        return JSONResponse({"error": "Error al dar de alta la cámara"}, status_code=500)


@app.delete("/api/admin/infra/camaras/pendientes/{camara_id}")
async def admin_eliminar_camara_pendiente(
    request: Request,
    camara_id: int,
) -> JSONResponse:
    """Elimina físicamente de la DB una cámara en estado PENDIENTE_REVISION.

    Solo se permite eliminar cámaras que estén en estado ``PENDIENTE_REVISION``.
    Para proteger contra borrados accidentales, registros en otros estados
    deben gestionarse por otros medios.
    """
    _require_admin(request)
    try:
        from db.models.infra import Camara, CamaraEstado
        from db.session import SessionLocal

        with SessionLocal() as session:
            camara = session.query(Camara).filter(Camara.id == camara_id).first()
            if not camara:
                return JSONResponse({"error": "Cámara no encontrada"}, status_code=404)
            if camara.estado != CamaraEstado.PENDIENTE_REVISION:
                return JSONResponse(
                    {
                        "error": (
                            f"Solo se pueden eliminar cámaras en estado PENDIENTE_REVISION "
                            f"(estado actual: {camara.estado.value})"
                        )
                    },
                    status_code=409,
                )
            nombre_eliminado = camara.nombre
            session.delete(camara)
            session.commit()
            logger.info(
                "action=eliminar_pendiente camara_id=%s nombre='%s'",
                camara_id,
                nombre_eliminado,
            )
            return JSONResponse({"ok": True, "id": camara_id})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=admin_eliminar_pendiente_error camara_id=%s error=%s", camara_id, exc)
        return JSONResponse({"error": "Error al eliminar la cámara"}, status_code=500)


@app.get("/api/admin/infra/camaras/viewer")
async def camaras_viewer_listado_web(
    request: Request,
    q: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = 60,
    offset: int = 0,
) -> JSONResponse:
    """Listado paginado de Cámaras raíz para el dashboard `/admin/servicios/viewer/Camaras` (vista
    dual grid/lista). Paginación real en SQL, sin el N+1 en memoria de `smart-search`."""
    _require_admin(request)
    try:
        from db.models.infra import Camara, CamaraEstado
        from db.session import SessionLocal

        with SessionLocal() as session:
            query = session.query(Camara).filter(Camara.camara_padre_id.is_(None))
            if estado and estado.upper() in {e.value for e in CamaraEstado}:
                query = query.filter(Camara.estado == CamaraEstado(estado.upper()))
            if q and q.strip():
                query = query.filter(Camara.nombre.ilike(f"%{q.strip()}%"))

            total = query.count()
            limit = max(1, min(limit, 100))
            offset = max(0, offset)
            filas = query.order_by(Camara.nombre).offset(offset).limit(limit).all()

            return JSONResponse({
                "total": total,
                "limit": limit,
                "offset": offset,
                "camaras": [
                    {
                        "id": c.id,
                        "nombre": c.nombre,
                        "estado": c.estado.value if c.estado else "LIBRE",
                        "botellas_count": len(c.botellas),
                        "cables_count": len(c.cables),
                    }
                    for c in filas
                ],
            })
    except Exception as exc:
        logger.exception("action=camaras_viewer_listado_error error=%s", exc)
        return JSONResponse({"error": "No se pudo obtener el listado de cámaras"}, status_code=500)


@app.get("/api/admin/infra/camaras/viewer/duplicados")
async def camaras_viewer_duplicados_web(request: Request) -> JSONResponse:
    """Grupos de Cámaras raíz candidatas a duplicado por nombre normalizado extendido (sin
    similitud difusa). Devuelve TODOS los grupos sin paginar — la cantidad de grupos es órdenes de
    magnitud menor que el total de Cámaras raíz. Ver `core/services/camara_duplicados_service.py`."""
    _require_admin(request)
    try:
        from core.services.camara_duplicados_service import detectar_grupos_duplicados
        from db.session import SessionLocal

        with SessionLocal() as session:
            grupos = detectar_grupos_duplicados(session)
            return JSONResponse({
                "total_grupos": len(grupos),
                "grupos": [
                    {
                        "clave_normalizada": g.clave_normalizada,
                        "criterio": g.criterio,
                        "estados_en_conflicto": g.estados_en_conflicto,
                        "estado_mas_restrictivo": g.estado_mas_restrictivo,
                        "miembros": [
                            {
                                "id": m.id,
                                "nombre": m.nombre,
                                "estado": m.estado,
                                "botellas_count": m.botellas_count,
                                "cables_count": m.cables_count,
                            }
                            for m in g.miembros
                        ],
                    }
                    for g in grupos
                ],
            })
    except Exception as exc:
        logger.exception("action=camaras_viewer_duplicados_error error=%s", exc)
        return JSONResponse({"error": "No se pudo calcular los grupos de duplicados"}, status_code=500)


@app.post("/api/infra/smart-search")
async def smart_search_camaras_web(  # noqa: C901
    request: Request,
    body: SmartSearchRequestModel,
) -> JSONResponse:
    """Smart Search: búsqueda libre por términos.

    Cada término se busca en múltiples campos (nombre, dirección, fontine_id,
    servicios, cables, estado, origen). Los términos se combinan con AND.
    """

    username, role = _require_auth(request)

    try:
        from sqlalchemy.orm import selectinload

        from core.services.camara_estado_service import get_camara_estado_contexto
        from db.models.infra import Camara
        from db.session import SessionLocal

        limit = min(body.limit, 500)
        offset = max(body.offset, 0)

        with SessionLocal() as session:
            from db.models.infra import CamaraEstado as _CamaraEstado
            # Etapa Cámara/Botella: el dashboard sólo muestra cámaras-raíz — sus Botellas viven en el
            # detalle (GET /api/infra/camaras/{id}/botellas). `selectinload(Camara.botellas)` evita que
            # `incluir_botellas=True` (abajo) dispare una query lazy por cada cámara de la página
            # encima del N+1 ya preexistente de este endpoint (empalmes/rutas/cables sin eager load).
            _query = session.query(Camara).filter(Camara.camara_padre_id.is_(None)).options(
                selectinload(Camara.botellas)
            )
            estado_filter: Optional[str] = None
            if body.estado:
                estado_upper = body.estado.strip().upper()
                if estado_upper in [e.value for e in _CamaraEstado]:
                    _query = _query.filter(Camara.estado == _CamaraEstado(estado_upper))
                    estado_filter = estado_upper

            # Filtro ADICIONAL (AND), independiente del chip de estado de arriba: por defecto nunca
            # se traen cámaras NO_OPERATIVA (infraestructura fantasma/sin señal real que contamina
            # el dashboard) salvo que el toggle "Mostrar No operativas" esté activo, o que el chip de
            # estado ya apunte explícitamente a NO_OPERATIVA.
            if not body.incluir_no_operativas and estado_filter != _CamaraEstado.NO_OPERATIVA.value:
                _query = _query.filter(Camara.estado != _CamaraEstado.NO_OPERATIVA)

            def get_camara_rutas(camara: Camara) -> list[dict]:
                """Rutas del grupo completo (cámara + sus botellas) — reusa la función módulo-level
                que ya usan `get_camara_detail_web`/`get_camara_registros_web`, sin duplicar lógica."""
                return _collect_camara_rutas_info(camara, incluir_botellas=True)

            def get_camara_servicios(camara: Camara, rutas_info: list[dict] = None) -> list[str]:
                """Servicios del grupo completo — idem, reusa la función módulo-level."""
                return _collect_camara_servicios_ids(camara, rutas_info)

            def get_camara_cables(camara: Camara) -> list[str]:
                cables_nombres = []
                for cable in camara.cables:
                    if cable.nombre and cable.nombre not in cables_nombres:
                        cables_nombres.append(cable.nombre)
                return cables_nombres

            def term_matches_camara(term: str, camara, servicios_ids, cables_nombres) -> bool:
                term_lower = term.lower()

                # Buscar en nombre
                if camara.nombre and term_lower in camara.nombre.lower():
                    return True

                # Buscar en dirección
                if camara.direccion and term_lower in camara.direccion.lower():
                    return True

                # Buscar en fontine_id
                if camara.fontine_id and term_lower in camara.fontine_id.lower():
                    return True

                # Buscar en servicios
                for svc_id in servicios_ids:
                    if term_lower in svc_id.lower():
                        return True

                # Buscar en cables
                for cable_nombre in cables_nombres:
                    if term_lower in cable_nombre.lower():
                        return True

                # Buscar en estado
                estado_actual = camara.estado.value if camara.estado else "LIBRE"
                if term_lower in estado_actual.lower():
                    return True

                # Buscar en origen
                origen_actual = camara.origen_datos.value if camara.origen_datos else "MANUAL"
                if term_lower in origen_actual.lower():
                    return True

                return False

            # Si no hay términos, devolver todas — LIMIT/OFFSET real en SQL (no hay términos que
            # matchear contra servicios/cables computados, así que no hace falta materializar todo
            # el resultado en memoria como sí requiere la rama con términos, más abajo).
            if not body.terms:
                total = _query.count()
                paginated = _query.order_by(Camara.nombre).offset(offset).limit(limit).all()
                camaras_response = []
                for cam in paginated:
                    rutas_info = get_camara_rutas(cam)
                    servicios_ids = get_camara_servicios(cam, rutas_info)
                    camaras_response.append(
                        _serialize_camara_response(
                            camara=cam,
                            rutas_info=rutas_info,
                            servicios_ids=servicios_ids,
                            contexto=get_camara_estado_contexto(session, cam.id),
                            editable=role == "admin",
                        )
                    )

                return JSONResponse({
                    "status": "ok",
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "filters_applied": 1 if estado_filter else 0,
                    "estado_filter": estado_filter,
                    "incluir_no_operativas": body.incluir_no_operativas,
                    "camaras": camaras_response,
                })

            # Aplicar términos con lógica AND — necesita el set completo en memoria porque el match
            # incluye campos computados (servicios/cables/rutas) que no se pueden filtrar en SQL sin
            # reescribir esto como un join; a la escala real de cámaras raíz (~10k) es aceptable.
            all_camaras = _query.order_by(Camara.nombre).all()
            matching_camaras = []
            for camara in all_camaras:
                rutas_info = get_camara_rutas(camara)
                servicios_ids = get_camara_servicios(camara, rutas_info)
                cables_nombres = get_camara_cables(camara)

                matches_all = True
                for term in body.terms:
                    term_clean = term.strip()
                    if not term_clean:
                        continue
                    if not term_matches_camara(term_clean, camara, servicios_ids, cables_nombres):
                        matches_all = False
                        break

                if matches_all:
                    matching_camaras.append((camara, servicios_ids, rutas_info))

            total = len(matching_camaras)
            paginated = matching_camaras[offset:offset + limit]
            camaras_response = []
            for cam, svc_ids, rutas in paginated:
                camaras_response.append(
                    _serialize_camara_response(
                        camara=cam,
                        rutas_info=rutas,
                        servicios_ids=svc_ids,
                        contexto=get_camara_estado_contexto(session, cam.id),
                        editable=role == "admin",
                    )
                )

            terms_count = len([t for t in body.terms if t.strip()])
            logger.info(
                "action=smart_search user=%s terms=%d estado=%s incluir_no_operativas=%s total=%d returned=%d",
                username,
                terms_count,
                estado_filter or "ninguno",
                body.incluir_no_operativas,
                total,
                len(camaras_response),
            )

            return JSONResponse({
                "status": "ok",
                "total": total,
                "limit": limit,
                "offset": offset,
                "filters_applied": terms_count + (1 if estado_filter else 0),
                "estado_filter": estado_filter,
                "incluir_no_operativas": body.incluir_no_operativas,
                "camaras": camaras_response,
            })

    except Exception as exc:
        logger.exception("action=smart_search_error user=%s error=%s", username, exc)
        return JSONResponse(
            {"error": f"Error en smart search: {exc!s}"},
            status_code=500
        )


# ── Endpoints: verificador de servicios sobre inventario Cromo (Etapa 6) ─────
# Contrato: docs/Doc Privada/ingesta_cromo.md §8.2. Sólo lectura, cualquier usuario autenticado
# (no requiere rol admin: a diferencia de disparar una ingesta, consultar el inventario ya ingerido
# no es una operación administrativa).


def _serializar_servicio_encontrado(servicio: Any) -> dict[str, Any]:
    return {
        "servicio_id": servicio.servicio_id,
        "servicio_id_externo": servicio.servicio_id_externo,
        "numero_primer_servicio": servicio.numero_primer_servicio,
        "nombre_cliente": servicio.nombre_cliente,
        "cliente": servicio.cliente,
        "estado_servicio": servicio.estado_servicio,
        "categoria": servicio.categoria,
        "tipo_servicio": servicio.tipo_servicio,
        "pelo_n_id": servicio.pelo_n_id,
        "servicio_numero_match": servicio.servicio_numero_match,
        "metodo": servicio.metodo,
    }


@app.get("/api/infra/cromo/cables/{cable_n_id}/servicios")
async def cromo_verificador_por_cable_web(request: Request, cable_n_id: int) -> JSONResponse:
    """Servicios que pasan por un cable entero (cualquiera de sus tubos/pelos)."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_por_cable
    from db.session import AsyncSessionLocal

    _require_auth(request)
    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await servicios_por_cable(sesion, cable_n_id)
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    return JSONResponse(
        {
            "cable_n_id": resultado.cable_n_id,
            "nombre": resultado.nombre,
            "capacidad": resultado.capacidad,
            "extremo_a_nombre": resultado.extremo_a_nombre,
            "extremo_b_nombre": resultado.extremo_b_nombre,
            "servicios": [_serializar_servicio_encontrado(s) for s in resultado.servicios],
        }
    )


@app.get("/api/infra/cromo/tubos/{tubo_n_id}/servicios")
async def cromo_verificador_por_tubo_web(request: Request, tubo_n_id: int) -> JSONResponse:
    """Servicios que pasan por un tubo/buffer específico dentro de un cable."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_por_tubo
    from db.session import AsyncSessionLocal

    _require_auth(request)
    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await servicios_por_tubo(sesion, tubo_n_id)
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    return JSONResponse(
        {
            "tubo_n_id": resultado.tubo_n_id,
            "cable_n_id": resultado.cable_n_id,
            "orden": resultado.orden,
            "nombre_color": resultado.nombre_color,
            "servicios": [_serializar_servicio_encontrado(s) for s in resultado.servicios],
        }
    )


@app.get("/api/infra/cromo/botellas/{botella_n_id}/servicios")
async def cromo_verificador_por_botella_web(request: Request, botella_n_id: int) -> JSONResponse:
    """Servicios que pasan por los cables que tienen esta botella como uno de sus extremos, más el
    listado de esos cables (id, nombre, cantidad de servicios) para la tarjeta "Cables asociados"
    del detalle de Botella en el Verificador."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_por_botella
    from db.session import AsyncSessionLocal

    _require_auth(request)
    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await servicios_por_botella(sesion, botella_n_id)
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    return JSONResponse(
        {
            "botella_n_id": resultado.botella_n_id,
            "nombre": resultado.nombre,
            "clase": resultado.clase,
            "localidad": resultado.localidad,
            "servicios": [_serializar_servicio_encontrado(s) for s in resultado.servicios],
            "cables": [
                {"n_id": c.n_id, "nombre": c.nombre, "cantidad_servicios": c.cantidad_servicios}
                for c in resultado.cables
            ],
        }
    )


# ── Endpoints: servicios ÚNICOS por cable/buffer + resolución de cable + refresco PROV on-demand
# (Task 10, plan "Corrección ingresos + Servicios", 2026-09-23) ─────────────────────────────────
# Vista COMPLEMENTARIA a las tres rutas de arriba (`/cables/{id}/servicios`, `/tubos/{id}/servicios`,
# `/botellas/{id}/servicios`): esas devuelven una fila por PELO (la tabla del Verificador, con su
# columna "Pelo" — varios pelos por servicio es normal, no un defecto). Estas cuatro rutas devuelven
# IDs de servicio ÚNICOS (agregados por `s.id`, `servicios_unicos_por_cable`/`_por_tubo` de la
# Task 1) — dos vistas legítimas del mismo dato que conviven; rutas nuevas, no una extensión de las
# de arriba (no las tocan).


class CromoServicioUnicoFrescuraModel(BaseModel):
    """Estado de sincronización PROV de un `ServicioUnico` puntual (Task 7:
    `core/services/prov/frescura.py`). `ultima_sincronizacion_prov` viaja como string ISO 8601 (no
    `None` salvo que el servicio nunca sincronizó con éxito)."""

    ultima_sincronizacion_prov: Optional[datetime] = Field(default=None)
    antiguedad_horas: Optional[float] = Field(default=None)
    vencida: bool


class CromoServicioUnicoResponseModel(BaseModel):
    """Un servicio único (Task 1: `ServicioUnico`) + su frescura PROV — forma que devuelven las
    tres rutas de servicios únicos (por cable, por buffer, y tras el refresco). `cantidad_pelos`/
    `pelos_n_ids` no son ruido: el ID es único, pero cuántas fibras ocupa es información real."""

    servicio_id: int
    servicio_id_externo: str
    numero_primer_servicio: Optional[str] = None
    nombre_cliente: Optional[str] = None
    cliente: Optional[str] = None
    estado_servicio: Optional[str] = None
    tipo_servicio: Optional[str] = None
    pelos_n_ids: list[int]
    cantidad_pelos: int
    numeros_en_pelo: list[str]
    metodos: list[str]
    frescura: CromoServicioUnicoFrescuraModel


class CromoBufferIdentidadModel(BaseModel):
    """Identidad de un buffer/tubo — `numero` es el 1-indexado que cuenta el técnico (`orden + 1`,
    mismo criterio que `cable_info.py::resolver_tubo_por_numero`)."""

    numero: int
    orden: int
    nombre_color: Optional[str] = None


class CromoRefrescoProvFallidoModel(BaseModel):
    servicio_id_externo: str
    motivo: Optional[str] = None


class CromoRefrescoProvModel(BaseModel):
    """`estado` en {"no_solicitado", "sin_vencidos", "completado", "parcial"}: sólo el POST
    `.../refrescar-prov` dispara un refresco de verdad (puede devolver cualquiera de los últimos
    tres); los dos GET de servicios únicos son de sólo lectura y siempre devuelven
    "no_solicitado" con `fallidos=[]` — no disparan nada."""

    estado: str
    fallidos: list[CromoRefrescoProvFallidoModel] = Field(default_factory=list)


class CromoServiciosUnicosResponseModel(BaseModel):
    cable_n_id: int
    cable_nombre: Optional[str] = None
    buffer: Optional[CromoBufferIdentidadModel] = None
    datos_al: datetime
    servicios: list[CromoServicioUnicoResponseModel]
    refresco_prov: CromoRefrescoProvModel


class CromoCableIdentidadResponseModel(BaseModel):
    n_id: int
    nombre: Optional[str] = None
    capacidad: Optional[str] = None


class CromoServiciosUnicosRefrescarRequestModel(BaseModel):
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


# ── Modelos de error, sólo para documentar `/docs` (Fix round 1, Minor: `response_model` cubre el
# 200 feliz pero `responses=` es la mitad que faltaba de la motivación original — que estas 4 rutas
# sí documenten en OpenAPI, la única desventaja real de vivir acá y no en `api/app/routes/`). Igual
# que el resto de esta sección, no se valida en runtime (los handlers siguen devolviendo
# `JSONResponse` a mano) — sólo alimenta el schema que ve `/docs`.


class CromoNoEncontradoModel(BaseModel):
    """`GET /cables/resolver` cuando `q` no matchea ningún cable vigente — no lleva `error` (a
    diferencia de las otras dos formas de 404 de acá abajo) porque no hay una excepción de dominio
    detrás, sólo "0 candidatos"."""

    codigo: Literal["NO_ENCONTRADO"] = "NO_ENCONTRADO"


class CromoCableNoEncontradoModel(BaseModel):
    """404 de los dos GET de servicios únicos por cable y del POST de refresco — el cable no existe
    ni por fila propia ni por referencia colgada (`ObjetoNoEncontrado`)."""

    codigo: Literal["NO_ENCONTRADO"] = "NO_ENCONTRADO"
    error: str


class CromoBufferNoEncontradoModel(BaseModel):
    """404 propio del GET por buffer — `total_buffers` en vez de `error`, para que el cliente pueda
    orientar al técnico ("el cable tiene 6 buffers, pediste B9")."""

    codigo: Literal["NO_ENCONTRADO"] = "NO_ENCONTRADO"
    total_buffers: int


class CromoAmbiguoModel(BaseModel):
    """409 de `GET /cables/resolver` — 2+ cables vigentes con el mismo nombre (hay al menos 2 pares
    reales conocidos, "F-ALV-2335"/"F-LEM-11-A"); la ambigüedad se hace explícita en vez de elegir
    arbitrariamente."""

    codigo: Literal["AMBIGUO"] = "AMBIGUO"
    candidatos: list[CromoCableIdentidadResponseModel]


class CromoErrorModel(BaseModel):
    """Forma genérica `{"error": "..."}` — CSRF inválido (403) y PROV no configurado (502) del
    POST de refresco."""

    error: str


async def _frescura_por_servicio(sesion: Any, servicio_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Frescura PROV cruda (timestamp + antigüedad + vencida) por `servicio_id`, para el detalle de
    cada `ServicioUnico` en la respuesta REST — a diferencia de `servicios_vencidos` (Task 7), que
    sólo devuelve el subconjunto vencido (un `set[int]`) sin el timestamp real. Reusa
    `horas_frescura()` para el umbral en vez de un segundo valor hardcodeado que se pueda
    desincronizar del real."""
    from datetime import timedelta, timezone

    from sqlalchemy import text

    from core.services.prov.frescura import horas_frescura

    if not servicio_ids:
        return {}
    ahora = datetime.now(timezone.utc)
    corte = ahora - timedelta(hours=horas_frescura())
    filas = (
        await sesion.execute(
            text(
                "SELECT servicio_id, ultima_sincronizacion_ok FROM app.servicios_sync_prov "
                "WHERE servicio_id = ANY(:ids ::integer[])"
            ),
            {"ids": servicio_ids},
        )
    ).all()
    ultimas = {fila[0]: fila[1] for fila in filas}
    resultado: dict[int, dict[str, Any]] = {}
    for servicio_id in servicio_ids:
        ultima = ultimas.get(servicio_id)
        if ultima is not None and ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)
        antiguedad = (ahora - ultima).total_seconds() / 3600 if ultima is not None else None
        vencida = ultima is None or ultima < corte
        resultado[servicio_id] = {
            "ultima_sincronizacion_prov": ultima.isoformat() if ultima is not None else None,
            "antiguedad_horas": antiguedad,
            "vencida": vencida,
        }
    return resultado


def _serializar_servicio_unico(servicio: Any, frescura: dict[str, Any]) -> dict[str, Any]:
    return {
        "servicio_id": servicio.servicio_id,
        "servicio_id_externo": servicio.servicio_id_externo,
        "numero_primer_servicio": servicio.numero_primer_servicio,
        "nombre_cliente": servicio.nombre_cliente,
        "cliente": servicio.cliente,
        "estado_servicio": servicio.estado_servicio,
        "tipo_servicio": servicio.tipo_servicio,
        "pelos_n_ids": list(servicio.pelos_n_ids),
        "cantidad_pelos": servicio.cantidad_pelos,
        "numeros_en_pelo": list(servicio.numeros_en_pelo),
        "metodos": list(servicio.metodos),
        "frescura": frescura,
    }


async def _identidad_cable(sesion: Any, cable_n_id: int) -> Optional[str]:
    """Nombre del cable para la identidad de la respuesta — `None` si el cable sólo se conoce por
    referencia colgada (pelos con servicio matcheado sin fila propia en `cromo_cables`, ver
    docstring de `servicios_unicos_por_cable`)."""
    from db.models.cromo import CromoCable

    cable = await sesion.get(CromoCable, cable_n_id)
    return cable.nombre if cable is not None else None


async def _resolver_cable_por_texto(sesion: Any, texto: str) -> list[tuple[int, Optional[str], Optional[str]]]:
    """Gemela async de `modules/slack_baneo_notifier/cable_info.py::buscar_cable_por_n_id_o_nombre`
    (que usa `Session` síncrona, pensada para el listener de Slack) contra `AsyncSession` — mismo
    criterio de resolución (n_id exacto si `texto` es puramente numérico, si no match exacto case-
    insensitive por `nombre`, sólo cables vigentes). Devuelve una lista para que el caller distinga
    0 (no encontrado) de 2+ (los duplicados reales conocidos, ej. "F-ALV-2335"/"F-LEM-11-A")."""
    from sqlalchemy import text

    texto_limpio = texto.strip()
    if texto_limpio.isdigit():
        filas = (
            await sesion.execute(
                text("SELECT n_id, nombre, capacidad FROM app.cromo_cables WHERE vigente = true AND n_id = :n_id"),
                {"n_id": int(texto_limpio)},
            )
        ).all()
    else:
        filas = (
            await sesion.execute(
                text(
                    "SELECT n_id, nombre, capacidad FROM app.cromo_cables "
                    "WHERE vigente = true AND lower(nombre) = lower(:nombre)"
                ),
                {"nombre": texto_limpio},
            )
        ).all()
    return [(fila[0], fila[1], fila[2]) for fila in filas]


async def _resolver_buffer_por_numero(
    sesion: Any, cable_n_id: int, numero: int
) -> tuple[Optional[tuple[int, int, Optional[str]]], int]:
    """Gemela async de `resolver_tubo_por_numero`/`contar_buffers_cable`
    (`modules/slack_baneo_notifier/cable_info.py`, síncronas) — `numero` es 1-indexado como lo
    cuenta el técnico, mapea a `cromo_tubos.orden = numero - 1` (confirmado con el usuario
    2026-08-13). Devuelve `(tubo_n_id, orden, nombre_color)` o `None` si no existe, más el total de
    buffers vigentes del cable (para que el 404 pueda orientar con `total_buffers`)."""
    from sqlalchemy import text

    fila_tubo = (
        await sesion.execute(
            text(
                "SELECT n_id, orden, nombre_color FROM app.cromo_tubos "
                "WHERE cable_n_id = :cable_n_id AND vigente = true AND orden = :orden"
            ),
            {"cable_n_id": cable_n_id, "orden": numero - 1},
        )
    ).first()
    total_buffers = (
        await sesion.execute(
            text("SELECT count(*) FROM app.cromo_tubos WHERE cable_n_id = :cable_n_id AND vigente = true"),
            {"cable_n_id": cable_n_id},
        )
    ).scalar_one()
    tubo = (fila_tubo[0], fila_tubo[1], fila_tubo[2]) if fila_tubo else None
    return tubo, int(total_buffers)


@dataclass(slots=True)
class _ResultadoRefrescoLote:
    """Resultado directo de `_ejecutar_refresco_prov_lote` — a diferencia de
    `refrescar_servicios_vencidos` (Task 9, fire-and-forget pensado para el hilo de Slack: devuelve
    `None` y postea el resultado a un canal), esta ruta REST corre ya dentro del loop async de
    FastAPI y puede simplemente awaitear el lote y devolver el resultado en la respuesta HTTP."""

    fallidos: list[dict[str, Optional[str]]]


async def _ejecutar_refresco_prov_lote(pendientes: list[Any]) -> _ResultadoRefrescoLote:
    """Corre el refresco PROV de `pendientes` (los `ServicioUnico` ya filtrados a vencidos por el
    caller) de forma síncrona con la petición HTTP — decisión de diseño de la Task 10 (ver reporte):
    reusa el tope/concurrencia/deadline/orden de prioridad y el worker por-servicio de la Task 9
    (`modules/slack_baneo_notifier/refresco_prov.py`: `priorizar_por_antiguedad`/
    `refrescar_un_servicio`, que no tienen ninguna dependencia de Slack) en vez de reimplementar la
    orquestación PROV desde cero, pero NO reusa `refrescar_servicios_vencidos` en sí: esa función
    pública es fire-and-forget, exige `client`/`channel`/`thread_ts` de Slack para postear el
    resultado, y nunca lo devuelve — pensada para encolarse desde el thread síncrono de Slack Bolt
    vía `run_coroutine_threadsafe`. Esta ruta ya corre en el loop de FastAPI (sin ese puente de
    threads) y necesita el resultado directo para la respuesta HTTP, no un canal al que postear."""
    from modules.slack_baneo_notifier.refresco_prov import (
        CONCURRENCIA_MAXIMA,
        DEADLINE_SEGUNDOS,
        TOPE_SERVICIOS_POR_COMANDO,
        ResultadoServicioRefrescado,
        priorizar_por_antiguedad,
        refrescar_un_servicio,
        sincronizar_clientes_de_resultados,
    )
    from core.services.prov.client import get_prov_client

    cliente = get_prov_client()
    ordenados = await priorizar_por_antiguedad(pendientes)
    candidatos = ordenados[:TOPE_SERVICIOS_POR_COMANDO]

    semaforo = asyncio.Semaphore(CONCURRENCIA_MAXIMA)
    resultados: dict[int, Any] = {}

    async def _tarea(servicio: Any) -> None:
        resultados[servicio.servicio_id] = await refrescar_un_servicio(servicio, semaforo, cliente)

    tareas = [asyncio.create_task(_tarea(s)) for s in candidatos]
    try:
        await asyncio.wait_for(asyncio.gather(*tareas, return_exceptions=True), timeout=DEADLINE_SEGUNDOS)
    except asyncio.TimeoutError:
        logger.warning(
            "action=cromo_servicios_unicos_refrescar_prov evento=deadline_alcanzado total=%d", len(candidatos)
        )
    finally:
        for tarea in tareas:
            if not tarea.done():
                tarea.cancel()

    for servicio in candidatos:
        if servicio.servicio_id not in resultados:
            resultados[servicio.servicio_id] = ResultadoServicioRefrescado(
                servicio.servicio_id,
                servicio.servicio_id_externo,
                False,
                "se agotó el tiempo del lote antes de poder intentarlo",
            )

    # Una sola sync de categorías de clientes para el lote, fuera del deadline. Nunca lanza.
    await sincronizar_clientes_de_resultados(resultados.values(), origen="cromo_servicios_unicos_refrescar_prov")

    fallidos = [
        {"servicio_id_externo": r.servicio_id_externo, "motivo": r.motivo_error}
        for r in resultados.values()
        if not r.ok
    ]
    return _ResultadoRefrescoLote(fallidos=fallidos)


@app.get(
    "/api/infra/cromo/cables/resolver",
    response_model=CromoCableIdentidadResponseModel,
    responses={
        404: {"model": CromoNoEncontradoModel, "description": "Ningún cable vigente matchea `q`."},
        409: {
            "model": CromoAmbiguoModel,
            "description": "2+ cables vigentes con el mismo nombre — ambigüedad explícita.",
        },
    },
)
async def cromo_cable_resolver_web(request: Request, q: str) -> JSONResponse:
    """Resuelve un cable por `n_id` (si `q` es puramente numérico) o por `nombre` exacto case-
    insensitive (si no) — ver `_resolver_cable_por_texto`. 404 si no hay ningún cable vigente con
    ese criterio; 409 explícito (nunca elegir arbitrariamente) si hay 2+ — hay al menos 2 pares de
    nombres duplicados reales conocidos (`F-ALV-2335`, `F-LEM-11-A`) sobre ~32.782 cables."""
    from db.session import AsyncSessionLocal

    _require_auth(request)
    async with AsyncSessionLocal() as sesion:
        candidatos = await _resolver_cable_por_texto(sesion, q)

    if not candidatos:
        return JSONResponse({"codigo": "NO_ENCONTRADO"}, status_code=404)
    if len(candidatos) > 1:
        return JSONResponse(
            {
                "codigo": "AMBIGUO",
                "candidatos": [
                    {"n_id": n_id, "nombre": nombre, "capacidad": capacidad} for n_id, nombre, capacidad in candidatos
                ],
            },
            status_code=409,
        )

    n_id, nombre, capacidad = candidatos[0]
    return JSONResponse({"n_id": n_id, "nombre": nombre, "capacidad": capacidad})


@app.get(
    "/api/infra/cromo/cables/{cable_n_id}/servicios-unicos",
    response_model=CromoServiciosUnicosResponseModel,
    responses={
        404: {
            "model": CromoCableNoEncontradoModel,
            "description": "El cable no existe en el inventario ingerido (ni fila propia ni referencia colgada).",
        },
    },
)
async def cromo_servicios_unicos_por_cable_web(request: Request, cable_n_id: int) -> JSONResponse:
    """IDs de servicio únicos (Task 1: `servicios_unicos_por_cable`) de un cable entero, con
    frescura PROV por servicio (Task 7) — vista complementaria a
    `/api/infra/cromo/cables/{id}/servicios` (arriba), que es por-pelo para la tabla del
    Verificador. Sólo lectura: no dispara ningún refresco (eso es el POST `.../refrescar-prov`, más
    abajo) — `refresco_prov` siempre viaja en "no_solicitado" acá."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_unicos_por_cable
    from db.session import AsyncSessionLocal

    _require_auth(request)
    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await servicios_unicos_por_cable(sesion, cable_n_id)
            cable_nombre = await _identidad_cable(sesion, cable_n_id)
            frescura = await _frescura_por_servicio(sesion, [s.servicio_id for s in resultado.servicios])
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"codigo": "NO_ENCONTRADO", "error": str(exc)}, status_code=404)

    from datetime import timezone

    return JSONResponse(
        {
            "cable_n_id": cable_n_id,
            "cable_nombre": cable_nombre,
            "buffer": None,
            "datos_al": datetime.now(timezone.utc).isoformat(),
            "servicios": [_serializar_servicio_unico(s, frescura[s.servicio_id]) for s in resultado.servicios],
            "refresco_prov": {"estado": "no_solicitado", "fallidos": []},
        }
    )


@app.get(
    "/api/infra/cromo/cables/{cable_n_id}/buffers/{numero}/servicios-unicos",
    response_model=CromoServiciosUnicosResponseModel,
    responses={
        404: {
            "model": CromoBufferNoEncontradoModel,
            "description": "El cable no tiene ese buffer (`total_buffers` orienta al cliente).",
        },
    },
)
async def cromo_servicios_unicos_por_buffer_web(request: Request, cable_n_id: int, numero: int) -> JSONResponse:
    """Igual que la ruta anterior, acotado a un buffer humano `B<numero>` puntual (`numero` 1-
    indexado, mapea a `cromo_tubos.orden = numero - 1`, ver `_resolver_buffer_por_numero`). 404 con
    `total_buffers` si el cable no tiene ese buffer — para que el cliente pueda orientar al técnico
    ("el cable tiene 6 buffers, pediste B9")."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_unicos_por_tubo, ResultadoServiciosUnicos
    from db.session import AsyncSessionLocal

    _require_auth(request)
    async with AsyncSessionLocal() as sesion:
        tubo, total_buffers = await _resolver_buffer_por_numero(sesion, cable_n_id, numero)
        if tubo is None:
            return JSONResponse({"codigo": "NO_ENCONTRADO", "total_buffers": total_buffers}, status_code=404)
        tubo_n_id, orden, nombre_color = tubo
        cable_nombre = await _identidad_cable(sesion, cable_n_id)
        try:
            resultado = await servicios_unicos_por_tubo(sesion, tubo_n_id)
        except ObjetoNoEncontrado:
            # El tubo existe de verdad (recién resuelto por fila propia arriba) — un buffer sin
            # ningún pelo cargado todavía no es "no encontrado", es un buffer real sin servicios
            # que reportar (el criterio de "no encontrado" de `servicios_unicos_por_tubo` es
            # tolerante a la fila de TUBO faltante, no al revés: acá la fila sí existe).
            resultado = ResultadoServiciosUnicos(cable_n_id=None, tubo_n_id=tubo_n_id, servicios=[])
        frescura = await _frescura_por_servicio(sesion, [s.servicio_id for s in resultado.servicios])

    from datetime import timezone

    return JSONResponse(
        {
            "cable_n_id": cable_n_id,
            "cable_nombre": cable_nombre,
            "buffer": {"numero": numero, "orden": orden, "nombre_color": nombre_color},
            "datos_al": datetime.now(timezone.utc).isoformat(),
            "servicios": [_serializar_servicio_unico(s, frescura[s.servicio_id]) for s in resultado.servicios],
            "refresco_prov": {"estado": "no_solicitado", "fallidos": []},
        }
    )


@app.post(
    "/api/infra/cromo/cables/{cable_n_id}/servicios-unicos/refrescar-prov",
    response_model=CromoServiciosUnicosResponseModel,
    responses={
        403: {"model": CromoErrorModel, "description": "CSRF inválido."},
        404: {
            "model": CromoCableNoEncontradoModel,
            "description": "El cable no existe en el inventario ingerido.",
        },
        502: {"model": CromoErrorModel, "description": "PROV no está configurado en este entorno."},
    },
)
async def cromo_servicios_unicos_refrescar_prov_web(
    request: Request, cable_n_id: int, body: CromoServiciosUnicosRefrescarRequestModel
) -> JSONResponse:
    """Dispara el refresco PROV (Task 9) de los servicios únicos vencidos de este cable, awaiteado
    dentro del propio request (a diferencia del comando de Slack, fire-and-forget) — ver
    `_ejecutar_refresco_prov_lote`. Responde con el mismo cuerpo que el GET de servicios únicos por
    cable, con `refresco_prov` reflejando el resultado real del lote en vez de "no_solicitado"."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_unicos_por_cable
    from core.services.prov.config import ProvConfigError
    from core.services.prov.frescura import servicios_vencidos
    from db.session import AsyncSessionLocal

    username, _ = _require_auth(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=cromo_servicios_unicos_refrescar_prov result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await servicios_unicos_por_cable(sesion, cable_n_id)
            vencidos = await servicios_vencidos(sesion, [s.servicio_id for s in resultado.servicios])
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"codigo": "NO_ENCONTRADO", "error": str(exc)}, status_code=404)

    pendientes = [s for s in resultado.servicios if s.servicio_id in vencidos]
    if not pendientes:
        refresco_prov: dict[str, Any] = {"estado": "sin_vencidos", "fallidos": []}
    else:
        try:
            lote = await _ejecutar_refresco_prov_lote(pendientes)
        except ProvConfigError as exc:
            logger.error(
                "action=cromo_servicios_unicos_refrescar_prov evento=prov_no_configurado cable_n_id=%s error=%s",
                cable_n_id,
                exc,
            )
            return JSONResponse({"error": f"PROV no está configurado: {exc}"}, status_code=502)
        except Exception as exc:
            logger.exception(
                "action=cromo_servicios_unicos_refrescar_prov_error cable_n_id=%s error=%s", cable_n_id, exc
            )
            return JSONResponse({"error": "No se pudo ejecutar el refresco PROV"}, status_code=500)
        refresco_prov = {"estado": "completado" if not lote.fallidos else "parcial", "fallidos": lote.fallidos}

    async with AsyncSessionLocal() as sesion:
        resultado_final = await servicios_unicos_por_cable(sesion, cable_n_id)
        cable_nombre = await _identidad_cable(sesion, cable_n_id)
        frescura = await _frescura_por_servicio(sesion, [s.servicio_id for s in resultado_final.servicios])

    from datetime import timezone

    return JSONResponse(
        {
            "cable_n_id": cable_n_id,
            "cable_nombre": cable_nombre,
            "buffer": None,
            "datos_al": datetime.now(timezone.utc).isoformat(),
            "servicios": [
                _serializar_servicio_unico(s, frescura[s.servicio_id]) for s in resultado_final.servicios
            ],
            "refresco_prov": refresco_prov,
        }
    )


def _serializar_pelo_empalme(pelo: Any) -> Optional[dict[str, Any]]:
    if pelo is None:
        return None
    return {
        "n_id": pelo.n_id,
        "cable_n_id": pelo.cable_n_id,
        "cable_nombre": pelo.cable_nombre,
        "tubo_n_id": pelo.tubo_n_id,
        "tubo_color": pelo.tubo_color,
        "numero_pelo": pelo.numero_pelo,
        "orden": pelo.orden,
        "color": pelo.color,
        "servicio_raw": pelo.servicio_raw,
        "servicio_numero": pelo.servicio_numero,
    }


@app.get("/api/infra/cromo/botellas/{botella_n_id}/empalmes")
async def cromo_empalmes_de_botella_web(request: Request, botella_n_id: int) -> JSONResponse:
    """Empalmes (fusiones) internos de una Botella, aplanados y con Splitters agrupados en una sola
    fila por pelo de origen — para la tabla dinámica de `/infra/cromo/verificador?...&n_id=.../empalmes`.
    Sólo lectura sobre `app.cromo_fusiones` ya ingerido, cualquier usuario autenticado (mismo
    criterio que el resto de `/api/infra/cromo/*`)."""
    from core.services.cromo.empalmes import empalmes_de_botella
    from core.services.cromo.verificador import ObjetoNoEncontrado
    from db.session import AsyncSessionLocal

    _require_auth(request)
    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await empalmes_de_botella(sesion, botella_n_id)
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    return JSONResponse(
        {
            "botella_n_id": resultado.botella_n_id,
            "nombre": resultado.nombre,
            "cables": [
                {"n_id": c.n_id, "nombre": c.nombre, "cantidad_empalmes": c.cantidad_empalmes}
                for c in resultado.cables
            ],
            "empalmes": [
                {
                    "fusion_n_id": e.fusion_n_id,
                    "nombre_par": e.nombre_par,
                    "es_splitter": e.es_splitter,
                    "pelo_origen": _serializar_pelo_empalme(e.pelo_origen),
                    "pelo_destino": _serializar_pelo_empalme(e.pelo_destino),
                    "splitter_destinos": [_serializar_pelo_empalme(p) for p in e.splitter_destinos],
                    "splitter_ratio": e.splitter_ratio,
                }
                for e in resultado.empalmes
            ],
            # Splitters tal como los declara Cromo (clase 133), con el ratio de `at.83`. Distinto de
            # `empalmes[].es_splitter`, que es la heurística de fan-out: `splitters_relevados=false`
            # significa que esta Botella todavía no se barrió con el código que los lee, no que no
            # tenga ninguno — y mientras tanto la heurística sigue siendo lo único disponible.
            "splitters": [
                {
                    "n_id": s.n_id,
                    "nombre": s.nombre,
                    "ratio": s.ratio,
                    "salidas": s.salidas,
                    "puertos_totales": s.puertos_totales,
                    "puertos_ocupados": s.puertos_ocupados,
                }
                for s in resultado.splitters
            ],
            "splitters_relevados": resultado.splitters_relevados,
        }
    )


@app.get("/api/infra/cromo/cables")
async def cromo_inventario_cables_web(
    request: Request,
    q: Optional[str] = None,
    jerarquia: Optional[str] = None,
    propietario: Optional[str] = None,
    vigente: Optional[bool] = None,
    n_id: Optional[int] = None,
    botella: Optional[str] = None,
    servicio: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> JSONResponse:
    """Inventario navegable de cables ya ingeridos (Etapa 8b, filtros extendidos en Etapa 9) —
    búsqueda + paginación. Sólo lectura, cualquier usuario autenticado (es consulta, no
    administración, mismo criterio que el verificador)."""
    from core.services.cromo.inventario import buscar_cables
    from db.session import AsyncSessionLocal

    _require_auth(request)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    async with AsyncSessionLocal() as sesion:
        resultado = await buscar_cables(
            sesion,
            q=q,
            jerarquia=jerarquia,
            propietario=propietario,
            vigente=vigente,
            n_id=n_id,
            botella=botella,
            servicio=servicio,
            limit=limit,
            offset=offset,
        )

    return JSONResponse(
        {
            "total": resultado.total,
            "limit": resultado.limit,
            "offset": resultado.offset,
            "cables": [
                {
                    "n_id": c.n_id,
                    "nombre": c.nombre,
                    "capacidad": c.capacidad,
                    "capacidad_pelos": c.capacidad_pelos,
                    "jerarquia": c.jerarquia,
                    "propietario": c.propietario,
                    "extremo_a_nombre": c.extremo_a_nombre,
                    "extremo_b_nombre": c.extremo_b_nombre,
                    "vigente": c.vigente,
                    "cantidad_servicios": c.cantidad_servicios,
                }
                for c in resultado.cables
            ],
        }
    )


@app.get("/api/infra/cromo/pon")
async def cromo_inventario_pon_web(
    request: Request,
    q: Optional[str] = None,
    n_id: Optional[int] = None,
    clases: Optional[str] = None,
    vigente: Optional[bool] = None,
    localidad: Optional[str] = None,
    propietario: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> JSONResponse:
    """Inventario navegable de la red de acceso PON: cajas PON y rosetas ya ingeridas.

    Sólo lectura, cualquier usuario autenticado — mismo criterio que los inventarios de cables y
    ODFs.

    `clases` llega como lista separada por comas (`?clases=84,137`) porque cajas PON y rosetas
    comparten tabla: es el parámetro que distingue una vista de la otra. Se ignoran los valores no
    numéricos en vez de devolver 400: un filtro de listado mal tipeado no debería romper la
    pantalla, y el resto de la lista sigue siendo un filtro válido.
    """
    from core.services.cromo.pon_inventario import buscar_pon_elementos
    from db.session import AsyncSessionLocal

    _require_auth(request)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    clases_filtro: Optional[list[int]] = None
    if clases:
        clases_filtro = [int(c) for c in clases.split(",") if c.strip().lstrip("-").isdigit()] or None

    async with AsyncSessionLocal() as sesion:
        resultado = await buscar_pon_elementos(
            sesion,
            q=q,
            n_id=n_id,
            clases=clases_filtro,
            vigente=vigente,
            localidad=localidad,
            propietario=propietario,
            limit=limit,
            offset=offset,
        )

    return JSONResponse(
        {
            "total": resultado.total,
            "limit": resultado.limit,
            "offset": resultado.offset,
            "elementos": [
                {
                    "n_id": e.n_id,
                    "clase": e.clase,
                    "nombre": e.nombre,
                    "localidad": e.localidad,
                    "calle": e.calle,
                    "altura": e.altura,
                    "propietario": e.propietario,
                    "tipo_conector": e.tipo_conector,
                    "capacidad_puertos": e.capacidad_puertos,
                    "latitud": e.latitud,
                    "longitud": e.longitud,
                    "vigente": e.vigente,
                    "cantidad_splitters": e.cantidad_splitters,
                }
                for e in resultado.elementos
            ],
        }
    )


@app.get("/api/infra/cromo/odfs")
async def cromo_inventario_odfs_web(
    request: Request,
    q: Optional[str] = None,
    n_id: Optional[int] = None,
    vigente: Optional[bool] = None,
    tipo_elemento: Optional[str] = None,
    servicio: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> JSONResponse:
    """Inventario navegable de ODFs ya ingeridos (Tarea 4 del plan ODFs) — búsqueda + paginación.
    Sólo lectura, cualquier usuario autenticado (mismo criterio que el inventario de cables)."""
    from core.services.cromo.odf_inventario import buscar_odfs
    from db.session import AsyncSessionLocal

    _require_auth(request)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    async with AsyncSessionLocal() as sesion:
        resultado = await buscar_odfs(
            sesion,
            q=q,
            n_id=n_id,
            vigente=vigente,
            tipo_elemento=tipo_elemento,
            servicio=servicio,
            limit=limit,
            offset=offset,
        )

    return JSONResponse(
        {
            "total": resultado.total,
            "limit": resultado.limit,
            "offset": resultado.offset,
            "odfs": [
                {
                    "n_id": o.n_id,
                    "nombre": o.nombre,
                    "tipo_elemento": o.tipo_elemento,
                    "localidad": o.localidad,
                    "calle": o.calle,
                    "altura": o.altura,
                    "propietario": o.propietario,
                    "vigente": o.vigente,
                    "cantidad_cables_asociados": o.cantidad_cables_asociados,
                    "cantidad_servicios": o.cantidad_servicios,
                }
                for o in resultado.odfs
            ],
        }
    )


def _serializar_detalle_odf(detalle: Any) -> dict[str, Any]:
    return {
        "n_id": detalle.n_id,
        "nombre": detalle.nombre,
        "tipo_elemento": detalle.tipo_elemento,
        "propietario": detalle.propietario,
        "codigo_modelo": detalle.codigo_modelo,
        "id_legacy": detalle.id_legacy,
        "notas": detalle.notas,
        "calle": detalle.calle,
        "altura": detalle.altura,
        "localidad": detalle.localidad,
        "provincia": detalle.provincia,
        "ubicacion_fisica": detalle.ubicacion_fisica,
        "tendido": detalle.tendido,
        "latitud": detalle.latitud,
        "longitud": detalle.longitud,
        "vigente": detalle.vigente,
        "cables_asociados": list(detalle.cables_asociados),
        "odfs_en_la_misma_direccion": list(detalle.odfs_en_la_misma_direccion),
    }


@app.get("/api/infra/cromo/odfs/{n_id}/detalle")
async def cromo_odf_detalle_web(request: Request, n_id: int) -> JSONResponse:
    """Detalle de un ODF: metadata, cables asociados resueltos (n_id + nombre) y otros ODFs que
    comparten domicilio físico (Tarea 4 del plan ODFs). Sólo lectura, cualquier usuario autenticado
    (mismo criterio que el detalle de cable)."""
    from core.services.cromo.odf_detalle import obtener_detalle_odf
    from core.services.cromo.verificador import ObjetoNoEncontrado
    from db.session import AsyncSessionLocal

    _require_auth(request)
    try:
        async with AsyncSessionLocal() as sesion:
            detalle = await obtener_detalle_odf(sesion, n_id)
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    return JSONResponse(_serializar_detalle_odf(detalle))


@app.get("/api/infra/cromo/odfs/{odf_n_id}/servicios")
async def cromo_verificador_por_odf_web(request: Request, odf_n_id: int) -> JSONResponse:
    """Servicios que pasan por los cables asociados a este ODF, más el listado de esos cables (id,
    nombre, cantidad de servicios) — mismo formato de tarjeta "Cables asociados" que el verificador
    de Botella (Tarea 4 del plan ODFs). Sólo lectura, cualquier usuario autenticado."""
    from core.services.cromo.verificador import ObjetoNoEncontrado, servicios_por_odf
    from db.session import AsyncSessionLocal

    _require_auth(request)
    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await servicios_por_odf(sesion, odf_n_id)
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    return JSONResponse(
        {
            "odf_n_id": resultado.odf_n_id,
            "nombre": resultado.nombre,
            "tipo_elemento": resultado.tipo_elemento,
            "localidad": resultado.localidad,
            "servicios": [_serializar_servicio_encontrado(s) for s in resultado.servicios],
            "cables": [
                {"n_id": c.n_id, "nombre": c.nombre, "cantidad_servicios": c.cantidad_servicios}
                for c in resultado.cables
            ],
        }
    )


@app.get("/api/infra/cromo/odfs/{odf_n_id}/conectores")
async def cromo_conectores_de_odf_web(request: Request, odf_n_id: int) -> JSONResponse:
    """Conectores/posiciones de patchera de esta ODF, con Cliente/Estado ya resueltos (atributo
    directo de Cromo + regex del pelo, combinados por MAX-based ID final — ver
    `core/services/cromo/odf_conectores.py`). Sólo lectura, cualquier usuario autenticado."""
    from core.services.cromo.odf_conectores import ObjetoNoEncontrado, conectores_de_odf
    from db.session import AsyncSessionLocal

    _require_auth(request)
    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await conectores_de_odf(sesion, odf_n_id)
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    return JSONResponse(
        {
            "odf_n_id": resultado.odf_n_id,
            "odf_nombre": resultado.odf_nombre,
            "conectores": [
                {
                    "n_id": c.n_id,
                    "bandeja_n_id": c.bandeja_n_id,
                    "bandeja_nombre": c.bandeja_nombre,
                    "numero_conector": c.numero_conector,
                    "pelo_n_id": c.pelo_n_id,
                    "pelo_numero": c.pelo_numero,
                    "servicio_resuelto": c.servicio_resuelto,
                    "servicio_id_historico": c.servicio_id_historico,
                    "servicio_id_externo": c.servicio_id_externo,
                    "nombre_cliente": c.nombre_cliente,
                    "cliente": c.cliente,
                    "estado_servicio": c.estado_servicio,
                }
                for c in resultado.conectores
            ],
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Servicios sin ODF — gestor de asociación manual Servicio→ODF (Tasks 2-4: Cromo)
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/api/infra/botellas/buscar")
async def botellas_unificadas_buscar_web(
    request: Request,
    q: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
    incluir_no_operativas: bool = False,
) -> JSONResponse:
    """Listado unificado de Botellas: `app.cromo_botellas` (Cromo, siempre primero) + `app.camaras`
    con `camara_padre_id` seteado (legado Infra/Baneos) — ambos con estado real desde 2026-08-11.
    `incluir_no_operativas=False` (default) oculta infraestructura fantasma/sin señal real de
    ambos orígenes. Sólo lectura, cualquier usuario autenticado — es consulta, no administración."""
    from core.services.botellas_unificadas_service import buscar_botellas_unificadas
    from db.session import AsyncSessionLocal

    _require_auth(request)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    async with AsyncSessionLocal() as sesion:
        resultado = await buscar_botellas_unificadas(
            sesion, q=q, limit=limit, offset=offset, incluir_no_operativas=incluir_no_operativas
        )

    return JSONResponse(
        {
            "total": resultado.total,
            "limit": resultado.limit,
            "offset": resultado.offset,
            "incluir_no_operativas": incluir_no_operativas,
            "botellas": [
                {"origen": b.origen, "id": b.id, "nombre": b.nombre, "estado": b.estado}
                for b in resultado.botellas
            ],
        }
    )


class BotellaEstadoMasivoItemModel(BaseModel):
    """Item de la clave compuesta `{origen, id}` del inventario unificado — nunca un id numérico
    solo (`CromoBotella.n_id` y `Camara.id` son espacios de ID independientes que pueden colisionar
    en valor)."""

    origen: str  # "cromo" | "legado"
    id: int


class BotellasEstadoMasivoRequestModel(BaseModel):
    """Payload para cambiar el estado de un lote de Botellas de origen mixto (Cromo + legado)."""

    items: list[BotellaEstadoMasivoItemModel]
    estado: str
    motivo: str = "Cambio de estado masivo"
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.put("/api/infra/botellas/estado")
async def botellas_estado_masivo_web(request: Request, body: BotellasEstadoMasivoRequestModel) -> JSONResponse:
    """Cambia el estado de un lote de Botellas (Cromo + legado) en una sola operación. Legado
    cascadea por grupo completo vía `aplicar_estado_a_grupo`; Cromo actualiza `CromoBotella.estado`
    directo (foto propia, ver `core/services/botellas_estado_masivo_service.py`)."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botellas_estado_masivo result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    if not body.items:
        return JSONResponse({"error": "No se especificaron botellas a actualizar"}, status_code=400)

    try:
        from core.services.botellas_estado_masivo_service import (
            ESTADOS_ADMISIBLES,
            EstadoMasivoError,
            ItemBotellaEstado,
            actualizar_estado_masivo,
        )
        from db.models.infra import CamaraEstado
        from db.session import SessionLocal

        estado_normalizado = body.estado.strip().upper()
        if estado_normalizado not in {estado.value for estado in ESTADOS_ADMISIBLES}:
            return JSONResponse({"error": "Estado inválido"}, status_code=400)

        items = [ItemBotellaEstado(origen=item.origen, id=item.id) for item in body.items]

        with SessionLocal() as session:
            try:
                resultado = actualizar_estado_masivo(
                    session,
                    items,
                    CamaraEstado(estado_normalizado),
                    usuario=username,
                    motivo=body.motivo.strip() or "Cambio de estado masivo",
                )
            except EstadoMasivoError as exc:
                session.rollback()
                return JSONResponse({"error": str(exc)}, status_code=400)

            session.commit()
            logger.info(
                "action=botellas_estado_masivo user=%s estado_nuevo=%s legado=%d cromo=%d no_encontrados=%d",
                username,
                resultado.estado_nuevo,
                resultado.legado_actualizadas,
                resultado.cromo_actualizadas,
                len(resultado.no_encontrados),
            )
            return JSONResponse({"ok": True, **resultado.to_dict()})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=botellas_estado_masivo_error user=%s error=%s", username, exc)
        return JSONResponse({"error": "No se pudo actualizar el estado de las Botellas"}, status_code=500)


@app.get("/api/admin/infra/botellas/viewer")
async def botellas_viewer_listado_web(
    request: Request,
    q: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
    incluir_no_operativas: bool = False,
) -> JSONResponse:
    """Listado paginado dual (Cromo + legado) para `/admin/servicios/viewer/Botellas` — delega
    íntegramente en `buscar_botellas_unificadas` (mismo servicio y patrón `AsyncSessionLocal` que ya
    usa `GET /api/infra/botellas/buscar`), con guarda admin adicional para el namespace del dashboard."""
    _require_admin(request)
    try:
        from core.services.botellas_unificadas_service import buscar_botellas_unificadas
        from db.session import AsyncSessionLocal

        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        async with AsyncSessionLocal() as sesion:
            resultado = await buscar_botellas_unificadas(
                sesion, q=q, limit=limit, offset=offset, incluir_no_operativas=incluir_no_operativas
            )

        return JSONResponse({
            "total": resultado.total,
            "limit": resultado.limit,
            "offset": resultado.offset,
            "incluir_no_operativas": incluir_no_operativas,
            "botellas": [
                {"origen": b.origen, "id": b.id, "nombre": b.nombre, "estado": b.estado}
                for b in resultado.botellas
            ],
        })
    except Exception as exc:
        logger.exception("action=botellas_viewer_listado_error error=%s", exc)
        return JSONResponse({"error": "No se pudo obtener el listado de Botellas"}, status_code=500)


@app.get("/api/admin/infra/botellas/viewer/duplicados")
async def botellas_viewer_duplicados_web(request: Request, refrescar: bool = False) -> JSONResponse:
    """Grupos de Botellas (Cromo + legado) candidatas a duplicado dentro de la misma Cámara padre.
    Sin paginar — ver `core/services/botella_duplicados_service.py`. Cada miembro Cromo lleva
    `tiene_cables` (señal "operativa" para elegir el destino al consolidar un grupo no `resoluble`,
    ver `core/services/cromo/verificador.py::tiene_cables_asociados_batch_sync` — una sola query
    batcheada para todos los n_ids de la página, nunca una por miembro); `None` para legado, donde esa
    señal no existe.

    Cada grupo también lleva `sugerencia_placeholders` (`{id_destino_cromo, ids_origen_cromo}` o
    `null`) — patrón "ID dual" (ver `core/services/botella_duplicados_service.py::
    sugerir_consolidacion_placeholders`): grupo 100% Cromo con exactamente un miembro operativo y el
    resto placeholders vacíos del mismo nombre. Es sólo detección/exposición para que un admin la
    consolide manualmente vía `POST /api/infra/botellas/consolidar` — no ejecuta nada acá.

    `?refrescar=true` (el botón "Actualizar" del visor) saltea la lectura de caché y fuerza el cómputo
    síncrono, repoblando la caché con el resultado fresco. Es la escotilla manual para los escritores
    que NO invalidan la caché (ingesta Cromo, cambios de estado/baneo, merge/eliminar Cámaras, el
    backfill de Cámara padre): sin esto, un admin que sabe que algo cambió por fuera de los 7
    mutadores cableados tendría que esperar hasta el TTL de 24h — ver `docs/decisiones.md`,
    entrada 2026-08-21 (cont.). El cómputo (cache miss o `refrescar=true`) corre en un hilo aparte
    (`asyncio.to_thread`) para no bloquear el event loop del proceso `web` — mismo patrón ya usado en
    `modules/botellas_recalculo_worker/worker.py`, ver `docs/decisiones.md`, entrada 2026-08-22."""
    _require_admin(request)
    try:
        from core.services.botella_duplicados_service import (
            detectar_grupos_duplicados_botellas,
            sugerir_consolidacion_placeholders,
        )
        from core.services.cromo.verificador import tiene_cables_asociados_batch_sync
        from db.session import SessionLocal

        with SessionLocal() as session:
            grupos = None if refrescar else await leer_cache_duplicados()
            if grupos is None:
                grupos = await asyncio.to_thread(detectar_grupos_duplicados_botellas, session)
                await guardar_cache_duplicados(grupos)
            ids_cromo = [m.id for g in grupos for m in g.miembros if m.origen == "cromo"]
            operativos = tiene_cables_asociados_batch_sync(session, ids_cromo)
            return JSONResponse({
                "total_grupos": len(grupos),
                "grupos": [
                    {
                        "camara_padre_id": g.camara_padre_id,
                        "camara_padre_nombre": g.camara_padre_nombre,
                        "clave_normalizada": g.clave_normalizada,
                        "criterio": g.criterio,
                        "estados_en_conflicto": g.estados_en_conflicto,
                        "estado_mas_restrictivo": g.estado_mas_restrictivo,
                        "resoluble": g.resoluble,
                        "sugerencia_placeholders": (
                            {"id_destino_cromo": s.id_destino_cromo, "ids_origen_cromo": s.ids_origen_cromo}
                            if (s := sugerir_consolidacion_placeholders(g, operativos))
                            else None
                        ),
                        "miembros": [
                            {
                                "origen": m.origen,
                                "id": m.id,
                                "nombre": m.nombre,
                                "estado": m.estado,
                                "tiene_cables": (m.id in operativos) if m.origen == "cromo" else None,
                            }
                            for m in g.miembros
                        ],
                    }
                    for g in grupos
                ],
            })
    except Exception as exc:
        logger.exception("action=botellas_viewer_duplicados_error error=%s", exc)
        return JSONResponse({"error": "No se pudo calcular los grupos de duplicados"}, status_code=500)


class BotellasOperatividadRequestModel(BaseModel):
    """Payload para consultar, en lote, cuáles de los n_ids Cromo dados tienen cables asociados."""

    n_ids: list[int]


@app.post("/api/admin/infra/botellas/operatividad")
async def botellas_operatividad_web(request: Request, body: BotellasOperatividadRequestModel) -> JSONResponse:
    """Cuáles de los n_ids Cromo dados tienen al menos un cable asociado (extremo_a/b) — señal
    "operativa" para el flujo de consolidación manual con IDs tipeados a mano (sin pasar por un grupo
    ya detectado). Una sola query batcheada, sin N+1."""
    _require_admin(request)
    try:
        from core.services.cromo.verificador import tiene_cables_asociados_batch_sync
        from db.session import SessionLocal

        with SessionLocal() as session:
            operativos = tiene_cables_asociados_batch_sync(session, body.n_ids)
        return JSONResponse({"operativos": sorted(operativos)})
    except Exception as exc:
        logger.exception("action=botellas_operatividad_error error=%s", exc)
        return JSONResponse({"error": "No se pudo calcular operatividad"}, status_code=500)


class BotellaApropiarRequestModel(BaseModel):
    """Payload para apropiar una Botella legado hacia su CromoBotella hermana (mismo padre)."""

    legado_id: int
    cromo_n_id: int
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.post("/api/infra/botellas/apropiar")
async def botellas_apropiar_web(request: Request, body: BotellaApropiarRequestModel) -> JSONResponse:
    """Apropia una Botella legado hacia su CromoBotella hermana: Cromo se conserva, la legado se
    elimina físicamente tras reasignar sus FKs reales a la Cámara padre. Ver
    `core/services/botella_merge_service.py`."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botellas_apropiar result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.botella_merge_service import ApropiacionBotellaError, apropiar_legado_a_cromo
        from db.session import SessionLocal

        with SessionLocal() as session:
            try:
                resultado = apropiar_legado_a_cromo(
                    session, legado_id=body.legado_id, cromo_n_id=body.cromo_n_id, usuario=username,
                )
            except ApropiacionBotellaError as exc:
                session.rollback()
                return JSONResponse({"error": str(exc)}, status_code=400)

            session.commit()
            logger.info(
                "action=botellas_apropiar user=%s legado_id=%s cromo_n_id=%s camara_padre_id=%s "
                "estado_final=%s cables=%d empalmes=%d ingresos=%d aliases=%d",
                username,
                resultado.legado_id,
                resultado.cromo_n_id,
                resultado.camara_padre_id,
                resultado.estado_final,
                resultado.cables_migrados,
                resultado.empalmes_migrados,
                resultado.ingresos_migrados,
                resultado.aliases_migrados,
            )
            await encolar_recalculo_duplicados_botellas(
                motivo=f"apropiar legado_id={resultado.legado_id} cromo_n_id={resultado.cromo_n_id} usuario={username}"
            )
            await _encolar_arbitro(
                "BOTELLAS", [resultado.cromo_n_id], f"apropiar cromo_n_id={resultado.cromo_n_id}"
            )
            return JSONResponse({
                "ok": True,
                "legado_id": resultado.legado_id,
                "legado_nombre": resultado.legado_nombre,
                "cromo_n_id": resultado.cromo_n_id,
                "cromo_nombre": resultado.cromo_nombre,
                "camara_padre_id": resultado.camara_padre_id,
                "camara_padre_nombre": resultado.camara_padre_nombre,
                "botellas_legado_migradas": resultado.botellas_legado_migradas,
                "cromo_reasignadas": resultado.cromo_reasignadas,
                "cables_migrados": resultado.cables_migrados,
                "empalmes_migrados": resultado.empalmes_migrados,
                "ingresos_migrados": resultado.ingresos_migrados,
                "aliases_migrados": resultado.aliases_migrados,
                "estado_final": resultado.estado_final,
            })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=botellas_apropiar_error user=%s error=%s", username, exc)
        return JSONResponse({"error": "No se pudo apropiar la Botella"}, status_code=500)


class BotellaApropiarMasivoRequestModel(BaseModel):
    """Payload para apropiar automáticamente TODOS los grupos de Botellas duplicadas resolubles."""

    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.post("/api/infra/botellas/apropiar-masivo")
async def botellas_apropiar_masivo_web(request: Request, body: BotellaApropiarMasivoRequestModel) -> JSONResponse:
    """Apropia automáticamente TODOS los grupos de Botellas duplicadas `resoluble` (1 legado + 1
    Cromo dentro del mismo padre) detectados en este momento — mismo patrón que
    `POST /api/infra/camaras/merge-masivo`: cada grupo corre en su PROPIA transacción, así que un
    fallo aislado no revierte los grupos ya apropiados exitosamente. Grupos no `resoluble` (todo
    legado, todo cromo, o mixto con 2+ legado) se omiten — no tienen política de resolución
    automática definida, ver `core/services/botella_duplicados_service.py`."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botellas_apropiar_masivo result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.botella_duplicados_service import (
            detectar_grupos_duplicados_botellas,
            sugerir_apropiacion,
        )
        from core.services.botella_merge_service import ApropiacionBotellaError, apropiar_legado_a_cromo
        from db.session import SessionLocal

        grupos = await leer_cache_duplicados()
        if grupos is None:
            with SessionLocal() as session_deteccion:
                grupos = await asyncio.to_thread(detectar_grupos_duplicados_botellas, session_deteccion)
            await guardar_cache_duplicados(grupos)

        resolubles = [(grupo, sugerir_apropiacion(grupo)) for grupo in grupos]
        resolubles = [(grupo, par) for grupo, par in resolubles if par is not None]

        detalle: list[dict[str, Any]] = []
        for grupo, (legado_id, cromo_n_id) in resolubles:
            with SessionLocal() as session:
                try:
                    resultado = apropiar_legado_a_cromo(
                        session, legado_id=legado_id, cromo_n_id=cromo_n_id, usuario=username,
                    )
                except ApropiacionBotellaError as exc:
                    session.rollback()
                    detalle.append({
                        "exito": False,
                        "legado_id": legado_id,
                        "cromo_n_id": cromo_n_id,
                        "camara_padre_nombre": grupo.camara_padre_nombre,
                        "error": str(exc),
                    })
                    continue

                session.commit()
                detalle.append({
                    "exito": True,
                    "legado_id": resultado.legado_id,
                    "cromo_n_id": resultado.cromo_n_id,
                    "camara_padre_nombre": resultado.camara_padre_nombre,
                    "estado_final": resultado.estado_final,
                })

        grupos_apropiados = sum(1 for item in detalle if item["exito"])
        grupos_con_error = len(detalle) - grupos_apropiados
        logger.info(
            "action=botellas_apropiar_masivo user=%s total_grupos=%d grupos_resolubles=%d "
            "grupos_apropiados=%d grupos_con_error=%d",
            username,
            len(grupos),
            len(resolubles),
            grupos_apropiados,
            grupos_con_error,
        )
        if grupos_apropiados > 0:
            await encolar_recalculo_duplicados_botellas(motivo=f"apropiar-masivo usuario={username}")
        return JSONResponse({
            "ok": True,
            "total_grupos": len(grupos),
            "grupos_resolubles": len(resolubles),
            "grupos_apropiados": grupos_apropiados,
            "grupos_con_error": grupos_con_error,
            "detalle": detalle,
        })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=botellas_apropiar_masivo_error user=%s error=%s", username, exc)
        return JSONResponse({"error": "No se pudo ejecutar la apropiación masiva"}, status_code=500)


class BotellaConsolidarRequestModel(BaseModel):
    """Payload para consolidar un grupo LIBRE de n_ids Cromo (no restringido a un grupo detectado
    automáticamente) hacia un único n_id destino, más opcionalmente una o más Botellas legado y un
    nombre corregido para el destino. `force_camera_association=True` bypasea el guard de "misma
    Cámara padre" de `apropiar_legado_a_cromo` para los `ids_legado` incluidos — no afecta la
    consolidación Cromo↔Cromo (`ids_origen_cromo`), que no tiene ese guard (ver docs/decisiones.md
    2026-08-24)."""

    ids_origen_cromo: list[int] = Field(default_factory=list)
    id_destino_cromo: int
    ids_legado: list[int] = Field(default_factory=list)
    nombre_destino: str | None = None
    motivo: str | None = None
    force_camera_association: bool = False
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.post("/api/infra/botellas/consolidar")
async def botellas_consolidar_web(request: Request, body: BotellaConsolidarRequestModel) -> JSONResponse:
    """Consolida un grupo libre de Botellas Cromo duplicadas hacia un único n_id destino: crea/
    actualiza filas en `app.cromo_botella_alias` (`accion='fusionar'`), opcionalmente migra una o más
    Botellas legado hacia el destino (reusa `apropiar_legado_a_cromo` tal cual) y opcionalmente
    corrige el nombre del destino si falta. Cierra el gap "Revisión manual" documentado 2026-08-14 en
    `core/services/botella_duplicados_service.py`. Ver `core/services/cromo/consolidacion_service.py`."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botellas_consolidar result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.botella_merge_service import ApropiacionBotellaError
        from core.services.cromo.consolidacion_service import (
            ConsolidacionBotellaError,
            consolidar_grupo_botellas,
        )
        from db.session import SessionLocal

        with SessionLocal() as session:
            try:
                resultado = consolidar_grupo_botellas(
                    session,
                    ids_origen_cromo=body.ids_origen_cromo,
                    id_destino_cromo=body.id_destino_cromo,
                    ids_legado=body.ids_legado,
                    nombre_destino=body.nombre_destino,
                    motivo=body.motivo,
                    usuario=username,
                    force_camera_association=body.force_camera_association,
                )
            except (ConsolidacionBotellaError, ApropiacionBotellaError) as exc:
                session.rollback()
                return JSONResponse({"error": str(exc)}, status_code=400)

            session.commit()
            logger.info(
                "action=botellas_consolidar user=%s destino=%s origenes=%s legados=%s "
                "alias_creados=%d alias_actualizados=%d repuntados=%d",
                username,
                resultado.id_destino_cromo,
                body.ids_origen_cromo,
                body.ids_legado,
                resultado.alias_creados,
                resultado.alias_actualizados,
                len(resultado.alias_repuntados),
            )
            await encolar_recalculo_duplicados_botellas(
                motivo=f"consolidar destino={resultado.id_destino_cromo} usuario={username}"
            )
            await _encolar_arbitro(
                "BOTELLAS",
                [resultado.id_destino_cromo, *body.ids_origen_cromo],
                f"consolidar destino={resultado.id_destino_cromo}",
            )
            return JSONResponse({
                "ok": True,
                "id_destino_cromo": resultado.id_destino_cromo,
                "alias_creados": resultado.alias_creados,
                "alias_actualizados": resultado.alias_actualizados,
                "alias_repuntados": resultado.alias_repuntados,
                "alias_dependientes_recableados": resultado.alias_dependientes_recableados,
                "cables_existentes_recableados": resultado.cables_existentes_recableados,
                "fusiones_existentes_recableadas": resultado.fusiones_existentes_recableadas,
                "legados_migrados": resultado.legados_migrados,
                "cables_migrados": resultado.cables_migrados,
                "empalmes_migrados": resultado.empalmes_migrados,
                "ingresos_migrados": resultado.ingresos_migrados,
                "camara_aliases_migrados": resultado.camara_aliases_migrados,
                "nombre_anterior": resultado.nombre_anterior,
                "nombre_nuevo": resultado.nombre_nuevo,
                "legados_con_camara_forzada": resultado.legados_con_camara_forzada,
            })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=botellas_consolidar_error user=%s error=%s", username, exc)
        return JSONResponse({"error": "No se pudo consolidar el grupo"}, status_code=500)


@app.get("/api/admin/infra/botellas/inconsistencias/exportar")
async def botellas_inconsistencias_exportar_web(request: Request) -> Response:
    """Excel de inconsistencias de Botellas sin resolver: huérfanas (sin Cámara padre) + miembros de
    grupos duplicados no `resoluble` automáticamente. Columnas: ID Cromo, Nombre, Cámara Padre,
    Motivo — mismo patrón de export ya usado en este archivo para Cámaras (`pd.ExcelWriter(engine=
    "openpyxl")` + `Response` con `Content-Disposition`)."""
    username = _require_admin(request)
    try:
        from datetime import datetime, timezone

        import pandas as pd

        from core.services.botella_duplicados_service import detectar_grupos_duplicados_botellas
        from core.services.cromo.orfanas_service import buscar_huerfanas
        from db.session import AsyncSessionLocal, SessionLocal

        rows: list[dict[str, Any]] = []

        async with AsyncSessionLocal() as sesion:
            huerfanas = await buscar_huerfanas(sesion, limit=100_000, offset=0)
        for h in huerfanas.botellas:
            rows.append({
                "ID Cromo": h.n_id,
                "Nombre": h.nombre or "",
                "Cámara Padre": "",
                "Motivo": "Huérfana — sin Cámara padre asociada",
            })

        with SessionLocal() as session:
            grupos = await leer_cache_duplicados()
            if grupos is None:
                grupos = await asyncio.to_thread(detectar_grupos_duplicados_botellas, session)
                await guardar_cache_duplicados(grupos)
        for g in grupos:
            if g.resoluble:
                continue
            cuenta_cromo = sum(1 for m in g.miembros if m.origen == "cromo")
            cuenta_legado = sum(1 for m in g.miembros if m.origen == "legado")
            descripcion_grupo = (
                f"Duplicado no resoluble — grupo de {len(g.miembros)} miembros "
                f"({cuenta_cromo} Cromo, {cuenta_legado} legado)"
            )
            for m in g.miembros:
                motivo = descripcion_grupo
                if m.origen == "legado":
                    motivo += f"; miembro legado (Camara.id={m.id})"
                rows.append({
                    "ID Cromo": m.id if m.origen == "cromo" else "",
                    "Nombre": m.nombre,
                    "Cámara Padre": g.camara_padre_nombre,
                    "Motivo": motivo,
                })

        logger.info("action=botellas_inconsistencias_exportar user=%s filas=%d", username, len(rows))

        df = pd.DataFrame(rows, columns=["ID Cromo", "Nombre", "Cámara Padre", "Motivo"])
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Inconsistencias", index=False)
        output.seek(0)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return Response(
            content=output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="botellas_inconsistencias_{timestamp}.xlsx"'},
        )
    except Exception as exc:
        logger.exception("action=botellas_inconsistencias_exportar_error error=%s", exc)
        return JSONResponse({"error": "No se pudo generar el reporte"}, status_code=500)


def _serializar_bloqueos(bloqueos: list[Any]) -> list[dict[str, Any]]:
    return [{"origen": b.origen, "id": b.id, "nombre": b.nombre, "razon": b.razon} for b in bloqueos]


class BotellaEliminarRequestModel(BaseModel):
    """Payload para eliminar permanentemente una Botella (legado o Cromo) genuinamente vacía."""

    origen: str
    id: int
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.post("/api/infra/botellas/eliminar")
async def botellas_eliminar_web(request: Request, body: BotellaEliminarRequestModel) -> JSONResponse:
    """Elimina permanentemente una Botella (legado o Cromo) — se rechaza si tiene Cables/Empalmes/
    Ingresos (legado) o Cables/Fusiones Cromo (o si ya es destino de otra fila de alias) asociados;
    sólo se puede eliminar lo que esté genuinamente vacío. Para Cromo, registra automáticamente el
    n_id en `app.cromo_botella_alias` (`accion='ignorar'`) para que la ingesta no la resucite. Si la
    Cámara padre queda vacía como consecuencia, también se elimina. Ver
    `core/services/camara_botella_delete_service.py`."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botellas_eliminar result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.camara_botella_delete_service import EliminacionBloqueadaError, eliminar_botella
        from db.session import SessionLocal

        with SessionLocal() as session:
            try:
                resultado = eliminar_botella(session, origen=body.origen, id=body.id, usuario=username)
            except EliminacionBloqueadaError as exc:
                session.rollback()
                return JSONResponse(
                    {"error": str(exc), "bloqueos": _serializar_bloqueos(exc.bloqueos)}, status_code=400
                )

            session.commit()
            logger.info(
                "action=botellas_eliminar user=%s origen=%s id=%s camara_padre_eliminada=%s alias_registrado=%s",
                username,
                resultado.origen,
                resultado.id,
                resultado.camara_padre_eliminada,
                resultado.alias_registrado,
            )
            await encolar_recalculo_duplicados_botellas(
                motivo=f"eliminar origen={resultado.origen} id={resultado.id} usuario={username}"
            )
            # Legado/cámara no tienen n_id Cromo: el alcance BOTELLAS del árbitro sólo habla de n_id.
            if resultado.origen == "cromo":
                await _encolar_arbitro("BOTELLAS", [resultado.id], f"eliminar cromo_n_id={resultado.id}")
            return JSONResponse({
                "ok": True,
                "origen": resultado.origen,
                "id": resultado.id,
                "camara_padre_eliminada": resultado.camara_padre_eliminada,
                "alias_registrado": resultado.alias_registrado,
            })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=botellas_eliminar_error user=%s error=%s", username, exc)
        return JSONResponse({"error": "No se pudo eliminar la Botella"}, status_code=500)


class BotellaEliminarGrupoRequestModel(BaseModel):
    """Payload para "Borrar y Excluir Cromo": borrado físico FORZADO de un grupo de `CromoBotella`
    conflictivas (botón de grupo del visor de duplicados). A diferencia de
    `BotellaEliminarRequestModel`, ignora deliberadamente la política "bloquear, nunca forzar" —
    ver `core/services/camara_botella_delete_service.py::eliminar_y_excluir_grupo_cromo`."""

    ids_cromo: list[int] = Field(default_factory=list)
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.post("/api/infra/botellas/eliminar-grupo")
async def botellas_eliminar_grupo_web(
    request: Request, body: BotellaEliminarGrupoRequestModel
) -> JSONResponse:
    """Elimina físicamente un grupo de Botellas Cromo conflictivas (residuo de cambios de nombre en
    la ingesta) junto con sus `CromoCable`/`CromoFusion` asociados, SIN bloquear por datos reales —
    a diferencia de `/api/infra/botellas/eliminar`. Registra cada n_id en `app.cromo_botella_alias`
    (`accion='ignorar'`) para que la ingesta no las resucite. Ver
    `core/services/camara_botella_delete_service.py::eliminar_y_excluir_grupo_cromo`."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botellas_eliminar_grupo result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.camara_botella_delete_service import (
            EliminacionBloqueadaError,
            eliminar_y_excluir_grupo_cromo,
        )
        from db.session import SessionLocal

        with SessionLocal() as session:
            try:
                resultado = eliminar_y_excluir_grupo_cromo(
                    session, ids_cromo=body.ids_cromo, usuario=username
                )
            except EliminacionBloqueadaError as exc:
                session.rollback()
                return JSONResponse({"error": str(exc)}, status_code=400)

            session.commit()
            logger.info(
                "action=botellas_eliminar_grupo user=%s botellas=%s cables=%d fusiones=%d "
                "aliases=%d no_encontradas=%s",
                username,
                resultado.botellas_eliminadas,
                resultado.cables_eliminados,
                resultado.fusiones_eliminadas,
                resultado.aliases_registrados,
                resultado.no_encontradas,
            )
            await encolar_recalculo_duplicados_botellas(
                motivo=f"eliminar-grupo botellas={resultado.botellas_eliminadas} usuario={username}"
            )
            if resultado.botellas_eliminadas:
                await _encolar_arbitro(
                    "BOTELLAS", body.ids_cromo, f"eliminar-grupo botellas={resultado.botellas_eliminadas}"
                )
            return JSONResponse({
                "ok": True,
                "botellas_eliminadas": resultado.botellas_eliminadas,
                "cables_eliminados": resultado.cables_eliminados,
                "fusiones_eliminadas": resultado.fusiones_eliminadas,
                "aliases_registrados": resultado.aliases_registrados,
                "no_encontradas": resultado.no_encontradas,
            })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=botellas_eliminar_grupo_error user=%s error=%s", username, exc)
        return JSONResponse({"error": "No se pudo eliminar el grupo de Botellas"}, status_code=500)


class CamaraEliminarRequestModel(BaseModel):
    """Payload para eliminar permanentemente una Cámara raíz genuinamente vacía (cascada a sus Botellas)."""

    camara_id: int
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.post("/api/infra/camaras/eliminar")
async def camaras_eliminar_web(request: Request, body: CamaraEliminarRequestModel) -> JSONResponse:
    """Elimina permanentemente una Cámara raíz junto con TODAS sus Botellas (legado + Cromo) — todo
    o nada: si un solo hijo (o la propia Cámara) tiene Cables/Empalmes/Ingresos/Fusiones reales
    asociados, se rechaza la operación completa sin borrar nada. Cada Botella Cromo eliminada
    registra su n_id en `app.cromo_botella_alias` (`accion='ignorar'`). Ver
    `core/services/camara_botella_delete_service.py`."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=camaras_eliminar result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.camara_botella_delete_service import EliminacionBloqueadaError, eliminar_camara
        from db.session import SessionLocal

        with SessionLocal() as session:
            try:
                resultado = eliminar_camara(session, camara_id=body.camara_id, usuario=username)
            except EliminacionBloqueadaError as exc:
                session.rollback()
                return JSONResponse(
                    {"error": str(exc), "bloqueos": _serializar_bloqueos(exc.bloqueos)}, status_code=400
                )

            session.commit()
            logger.info(
                "action=camaras_eliminar user=%s camara_id=%s legado=%d cromo=%d aliases=%d",
                username,
                resultado.camara_id,
                resultado.botellas_legado_eliminadas,
                resultado.botellas_cromo_eliminadas,
                resultado.aliases_registrados,
            )
            return JSONResponse({
                "ok": True,
                "camara_id": resultado.camara_id,
                "botellas_legado_eliminadas": resultado.botellas_legado_eliminadas,
                "botellas_cromo_eliminadas": resultado.botellas_cromo_eliminadas,
                "aliases_registrados": resultado.aliases_registrados,
            })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=camaras_eliminar_error user=%s error=%s", username, exc)
        return JSONResponse({"error": "No se pudo eliminar la Cámara"}, status_code=500)


@app.get("/api/infra/cromo-botellas/{n_id}/estado-asociacion")
async def cromo_botella_estado_asociacion_web(request: Request, n_id: int) -> JSONResponse:
    """Chequeo liviano de una Botella Cromo puntual: ¿está huérfana (sin `camara_id`)? Usado por
    `BotellaDetalleUnificadaView.vue` para decidir si mostrar el panel de resolución individual en
    vez de redirigir directo al Verificador Cromo. Desde 2026-08-13 también trae `camara_id`/
    `camara_nombre` (Cámara padre) cuando no está huérfana, para la navegación cruzada del
    Verificador hacia `CamaraDetailView.vue`."""
    from sqlalchemy import select

    from db.models.cromo import CromoBotella
    from db.models.infra import Camara
    from db.session import AsyncSessionLocal

    _require_auth(request)
    async with AsyncSessionLocal() as sesion:
        botella = (
            await sesion.execute(
                select(
                    CromoBotella.n_id,
                    CromoBotella.nombre,
                    CromoBotella.camara_id,
                    Camara.nombre,
                )
                .outerjoin(Camara, Camara.id == CromoBotella.camara_id)
                .where(CromoBotella.n_id == n_id)
            )
        ).first()
    if botella is None:
        return JSONResponse({"error": "Botella no encontrada"}, status_code=404)
    return JSONResponse({
        "n_id": botella[0],
        "nombre": botella[1],
        "huerfana": botella[2] is None,
        "camara_id": botella[2],
        "camara_nombre": botella[3],
    })


@app.get("/api/infra/cromo-botellas/huerfanas")
async def cromo_botellas_huerfanas_web(
    request: Request,
    q: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
) -> JSONResponse:
    """Botellas Cromo vigentes sin `camara_id` — no matchearon el regex del backfill automático.
    Sólo lectura, cualquier usuario autenticado. Ver `core/services/cromo/orfanas_service.py`."""
    from core.services.cromo.orfanas_service import buscar_huerfanas
    from db.session import AsyncSessionLocal

    _require_auth(request)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    async with AsyncSessionLocal() as sesion:
        resultado = await buscar_huerfanas(sesion, q=q, limit=limit, offset=offset)

    return JSONResponse({
        "total": resultado.total,
        "limit": resultado.limit,
        "offset": resultado.offset,
        "botellas": [
            {"n_id": b.n_id, "nombre": b.nombre, "calle": b.calle, "localidad": b.localidad}
            for b in resultado.botellas
        ],
    })


class CromoBotellasAsociarRequestModel(BaseModel):
    """Payload para asociar una o más Botellas Cromo huérfanas a una Cámara (existente o nueva)."""

    n_ids: list[int]
    camara_id: Optional[int] = None
    nombre_nueva_camara: Optional[str] = None
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.post("/api/infra/cromo-botellas/asociar")
async def cromo_botellas_asociar_web(request: Request, body: CromoBotellasAsociarRequestModel) -> JSONResponse:
    """Asocia una o más Botellas Cromo huérfanas a una Cámara existente o recién creada — resolución
    manual individual o masiva (Caso 1, huérfanas). Ver `core/services/cromo/orfanas_service.py`."""
    username = _require_auth(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=cromo_botellas_asociar result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.cromo.orfanas_service import AsociarHuerfanasError, asociar_huerfanas
        from db.session import SessionLocal

        with SessionLocal() as session:
            try:
                resultado = asociar_huerfanas(
                    session,
                    n_ids=body.n_ids,
                    camara_id=body.camara_id,
                    nombre_nueva_camara=body.nombre_nueva_camara,
                    usuario=username,
                )
            except AsociarHuerfanasError as exc:
                session.rollback()
                return JSONResponse({"error": str(exc)}, status_code=400)

            session.commit()
            logger.info(
                "action=cromo_botellas_asociar user=%s camara_id=%s camara_creada=%s botellas=%d",
                username,
                resultado.camara_id,
                resultado.camara_creada,
                resultado.botellas_vinculadas,
            )
            return JSONResponse({
                "ok": True,
                "camara_id": resultado.camara_id,
                "camara_creada": resultado.camara_creada,
                "botellas_vinculadas": resultado.botellas_vinculadas,
                "estado_asignado": resultado.estado_asignado,
            })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=cromo_botellas_asociar_error user=%s error=%s", username, exc)
        return JSONResponse({"error": "No se pudieron asociar las Botellas"}, status_code=500)


class CamaraMergeRequestModel(BaseModel):
    """Payload para unificar dos Cámaras raíz duplicadas."""

    camara_principal_id: int
    camara_secundaria_id: int
    guardar_alias: bool = True
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.post("/api/infra/camaras/merge")
async def camaras_merge_web(request: Request, body: CamaraMergeRequestModel) -> JSONResponse:
    """Fusiona dos Cámaras raíz duplicadas: la principal hereda todo lo heredable de la secundaria
    (Botellas propias, Botellas Cromo, Cables, Empalmes, Ingresos, alias y auditoría/historial) y la
    secundaria se elimina físicamente. Ver `core/services/camara_merge_service.py`."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=camaras_merge result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.camara_merge_service import MergeCamarasError, unificar_camaras
        from db.session import SessionLocal

        with SessionLocal() as session:
            try:
                resultado = unificar_camaras(
                    session,
                    principal_id=body.camara_principal_id,
                    secundaria_id=body.camara_secundaria_id,
                    usuario=username,
                    guardar_alias=body.guardar_alias,
                )
            except MergeCamarasError as exc:
                session.rollback()
                return JSONResponse({"error": str(exc)}, status_code=400)

            session.commit()
            logger.info(
                "action=camaras_merge user=%s principal=%s secundaria=%s botellas_legado=%d "
                "botellas_cromo=%d cables=%d empalmes=%d ingresos=%d aliases=%d alias_creado=%s "
                "estado_final=%s",
                username,
                resultado.principal_id,
                resultado.secundaria_id,
                resultado.botellas_legado_migradas,
                resultado.botellas_cromo_migradas,
                resultado.cables_migrados,
                resultado.empalmes_migrados,
                resultado.ingresos_migrados,
                resultado.aliases_migrados,
                resultado.alias_creado,
                resultado.estado_final,
            )
            return JSONResponse({
                "ok": True,
                "principal_id": resultado.principal_id,
                "secundaria_id": resultado.secundaria_id,
                "secundaria_nombre": resultado.secundaria_nombre,
                "botellas_legado_migradas": resultado.botellas_legado_migradas,
                "botellas_cromo_migradas": resultado.botellas_cromo_migradas,
                "cables_migrados": resultado.cables_migrados,
                "empalmes_migrados": resultado.empalmes_migrados,
                "ingresos_migrados": resultado.ingresos_migrados,
                "aliases_migrados": resultado.aliases_migrados,
                "alias_creado": resultado.alias_creado,
                "estado_final": resultado.estado_final,
            })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=camaras_merge_error user=%s error=%s", username, exc)
        return JSONResponse({"error": "No se pudo unificar las cámaras"}, status_code=500)


class CamaraMergeGrupoRequestModel(BaseModel):
    """Payload para fusionar TODAS las Cámaras de un grupo de duplicados dentro de una sola principal."""

    camara_principal_id: int
    camara_secundaria_ids: list[int]
    guardar_alias: bool = True
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.post("/api/infra/camaras/merge-grupo")
async def camaras_merge_grupo_web(request: Request, body: CamaraMergeGrupoRequestModel) -> JSONResponse:
    """Fusiona TODAS las Cámaras de un grupo de duplicados dentro de una única principal, con un solo
    click admin. Mismo mecanismo que `POST /api/infra/camaras/merge` (`unificar_camaras`), aplicado en
    loop con `session.expire_all()` entre cada llamada — ver
    `core/services/camara_merge_service.py::fusionar_grupo_camaras`."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=camaras_merge_grupo result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.camara_merge_service import MergeCamarasError, fusionar_grupo_camaras
        from db.session import SessionLocal

        with SessionLocal() as session:
            try:
                resultado = fusionar_grupo_camaras(
                    session,
                    principal_id=body.camara_principal_id,
                    secundaria_ids=body.camara_secundaria_ids,
                    usuario=username,
                    guardar_alias=body.guardar_alias,
                )
            except MergeCamarasError as exc:
                session.rollback()
                return JSONResponse({"error": str(exc)}, status_code=400)

            session.commit()
            logger.info(
                "action=camaras_merge_grupo user=%s principal=%s secundarias=%s botellas_legado=%d "
                "botellas_cromo=%d cables=%d empalmes=%d ingresos=%d aliases=%d aliases_creados=%d "
                "estado_final=%s",
                username,
                resultado.principal_id,
                resultado.secundarias_fusionadas,
                resultado.botellas_legado_migradas,
                resultado.botellas_cromo_migradas,
                resultado.cables_migrados,
                resultado.empalmes_migrados,
                resultado.ingresos_migrados,
                resultado.aliases_migrados,
                resultado.aliases_creados,
                resultado.estado_final,
            )
            return JSONResponse({
                "ok": True,
                "principal_id": resultado.principal_id,
                "secundarias_fusionadas": resultado.secundarias_fusionadas,
                "secundarias_nombres": resultado.secundarias_nombres,
                "botellas_legado_migradas": resultado.botellas_legado_migradas,
                "botellas_cromo_migradas": resultado.botellas_cromo_migradas,
                "cables_migrados": resultado.cables_migrados,
                "empalmes_migrados": resultado.empalmes_migrados,
                "ingresos_migrados": resultado.ingresos_migrados,
                "aliases_migrados": resultado.aliases_migrados,
                "aliases_creados": resultado.aliases_creados,
                "estado_final": resultado.estado_final,
            })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=camaras_merge_grupo_error user=%s error=%s", username, exc)
        return JSONResponse({"error": "No se pudo fusionar el grupo de Cámaras"}, status_code=500)


class CamaraMergeMasivoRequestModel(BaseModel):
    """Payload para fusionar automáticamente TODOS los grupos de Cámaras duplicadas detectados."""

    guardar_alias: bool = True
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.post("/api/infra/camaras/merge-masivo")
async def camaras_merge_masivo_web(request: Request, body: CamaraMergeMasivoRequestModel) -> JSONResponse:
    """Fusiona automáticamente TODOS los grupos de Cámaras duplicadas detectados en este momento —
    para cada grupo, `sugerir_principal()` (`core/services/camara_duplicados_service.py`) elige la
    Cámara con más `botellas_count + cables_count` (empate → id más bajo) y fusiona las demás dentro
    de ella vía `fusionar_grupo_camaras()` (mismo mecanismo que la fusión de un grupo individual).

    A diferencia de los demás endpoints de este dominio, cada grupo corre en su PROPIA transacción
    (`with SessionLocal()` independiente por grupo, no una sola sesión compartida) — si un grupo falla
    (ej. una Cámara ya fue tocada por otra operación concurrente entre la detección y la fusión), los
    grupos anteriores que ya se commitearon exitosamente NO se revierten; el error de ese grupo queda
    reportado en `detalle` y se sigue con el resto. Es una desviación deliberada del patrón habitual
    (una única sesión/transacción por request) porque acá cada grupo es independiente por diseño
    (nunca comparten Cámaras entre sí) y una falla aislada no debe descartar el resto del lote."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=camaras_merge_masivo result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        from core.services.camara_duplicados_service import detectar_grupos_duplicados, sugerir_principal
        from core.services.camara_merge_service import MergeCamarasError, fusionar_grupo_camaras
        from db.session import SessionLocal

        with SessionLocal() as session_deteccion:
            grupos = detectar_grupos_duplicados(session_deteccion)

        detalle: list[dict[str, Any]] = []
        for grupo in grupos:
            principal_id = sugerir_principal(grupo)
            secundaria_ids = [m.id for m in grupo.miembros if m.id != principal_id]
            with SessionLocal() as session:
                try:
                    resultado = fusionar_grupo_camaras(
                        session,
                        principal_id=principal_id,
                        secundaria_ids=secundaria_ids,
                        usuario=username,
                        guardar_alias=body.guardar_alias,
                    )
                except MergeCamarasError as exc:
                    session.rollback()
                    detalle.append({
                        "exito": False,
                        "principal_id": principal_id,
                        "secundaria_ids": secundaria_ids,
                        "error": str(exc),
                    })
                    continue

                session.commit()
                detalle.append({
                    "exito": True,
                    "principal_id": resultado.principal_id,
                    "secundarias_fusionadas": resultado.secundarias_fusionadas,
                    "estado_final": resultado.estado_final,
                })

        grupos_fusionados = sum(1 for item in detalle if item["exito"])
        grupos_con_error = len(detalle) - grupos_fusionados
        logger.info(
            "action=camaras_merge_masivo user=%s total_grupos=%d grupos_fusionados=%d grupos_con_error=%d",
            username,
            len(grupos),
            grupos_fusionados,
            grupos_con_error,
        )
        return JSONResponse({
            "ok": True,
            "total_grupos": len(grupos),
            "grupos_fusionados": grupos_fusionados,
            "grupos_con_error": grupos_con_error,
            "detalle": detalle,
        })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=camaras_merge_masivo_error user=%s error=%s", username, exc)
        return JSONResponse({"error": "No se pudo ejecutar la fusión masiva"}, status_code=500)


def _serializar_extremo_cable(n_id: Any, clase: Any, legacy: Any, nombre: Any) -> dict[str, Any]:
    return {"n_id": n_id, "clase": clase, "legacy": legacy, "nombre": nombre}


def _serializar_pelo_detalle(pelo: Any) -> dict[str, Any]:
    from core.services.cromo.parser import extraer_tipo_servicio_display

    # "Línea"/"Cliente" reciclan el match ya resuelto por `obtener_detalle_cable`/`pelos_de_tubo_sync`
    # (`v_cromo_servicio_match_vigente` → `app.servicios`, sin JOIN nuevo) — el primero de `pelo.servicios` si
    # existe alguno (ver PeloDetalle.servicios). "-"/None si no hay match, ningún JOIN nuevo por
    # `Servicio.numero_linea`.
    primer_match = pelo.servicios[0] if pelo.servicios else None
    return {
        "n_id": pelo.n_id,
        "numero_pelo": pelo.numero_pelo,
        "orden": pelo.orden,
        "color": pelo.color,
        "tipo_asociacion": pelo.tipo_asociacion,
        "servicio_raw": pelo.servicio_raw,
        "servicio_numero": pelo.servicio_numero,
        "vigente": pelo.vigente,
        "servicios": [_serializar_servicio_encontrado(s) for s in pelo.servicios],
        "tipo_servicio": extraer_tipo_servicio_display(pelo.servicio_raw),
        "linea": primer_match.servicio_id_externo if primer_match else None,
        "cliente": (primer_match.nombre_cliente or primer_match.cliente) if primer_match else None,
        "verificable": pelo.verificable,
        "status": pelo.status,
        "fecha_hora_status": pelo.fecha_hora_status.isoformat() if pelo.fecha_hora_status else None,
        # Pelo de un caso de inconsistencia de Cromo en CUARENTENA: `servicios` viene vacío pero el
        # pelo no está libre; el SPA lo marca "en cuarentena (inconsistencia Cromo)".
        "en_cuarentena": pelo.en_cuarentena,
    }


def _serializar_detalle_cable(detalle: Any) -> dict[str, Any]:
    return {
        "n_id": detalle.n_id,
        "nombre": detalle.nombre,
        "capacidad": detalle.capacidad,
        "capacidad_pelos": detalle.capacidad_pelos,
        "jerarquia": detalle.jerarquia,
        "propietario": detalle.propietario,
        "tendido": detalle.tendido,
        # Decimal no es serializable por JSONResponse/json.dumps — a float explícito.
        "distancia_geo": float(detalle.distancia_geo) if detalle.distancia_geo is not None else None,
        "distancia_real": float(detalle.distancia_real) if detalle.distancia_real is not None else None,
        "id_legacy": detalle.id_legacy,
        "notas": detalle.notas,
        "vigente": detalle.vigente,
        "extremo_a": _serializar_extremo_cable(
            detalle.extremo_a_n_id, detalle.extremo_a_clase, detalle.extremo_a_legacy, detalle.extremo_a_nombre
        ),
        "extremo_b": _serializar_extremo_cable(
            detalle.extremo_b_n_id, detalle.extremo_b_clase, detalle.extremo_b_legacy, detalle.extremo_b_nombre
        ),
        "tubos": [
            {
                "n_id": t.n_id,
                "orden": t.orden,
                "nombre_color": t.nombre_color,
                "vigente": t.vigente,
                "tiene_fila_propia": t.tiene_fila_propia,
                "pelos": [_serializar_pelo_detalle(p) for p in t.pelos],
            }
            for t in detalle.tubos
        ],
    }


@app.get("/api/infra/cromo/cables/{n_id}/detalle")
async def cromo_cable_detalle_web(request: Request, n_id: int) -> JSONResponse:
    """Detalle jerárquico completo de un cable: metadata, extremos, tubos/buffers y pelos con su
    servicio matcheado (Etapa 9). Sólo lectura, cualquier usuario autenticado (mismo criterio que el
    verificador/inventario)."""
    from core.services.cromo.detalle import obtener_detalle_cable
    from core.services.cromo.verificador import ObjetoNoEncontrado
    from db.session import AsyncSessionLocal

    _require_auth(request)
    try:
        async with AsyncSessionLocal() as sesion:
            detalle = await obtener_detalle_cable(sesion, n_id)
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    return JSONResponse(_serializar_detalle_cable(detalle))


def _serializar_elemento_vivo(elemento: Any) -> dict[str, Any]:
    return {
        "n_id": elemento.n_id,
        "version_id": elemento.version_id,
        "clase": elemento.clase,
        "clase_etiqueta": elemento.clase_etiqueta,
        "clase_entidad": elemento.clase_entidad,
        "nombre": elemento.nombre,
        "notas": elemento.notas,
        "atributos": [{"id": a.id, "etiqueta": a.etiqueta, "valor": a.valor} for a in elemento.atributos],
        "payload_raw": elemento.payload_raw,
    }


@app.get("/api/infra/cromo/elementos/{n_id}/vivo")
async def cromo_elemento_vivo_web(request: Request, n_id: int) -> JSONResponse:
    """Visor en vivo de un elemento Cromo por `n_id` — GET directo contra Cromo (nunca contra las
    tablas ya ingeridas), para auditar inconsistencias sin esperar a la próxima corrida de ingesta.
    Sólo lectura, cualquier usuario autenticado (mismo criterio que el resto de `/api/infra/cromo/*`).
    Nunca persiste nada."""
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo.live_lookup_service import obtener_elemento_vivo
    from core.services.cromo.verificador import ObjetoNoEncontrado
    from db.session import AsyncSessionLocal

    _require_auth(request)
    try:
        async with AsyncSessionLocal() as sesion, CromoClient(config=get_cromo_config()) as cliente:
            elemento = await obtener_elemento_vivo(cliente, sesion, n_id)
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except CromoClientError as exc:
        return JSONResponse({"error": f"Cromo no respondió: {exc}"}, status_code=502)

    return JSONResponse(_serializar_elemento_vivo(elemento))


def _serializar_pelo_excluido(excluido: Any) -> dict[str, Any]:
    return {
        "pelo_n_id": excluido.pelo_n_id,
        "numero_pelo": excluido.numero_pelo,
        "color": excluido.color,
        "cable_nombre": excluido.cable_nombre,
        "motivo": excluido.motivo,
        "excluido_por": excluido.excluido_por,
        "created_at": excluido.created_at.isoformat() if excluido.created_at else None,
        "origen": getattr(excluido, "origen", "MANUAL"),
    }


@app.get("/api/infra/cromo/servicios/{servicio_id}/odfs")
async def cromo_odfs_de_servicio_web(request: Request, servicio_id: int) -> JSONResponse:
    """ODFs de Cromo a las que llega un Servicio — el canal por defecto del Detalle de Servicio.

    SQL local sobre lo ya ingerido: **no toca Cromo en vivo**. La consulta en vivo es el segundo
    canal y ya existe como el botón "Resolver camino" del mismo panel; el tracking manual es el
    tercero, sólo para regularizar lo que Cromo no resuelve solo.

    Sistema distinto del endpoint legacy `GET /api/infra/servicios/{servicio_id}/odfs`, que deriva
    las ODFs del archivo de tracking subido a mano (27 Servicios de 14.147 en dev). Éste toma
    `servicio_id` como **PK interna**, igual que el resto de la familia `/cromo/servicios/...`;
    el legacy toma el ID de origen. No son intercambiables.
    """
    from core.services.cromo.verificador import odfs_por_servicio
    from db.session import AsyncSessionLocal

    username, _ = _require_auth(request)

    async with AsyncSessionLocal() as sesion:
        if not await _servicio_existe(sesion, servicio_id):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
        odfs = await odfs_por_servicio(sesion, servicio_id)

    logger.info(
        "action=cromo_odfs_de_servicio user=%s servicio_id=%s odfs=%d",
        username,
        servicio_id,
        len(odfs),
    )

    return JSONResponse(
        {
            "servicio_id": servicio_id,
            "total": len(odfs),
            "odfs": [
                {
                    "odf_n_id": odf.odf_n_id,
                    "nombre": odf.nombre,
                    "calle": odf.calle,
                    "altura": odf.altura,
                    "localidad": odf.localidad,
                    "conectores": odf.conectores,
                    "pelos": odf.pelos,
                    "origen": odf.origen,
                }
                for odf in odfs
            ],
        }
    )


@app.get("/api/infra/cromo/servicios/{servicio_id}/camino-optico/pelos")
async def cromo_camino_pelos_web(
    request: Request, servicio_id: int, priorizar_conector: bool = False
) -> JSONResponse:
    """Pelos de Cromo con los que se puede pedir el camino óptico de un Servicio.

    SQL local barato: **no toca Cromo**. Existe para que el Detalle de Servicio sepa si el botón
    de descarga va habilitado ANTES del click — de los 2.891 Servicios sin ODF, 2.228 (77%) no
    tienen ningún pelo y para ellos `/path` no tiene input posible.
    """
    from core.services.cromo import tracking_cache
    from core.services.cromo.camino_optico_service import (
        caminos_esperados,
        contar_semillas,
        listar_pelos_semilla,
        semillas_por_defecto,
    )
    from core.services.cromo.pelos_excluidos import listar_excluidos
    from db.session import AsyncSessionLocal

    _require_auth(request)

    async with AsyncSessionLocal() as sesion:
        if not await _servicio_existe(sesion, servicio_id):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
        semillas = await listar_pelos_semilla(
            sesion, servicio_id, priorizar_conector=priorizar_conector
        )
        frescura = await tracking_cache.frescura(sesion, [s.pelo_n_id for s in semillas])
        total_matcheados, total_con_conector = await contar_semillas(sesion, servicio_id)
        esperados = await caminos_esperados(sesion, servicio_id)
        excluidos = await listar_excluidos(sesion, servicio_id)

    preseleccionados = [s.pelo_n_id for s in semillas_por_defecto(semillas)]
    # Si ninguna semilla tiene conector, la ODF del Servicio todavía no fue relevada y la
    # preselección cae al comportamiento histórico (el primer pelo del ranking). La UI necesita
    # distinguir ese caso para explicar por qué el default no son las posiciones de la ODF.
    odf_relevada = any(s.tiene_conector_odf for s in semillas)

    pelos = []
    for semilla in semillas:
        dato = _serializar_pelo_semilla(semilla)
        generado_at = frescura.get(semilla.pelo_n_id)
        dato["tracking_en_cache"] = generado_at.isoformat() if generado_at else None
        pelos.append(dato)

    return JSONResponse(
        {
            "servicio_id": servicio_id,
            "total": len(semillas),
            "pelos": pelos,
            "preseleccionados": preseleccionados,
            "odf_relevada": odf_relevada,
            # `total` es la lista ya truncada; estos dos son el universo real. Sin ellos la UI no
            # puede distinguir "este Servicio tiene 20 pelos" de "tiene 227 y ves 20". El número de
            # servicio viaja en el `at.61` de TODOS los pelos del recorrido, así que el total es
            # grande por diseño y los pelos que el operador llama "del Servicio" son los que son
            # posición de ODF.
            "total_matcheados": total_matcheados,
            "total_con_posicion_odf": total_con_conector,
            # Regla de operaciones: tantos caminos (y `.txt`) como pelos del Servicio en un mismo
            # cable u ODF. Cuáles son esos caminos lo resuelve `/caminos`, que sí va a Cromo.
            "caminos_esperados": esperados,
            "excluidos": [_serializar_pelo_excluido(x) for x in excluidos],
        }
    )


@app.get("/api/infra/cromo/servicios/{servicio_id}/camino-optico/tracking.txt")
async def cromo_camino_tracking_txt_web(
    request: Request,
    servicio_id: int,
    pelo_n_id: Optional[int] = None,
    tramo: Optional[int] = Query(default=None, ge=1),
) -> Response:
    """Tracking óptico de un Servicio, generado desde Cromo, en el formato `.txt` legacy.

    `tramo` (opcional, con `pelo_n_id`) es el número de tramo que ya conoce el frontend desde
    `/caminos`: el archivo se llama `{at62} CROMO T{n} pelo {n_id}.txt`, igual que en Slack.

    `_require_auth` con el mismo criterio que `/api/infra/tracking/{ruta_id}/download`, que ya
    entrega el tracking completo de una ruta a cualquier usuario autenticado.

    `SIN_SEMILLA`/`SIN_CAMINO` responden **409** y no 200: no hay archivo que adjuntar, y un
    `.txt` que dice "no hay datos" es basura en la carpeta de Descargas de alguien.
    """
    from core.services.cromo.camino_optico_service import (
        ESTADO_SIN_SEMILLA,
        contar_semillas,
        listar_pelos_semilla,
        pelo_pertenece_al_servicio,
        semillas_por_defecto,
    )
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo import tracking_service
    from core.services.cromo.tracking_service import (
        TrackingNoDisponible,
        nombre_archivo_tramo,
        nombre_distinguible,
        obtener_tracking,
    )
    from db.session import AsyncSessionLocal

    usuario, _rol = _require_auth(request)

    try:
        async with AsyncSessionLocal() as sesion:
            if not await _servicio_existe(sesion, servicio_id):
                return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)

            # El universo real, sin el tope de `listar_pelos_semilla`. Es lo que decide tanto si
            # hay camino posible como si el nombre del archivo tiene que distinguir el pelo.
            total_pelos, _con_odf = await contar_semillas(sesion, servicio_id)
            if total_pelos == 0:
                return JSONResponse(
                    {
                        "error": (
                            "El Servicio no tiene ningún pelo en Cromo, así que no hay camino "
                            "que resolver."
                        ),
                        "estado": ESTADO_SIN_SEMILLA,
                    },
                    status_code=409,
                )

            if pelo_n_id is not None:
                # Pertenencia por consulta directa, NO contra la lista truncada de semillas: con
                # el tope de 20 sobre cientos de pelos matcheados, un pelo legítimo que el propio
                # selector acababa de ofrecer se rechazaba como ajeno (bug real, Servicio 93154).
                if not await pelo_pertenece_al_servicio(sesion, servicio_id, pelo_n_id):
                    return JSONResponse(
                        {"error": f"El pelo {pelo_n_id} no pertenece al Servicio {servicio_id}."},
                        status_code=400,
                    )
                elegido = pelo_n_id
            else:
                # Sin pedido explícito, la posición de ODF del Servicio: mismo criterio que el
                # default del selector, así que pedir el `.txt` "a secas" baja lo mismo que el
                # botón de la pantalla.
                semillas = await listar_pelos_semilla(
                    sesion, servicio_id, priorizar_conector=True
                )
                elegido = semillas_por_defecto(semillas)[0].pelo_n_id

            async with CromoClient(config=get_cromo_config()) as cliente:
                tracking = await obtener_tracking(
                    cliente, sesion, servicio_id=servicio_id, pelo_n_id=elegido
                )
            if not tracking.desde_cache:
                # Evidencia para el árbitro, sólo del camino recién traído de Cromo. Nunca cambia
                # la respuesta HTTP.
                try:
                    from core.services.cromo.arbitro.evidencia import (
                        entradas_de_trackings,
                        registrar_y_encolar,
                    )

                    await registrar_y_encolar(
                        sesion,
                        servicio_id,
                        entradas_de_trackings([tracking]),
                        # Un solo tracking de Cromo; TrackingGenerado no informa truncamiento.
                        completo=True,
                        fuente="WEB",
                    )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "action=arbitro_evidencia evento=enganche_fallido servicio_id=%s",
                        servicio_id,
                        exc_info=True,
                    )
            numero_servicio = (
                await tracking_service.numero_del_servicio(sesion, servicio_id)
                if tramo is not None and pelo_n_id is not None
                else None
            )
    except TrackingNoDisponible as exc:
        return JSONResponse({"error": exc.motivo, "estado": exc.estado}, status_code=409)
    except CromoClientError as exc:
        return JSONResponse({"error": f"Cromo no respondió: {exc}"}, status_code=502)

    # Con un solo pelo (el caso PON) el nombre queda idéntico al de siempre; con varios se
    # intercala el n_id, porque si no los N archivos del mismo Servicio se pisan entre sí en la
    # carpeta de Descargas y se pierde cuál es cuál.
    # El nombre de tramo lleva el número del Servicio en LAS-FOCAS, no el at.62 del pelo (que Cromo
    # a veces trae mal); el at.62 del nombre base queda sólo como respaldo.
    base_at62 = re.match(r"^(\d+) CROMO", tracking.nombre_archivo)
    if tramo is not None and pelo_n_id is not None:
        nombre = nombre_archivo_tramo(
            numero_servicio or (base_at62.group(1) if base_at62 else None), tramo, tracking.pelo_n_id
        )
    else:
        nombre = nombre_distinguible(
            tracking.nombre_archivo, tracking.pelo_n_id, distinguir=total_pelos > 1
        )
    logger.info(
        "action=cromo_camino_tracking user=%s servicio_id=%s pelo_n_id=%s desde_cache=%s duracion_ms=%s",
        usuario,
        servicio_id,
        tracking.pelo_n_id,
        tracking.desde_cache,
        tracking.duracion_ms,
    )
    return Response(
        content=tracking.contenido,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


async def _inconsistencias_del_servicio(sesion: Any, servicio_id: int) -> dict[str, int]:
    """Casos de inconsistencias de Cromo que tocan al Servicio, para el aviso del panel Camino.
    Es accesorio: si falla (tabla sin migrar, DB caída) los caminos se devuelven igual."""
    from core.services.cromo.inconsistencias_cromo import resumen_de_servicio

    try:
        return await resumen_de_servicio(sesion, servicio_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "action=cromo_camino_inconsistencias_error servicio_id=%s error=%s", servicio_id, exc
        )
        return {"cuarentena": 0, "en_revision": 0}


@app.get("/api/infra/cromo/servicios/{servicio_id}/camino-optico/caminos")
async def cromo_camino_caminos_web(request: Request, servicio_id: int) -> JSONResponse:
    """Los caminos del Servicio, separados en tramos y residuales.

    Es lo mismo que hace `@bot track` en Slack (`tracking_service.trackings_del_servicio`): recorre
    todas las semillas —posiciones de ODF primero, después los pelos de los cables— descartando
    las que ya recorrió un camino, sin cortar en los caminos esperados (tope de llamadas
    `CROMO_TRACKING_MAX_LLAMADAS`), y clasifica cada camino como TRAMO o RESIDUAL. **Va a Cromo**:
    4,6-14 s por camino en frío; deja cacheado cada tracking, así que bajar los `.txt` después es
    inmediato.

    Contrato: `tramos[{n, pelo_n_id, nombre_archivo, pelos_en_camino, desde_cache, extremos,
    odfs}]` (ya ordenados; `n` es el número de tramo del nombre del `.txt`), `residuales[...]` sin
    `n` ni `desde_cache` (no se descargan), `esperados_declarados` (o `null`, lo declara el
    operador), `completo`, `errores`, `no_cubiertos` (cantidad de semillas sin camino: fallaron o no
    se llegaron a pedir), `tope_llamadas` (se tocó `CROMO_TRACKING_MAX_LLAMADAS`) y `segmentos`
    (grupos de tramos que comparten cables). `odf_confirmadas` son las ODF que un admin confirmó
    para el Servicio (`odf_n_id`, `rol`, `odf_nombre`, `odf_tipo`, ...). `extremos` es `{a, b}`
    con `tipo`, `odf_n_id`, `odf_nombre`, `odf_clase`, `patchera_nombre`, `conector` e `id_cromo`.
    `odfs` son TODAS las ODF que toca el camino (extremos e intermedias) con `odf_n_id` de linaje,
    `odf_nombre` y `odf_clase`: la UI ofrece confirmar cualquiera, también las de un residual.

    Existe porque la preselección de `/pelos` es SQL local y sin ODF no puede saber qué pelos son
    del mismo hilo: el 94673 (sin ODF en sus extremos) preseleccionaba uno solo de sus 2 caminos.
    """
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo.servicio_odf_confirmacion import datos_de_odfs, n_ids_de_odfs
    from core.services.cromo.tracking_service import trackings_del_servicio
    from db.session import AsyncSessionLocal

    usuario, _rol = _require_auth(request)
    try:
        async with AsyncSessionLocal() as sesion:
            if not await _servicio_existe(sesion, servicio_id):
                return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
            async with CromoClient(config=get_cromo_config()) as cliente:
                resultado = await trackings_del_servicio(cliente, sesion, servicio_id)
            # Los caminos pueden traer el id de versión de la ODF: se expone siempre el n_id. Entran
            # las de los extremos y las intermedias (`odfs`), de tramos y de residuales.
            ids_odf: list[int] = []
            for t in (*resultado.tramos, *resultado.residuales):
                if not t.extremos:
                    continue
                ids_odf.extend(e.odf_id for e in t.extremos.extremos if e.odf_id is not None)
                ids_odf.extend(t.extremos.odfs)
            ids_odf = list(dict.fromkeys(ids_odf))
            n_ids_odf = await n_ids_de_odfs(sesion, ids_odf)
            # Nombre y clase de cada ODF, también de las intermedias: una sola query.
            datos_odf = await datos_de_odfs(
                sesion, list(dict.fromkeys(n_ids_odf.get(i, i) for i in ids_odf))
            )
            inconsistencias = await _inconsistencias_del_servicio(sesion, servicio_id)
    except CromoClientError as exc:
        return JSONResponse({"error": f"Cromo no respondió: {exc}"}, status_code=502)

    logger.info(
        "action=cromo_camino_caminos user=%s servicio_id=%s tramos=%s residuales=%s completo=%s",
        usuario,
        servicio_id,
        len(resultado.tramos),
        len(resultado.residuales),
        resultado.completo,
    )

    def _extremo(e: Any) -> Optional[dict[str, Any]]:
        if e is None:
            return None
        return {
            "tipo": e.tipo,
            "id_cromo": e.id_cromo,
            "odf_n_id": n_ids_odf.get(e.odf_id, e.odf_id) if e.odf_id is not None else None,
            "odf_nombre": e.odf_nombre,
            "odf_clase": e.odf_clase,
            "patchera_nombre": e.patchera_nombre,
            "conector": e.conector_numero,
        }

    def _odfs(resumen: Any) -> list[dict[str, Any]]:
        """Todas las ODF del camino, por n_id y sin repetir. Si la ODF no está ingerida, el nombre y
        la clase salen del extremo del payload (cuando es uno)."""
        if resumen is None:
            return []
        del_payload = {
            n_ids_odf.get(e.odf_id, e.odf_id): (e.odf_nombre, e.odf_clase)
            for e in resumen.extremos
            if e.odf_id is not None
        }
        salida: dict[int, dict[str, Any]] = {}
        for odf_id in (*resumen.odfs, *del_payload):
            n_id = n_ids_odf.get(odf_id, odf_id)
            if n_id in salida:
                continue
            nombre, clase = datos_odf.get(n_id) or del_payload.get(n_id) or (None, None)
            salida[n_id] = {"odf_n_id": n_id, "odf_nombre": nombre, "odf_clase": clase}
        return list(salida.values())

    def _camino(t: Any) -> dict[str, Any]:
        resumen = t.extremos
        return {
            "pelo_n_id": t.pelo_n_id,
            "nombre_archivo": t.nombre_archivo,
            "pelos_en_camino": len(t.pelos_camino),
            "extremos": {
                "a": _extremo(resumen.inicio) if resumen else None,
                "b": _extremo(resumen.fin) if resumen else None,
            },
            "odfs": _odfs(resumen),
        }

    tramos = [
        {"n": n, **_camino(t), "desde_cache": t.desde_cache}
        for n, t in enumerate(resultado.tramos, start=1)
    ]
    return JSONResponse(
        {
            "tramos": tramos,
            "residuales": [_camino(t) for t in resultado.residuales],
            "esperados_declarados": resultado.esperados_declarados,
            "odf_confirmadas": resultado.odf_confirmadas,
            "completo": resultado.completo,
            "errores": resultado.errores,
            "no_cubiertos": len(resultado.no_cubiertos),
            "tope_llamadas": resultado.tope_llamadas,
            "segmentos": resultado.segmentos,
            "inconsistencias": inconsistencias,
        }
    )


class HuerfanosRevisarRequestModel(BaseModel):
    """Payload para normalizar o descartar filas de la auditoría de huérfanos, en lote."""

    ids: list[int] = Field(min_length=1, max_length=500, description="Ids de cromo_auditoria_huerfanos")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class HuerfanosAuditoriaGlobalRequestModel(BaseModel):
    """Payload para lanzar la auditoría global de huérfanos (corrida en el cromo_worker)."""

    max_servicios: int | None = Field(
        default=None, ge=1, le=2000, description="Tope de Servicios; default CROMO_AUDITORIA_MAX_SERVICIOS"
    )
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.get("/api/admin/infra/huerfanos")
async def huerfanos_listar_web(
    request: Request,
    servicio_id: Optional[int] = None,
    causa: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> JSONResponse:
    """Viewer de huérfanos: pelos de caminos RESIDUALES con causa sugerida, evidencia y estado.

    Filtros `servicio_id` (PK de `app.servicios`), `causa` y `estado`. `conteos_por_causa` sale con
    los filtros de servicio y estado, antes del de causa (chips). Admin.
    """
    from core.services.cromo.auditoria_huerfanos import CAUSAS, ESTADOS, listar_huerfanos
    from db.session import AsyncSessionLocal

    _require_admin(request)
    if causa is not None and causa not in CAUSAS:
        return JSONResponse({"error": f"causa inválida. Valores: {list(CAUSAS)}"}, status_code=400)
    if estado is not None and estado not in ESTADOS:
        return JSONResponse({"error": f"estado inválido. Valores: {list(ESTADOS)}"}, status_code=400)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    async with AsyncSessionLocal() as sesion:
        pagina = await listar_huerfanos(
            sesion, servicio_id=servicio_id, causa=causa, estado=estado, limit=limit, offset=offset
        )
    return JSONResponse(pagina)


@app.post("/api/admin/infra/huerfanos/normalizar")
async def huerfanos_normalizar_web(request: Request, body: HuerfanosRevisarRequestModel) -> JSONResponse:
    """Normaliza en lote: excluye del Servicio el pelo de cada fila (`origen=AUDITORIA`).

    Qué se puede normalizar lo decide el servidor con la fila guardada: sólo PENDIENTE, no
    protegida y con causa habilitada (hoy sólo `CABLE_DESUSO`). Lo demás vuelve en `rechazados`
    con su motivo. Reversible con "Restaurar" del panel del camino. Admin + CSRF.
    """
    from core.services.cromo.auditoria_huerfanos import normalizar
    from db.session import AsyncSessionLocal

    username = _require_admin(request)
    if not _validar_csrf(request, body.csrf_token, "cromo_huerfanos_normalizar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        resultado = await normalizar(sesion, body.ids, usuario=username)
    return JSONResponse(
        {"ok": True, "aplicados": resultado.aplicados, "rechazados": resultado.rechazados}
    )


@app.post("/api/admin/infra/huerfanos/descartar")
async def huerfanos_descartar_web(request: Request, body: HuerfanosRevisarRequestModel) -> JSONResponse:
    """Marca DESCARTADO las filas PENDIENTE elegidas (revisadas, no son huérfanos). Admin + CSRF."""
    from core.services.cromo.auditoria_huerfanos import descartar
    from db.session import AsyncSessionLocal

    username = _require_admin(request)
    if not _validar_csrf(request, body.csrf_token, "cromo_huerfanos_descartar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        resultado = await descartar(sesion, body.ids, usuario=username)
    return JSONResponse(
        {"ok": True, "aplicados": resultado.aplicados, "rechazados": resultado.rechazados}
    )


@app.get("/api/admin/infra/huerfanos/auditoria-global")
async def huerfanos_auditoria_global_estado_web(request: Request) -> JSONResponse:
    """Última auditoría global (o `null`), para que el Viewer muestre su estado al abrir. Admin."""
    from core.services.cromo.auditoria_huerfanos_global import (
        max_servicios_configurado,
        ultima_auditoria,
    )
    from db.session import AsyncSessionLocal

    _require_admin(request)
    async with AsyncSessionLocal() as sesion:
        corrida = await ultima_auditoria(sesion)
    return JSONResponse(
        {
            "corrida": _serializar_cromo_corrida(corrida) if corrida is not None else None,
            "max_servicios_default": max_servicios_configurado(),
        }
    )


@app.post("/api/admin/infra/huerfanos/auditoria-global")
async def huerfanos_auditoria_global_iniciar_web(
    request: Request, body: HuerfanosAuditoriaGlobalRequestModel
) -> JSONResponse:
    """Lanza la auditoría global: corrida sintética que ejecuta el `cromo_worker` (tiene las
    credenciales de Cromo). Recorre los Servicios Activos con más pelos hasta el tope. El progreso
    se sigue con el SSE de corridas (`/api/admin/ingesta/cromo/corridas/{id}/stream`).
    Una sola a la vez: si hay otra EN_CURSO devuelve 409 con su id. Admin + CSRF.
    """
    from core.services.cromo.auditoria_huerfanos_global import (
        iniciar_si_no_hay_otra,
        max_servicios_configurado,
    )
    from db.session import AsyncSessionLocal

    username = _require_admin(request)
    if not _validar_csrf(request, body.csrf_token, "cromo_huerfanos_auditoria_global", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    tope = body.max_servicios or max_servicios_configurado()
    async with AsyncSessionLocal() as sesion:
        # Chequeo + alta bajo advisory lock: dos POST simultáneos no lanzan dos auditorías.
        corrida, en_curso = await iniciar_si_no_hay_otra(
            sesion, usuario=username, max_servicios=tope
        )
        if corrida is None:
            return JSONResponse(
                {"error": "Ya hay una auditoría global en curso.", "corrida_id": en_curso},
                status_code=409,
            )
        corrida_id = corrida.id

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                _CROMO_WORKER_RUN_URL, json={"corrida_id": corrida_id, "usuario": username}
            )
            response.raise_for_status()
    except Exception as exc:
        logger.error("action=cromo_huerfanos_auditoria_global_error corrida_id=%s error=%s", corrida_id, exc)
        await _marcar_corrida_fallida(
            corrida_id, f"No se pudo delegar la auditoría al worker de Cromo: {exc}"
        )
        return JSONResponse(
            {"error": "El worker de Cromo no está disponible. Intentá nuevamente en unos segundos."},
            status_code=503,
        )
    logger.info(
        "action=cromo_huerfanos_auditoria_global user=%s corrida_id=%s max_servicios=%s",
        username,
        corrida_id,
        tope,
    )
    return JSONResponse({"corrida_id": corrida_id, "max_servicios": tope}, status_code=202)


class InconsistenciasEstadoRequestModel(BaseModel):
    """Payload para cambiar el estado de casos de inconsistencias, en lote."""

    ids: list[int] = Field(min_length=1, max_length=500, description="Ids de cromo_inconsistencia")
    estado: str = Field(description="CUARENTENA | ACEPTADA | REPORTADA | PENDIENTE (liberar)")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class InconsistenciasDeteccionRequestModel(BaseModel):
    """Payload para lanzar la detección manual de inconsistencias."""

    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.get("/api/admin/infra/inconsistencias-cromo")
async def inconsistencias_cromo_listar_web(
    request: Request,
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    revision: Optional[str] = None,
    localidad: Optional[str] = None,
    servicio: Optional[str] = None,
    servicio_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> JSONResponse:
    """Viewer de inconsistencias de Cromo: casos detectados (isla de fusiones, cable sin extremo,
    elemento isla) con revisión, estado y evidencia. Filtros `tipo`, `estado`, `revision`,
    `localidad` (ILIKE), `servicio` (número) y `servicio_id` (PK de `app.servicios`).
    `conteos_por_tipo` sale con todos los filtros salvo el de tipo (chips). Admin."""
    from fastapi.encoders import jsonable_encoder

    from core.services.cromo.inconsistencias_cromo import (
        ESTADOS,
        REVISIONES,
        TIPOS,
        listar,
    )
    from db.session import AsyncSessionLocal

    _require_admin(request)
    if tipo is not None and tipo not in TIPOS:
        return JSONResponse({"error": f"tipo inválido. Valores: {list(TIPOS)}"}, status_code=400)
    if estado is not None and estado not in ESTADOS:
        return JSONResponse({"error": f"estado inválido. Valores: {list(ESTADOS)}"}, status_code=400)
    if revision is not None and revision not in REVISIONES:
        return JSONResponse(
            {"error": f"revision inválida. Valores: {list(REVISIONES)}"}, status_code=400
        )
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    async with AsyncSessionLocal() as sesion:
        pagina = await listar(
            sesion,
            tipo=tipo,
            estado=estado,
            revision=revision,
            localidad=localidad or None,
            servicio=servicio or None,
            servicio_id=servicio_id,
            por_pagina=limit,
            desplazamiento=offset,
        )
    return JSONResponse(jsonable_encoder(pagina))


@app.get("/api/admin/infra/inconsistencias-cromo/exportar.xlsx")
async def inconsistencias_cromo_exportar_web(
    request: Request,
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    revision: Optional[str] = None,
    localidad: Optional[str] = None,
    servicio: Optional[str] = None,
    servicio_id: Optional[int] = None,
) -> Response:
    """XLSX "para corregir en Cromo": una hoja por localidad, con tipo, revisión, estado, objeto,
    ID Cromo, qué falta, servicios afectados y fechas. Mismos filtros que el listado; sin `estado`
    exporta sólo lo accionable (PENDIENTE, CUARENTENA, REPORTADA). Admin."""
    from core.services.cromo import inconsistencias_reporte as reporte
    from core.services.cromo.inconsistencias_cromo import ESTADOS, REVISIONES, TIPOS
    from db.session import AsyncSessionLocal

    username = _require_admin(request)
    if tipo is not None and tipo not in TIPOS:
        return JSONResponse({"error": f"tipo inválido. Valores: {list(TIPOS)}"}, status_code=400)
    if estado is not None and estado not in ESTADOS:
        return JSONResponse({"error": f"estado inválido. Valores: {list(ESTADOS)}"}, status_code=400)
    if revision is not None and revision not in REVISIONES:
        return JSONResponse(
            {"error": f"revision inválida. Valores: {list(REVISIONES)}"}, status_code=400
        )
    try:
        async with AsyncSessionLocal() as sesion:
            filas = await reporte.filas_reporte(
                sesion,
                tipo=tipo,
                estado=estado,
                revision=revision,
                localidad=localidad or None,
                servicio=servicio or None,
                servicio_id=servicio_id,
            )
        contenido = await asyncio.to_thread(reporte.generar_xlsx, filas)
    except Exception as exc:
        logger.exception("action=inconsistencias_cromo_exportar_error error=%s", exc)
        return JSONResponse({"error": "No se pudo generar el reporte"}, status_code=500)
    logger.info("action=inconsistencias_cromo_exportar user=%s filas=%d", username, len(filas))
    sello = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="inconsistencias_cromo_{sello}.xlsx"'},
    )


class InconsistenciasAvisoSlackRequestModel(BaseModel):
    """Payload para configurar el aviso de casos nuevos a Slack."""

    slack_channels: str = Field(default="", description="Canales (#nombre o ID C/G/D...) separados por coma")
    activo: bool = Field(default=False, description="Si el aviso a Slack está encendido")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.get("/api/admin/infra/inconsistencias-cromo/aviso-slack")
async def inconsistencias_cromo_aviso_slack_get_web(request: Request) -> JSONResponse:
    """Config del aviso de casos nuevos a Slack (fila "Cromo Inconsistencias"). Admin."""
    from core.services.cromo.inconsistencias_reporte import leer_config_aviso
    from db.session import AsyncSessionLocal

    _require_admin(request)
    async with AsyncSessionLocal() as sesion:
        return JSONResponse(await leer_config_aviso(sesion))


@app.post("/api/admin/infra/inconsistencias-cromo/aviso-slack")
async def inconsistencias_cromo_aviso_slack_post_web(
    request: Request, body: InconsistenciasAvisoSlackRequestModel
) -> JSONResponse:
    """Guarda canales y activación del aviso a Slack. Mismas reglas de formato de canal que el
    resto de los servicios de Slack. Admin + CSRF."""
    from core.services.cromo.inconsistencias_reporte import guardar_config_aviso, normalizar_canales
    from db.session import AsyncSessionLocal

    username = _require_admin(request)
    if not _validar_csrf(request, body.csrf_token, "cromo_inconsistencias_aviso_slack", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    canales = normalizar_canales(body.slack_channels)
    if len(canales) > 512:
        return JSONResponse({"error": "Los canales no deben superar 512 caracteres"}, status_code=400)
    if any(not _es_destino_slack_valido(c) for c in canales.split(",") if c):
        return JSONResponse(
            {"error": "Cada destino debe ser un nombre de canal con # o un ID de Slack tipo C/G/D..."},
            status_code=400,
        )
    if body.activo and not canales:
        return JSONResponse({"error": "Para activar el aviso hay que indicar al menos un canal"}, status_code=400)
    async with AsyncSessionLocal() as sesion:
        await guardar_config_aviso(sesion, canales, body.activo)
        await sesion.commit()
    logger.info(
        "action=cromo_inconsistencias_aviso_slack user=%s activo=%s canales=%s", username, body.activo, canales
    )
    return JSONResponse({"ok": True, "slack_channels": canales, "activo": body.activo})


@app.post("/api/admin/infra/inconsistencias-cromo/estado")
async def inconsistencias_cromo_estado_web(
    request: Request, body: InconsistenciasEstadoRequestModel
) -> JSONResponse:
    """Cambia el estado de los casos elegidos (cuarentena, aceptar, reportar o liberar a
    PENDIENTE). Las transiciones válidas las decide el servidor (`cambiar_estado`): lo que no se
    puede vuelve en `rechazados` con su motivo. Admin + CSRF."""
    from core.services.cromo.inconsistencias_cromo import ESTADOS_DESTINO_MANUAL, cambiar_estado
    from db.session import AsyncSessionLocal

    username = _require_admin(request)
    if not _validar_csrf(request, body.csrf_token, "cromo_inconsistencias_estado", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    if body.estado not in ESTADOS_DESTINO_MANUAL:
        return JSONResponse(
            {"error": f"estado inválido. Valores: {sorted(ESTADOS_DESTINO_MANUAL)}"}, status_code=400
        )
    async with AsyncSessionLocal() as sesion:
        resultado = await cambiar_estado(sesion, body.ids, body.estado, username)
        await sesion.commit()
    if resultado["actualizados"]:
        await _encolar_arbitro("TODO", [], f"inconsistencias-estado estado={body.estado}")
    logger.info(
        "action=cromo_inconsistencias_estado user=%s estado=%s aplicados=%s rechazados=%s",
        username,
        body.estado,
        len(resultado["actualizados"]),
        len(resultado["rechazados"]),
    )
    return JSONResponse(
        {"ok": True, "aplicados": resultado["actualizados"], "rechazados": resultado["rechazados"]}
    )


@app.get("/api/admin/infra/inconsistencias-cromo/deteccion")
async def inconsistencias_cromo_deteccion_estado_web(request: Request) -> JSONResponse:
    """Última corrida del detector (o `null`), para que el Viewer muestre su estado al abrir. Admin."""
    from core.services.cromo.inconsistencias_cromo import ultima_deteccion
    from db.session import AsyncSessionLocal

    _require_admin(request)
    async with AsyncSessionLocal() as sesion:
        corrida = await ultima_deteccion(sesion)
    return JSONResponse(
        {"corrida": _serializar_cromo_corrida(corrida) if corrida is not None else None}
    )


@app.post("/api/admin/infra/inconsistencias-cromo/deteccion")
async def inconsistencias_cromo_deteccion_iniciar_web(
    request: Request, body: InconsistenciasDeteccionRequestModel
) -> JSONResponse:
    """Lanza el detector a mano: corrida sintética que ejecuta el `cromo_worker` (tiene las
    credenciales de Cromo para confirmar cables en vivo). El progreso se sigue con el SSE de
    corridas. Una sola a la vez: si hay otra detección o una ingesta EN_CURSO devuelve 409 con su
    id. Admin + CSRF."""
    from core.services.cromo.inconsistencias_cromo import iniciar_si_no_hay_otra
    from db.session import AsyncSessionLocal

    username = _require_admin(request)
    if not _validar_csrf(request, body.csrf_token, "cromo_inconsistencias_deteccion", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        corrida, en_curso = await iniciar_si_no_hay_otra(sesion, usuario=username, origen="MANUAL")
        if corrida is None:
            return JSONResponse(
                {"error": "Hay una detección o una ingesta en curso.", "corrida_id": en_curso},
                status_code=409,
            )
        corrida_id = corrida.id

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                _CROMO_WORKER_RUN_URL, json={"corrida_id": corrida_id, "usuario": username}
            )
            response.raise_for_status()
    except Exception as exc:
        logger.error("action=cromo_inconsistencias_deteccion_error corrida_id=%s error=%s", corrida_id, exc)
        await _marcar_corrida_fallida(
            corrida_id, f"No se pudo delegar la detección al worker de Cromo: {exc}"
        )
        return JSONResponse(
            {"error": "El worker de Cromo no está disponible. Intentá nuevamente en unos segundos."},
            status_code=503,
        )
    logger.info("action=cromo_inconsistencias_deteccion user=%s corrida_id=%s", username, corrida_id)
    return JSONResponse({"corrida_id": corrida_id}, status_code=202)


class ArbitroPropuestasRequestModel(BaseModel):
    """Payload para decidir propuestas del árbitro de Cromo (aplicar, rechazar, revertir), en lote."""

    ids: list[int] = Field(min_length=1, max_length=500, description="Ids de cromo_propuesta")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class ArbitroReglaRequestModel(BaseModel):
    """Payload para cambiar la configuración de una regla del árbitro."""

    codigo: str
    modo: str = Field(description="APAGADA | SOMBRA | AUTO")
    umbral: int
    presupuesto_por_corrida: int
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class ArbitroNormalizarRequestModel(BaseModel):
    """Payload del análisis retroactivo: reglas a correr (None = todas)."""

    reglas: Optional[list[str]] = None
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.get("/api/admin/infra/arbitro-cromo/propuestas")
async def arbitro_cromo_propuestas_web(
    request: Request,
    regla: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    """Lista paginada de propuestas del árbitro de Cromo, filtrable por regla y estado. Admin."""
    from fastapi.encoders import jsonable_encoder
    from core.services.cromo.arbitro import motor
    from db.session import AsyncSessionLocal

    _require_admin(request)
    async with AsyncSessionLocal() as sesion:
        resultado = await motor.listar_propuestas(
            sesion, regla=regla, estado=estado, limit=limit, offset=offset
        )
    return JSONResponse(jsonable_encoder(resultado))


async def _encolar_arbitro_tras_decision(sesion, ids: Sequence[int], motivo: str) -> None:
    """Encola una evaluación VIEWER por tipo de objeto tocado. Best-effort: nunca altera la respuesta."""
    try:
        from core.services.cromo.arbitro import evaluaciones

        alcances = await evaluaciones.alcances_de_propuestas(sesion, ids)
        for tipo, objeto_ids in alcances.items():
            await _encolar_arbitro(tipo, objeto_ids, motivo)
    except Exception:  # noqa: BLE001
        logger.warning("action=arbitro_encolar_viewer result=fail motivo=%s", motivo, exc_info=True)


@app.post("/api/admin/infra/arbitro-cromo/propuestas/aplicar")
async def arbitro_cromo_aplicar_web(
    request: Request, body: ArbitroPropuestasRequestModel
) -> JSONResponse:
    """Aplica propuestas a mano. Lo que no se puede vuelve en `rechazados` con su motivo. Admin + CSRF."""
    from core.services.cromo.arbitro import motor
    from db.session import AsyncSessionLocal

    username = _require_admin(request)
    if not _validar_csrf(request, body.csrf_token, "arbitro_cromo_propuestas", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        resultado = await motor.aplicar_manual(sesion, body.ids, username)
        await sesion.commit()
        if resultado["aplicados"]:
            await _encolar_arbitro_tras_decision(sesion, resultado["aplicados"], f"arbitro-aplicar user={username}")
    return JSONResponse({"ok": True, **resultado})


@app.post("/api/admin/infra/arbitro-cromo/propuestas/rechazar")
async def arbitro_cromo_rechazar_web(
    request: Request, body: ArbitroPropuestasRequestModel
) -> JSONResponse:
    """Rechaza propuestas (la decisión humana bloquea re-proponer con la misma evidencia). Admin + CSRF."""
    from core.services.cromo.arbitro import motor
    from db.session import AsyncSessionLocal

    username = _require_admin(request)
    if not _validar_csrf(request, body.csrf_token, "arbitro_cromo_propuestas", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        resultado = await motor.rechazar(sesion, body.ids, username)
        await sesion.commit()
    return JSONResponse({"ok": True, **resultado})


@app.post("/api/admin/infra/arbitro-cromo/propuestas/revertir")
async def arbitro_cromo_revertir_web(
    request: Request, body: ArbitroPropuestasRequestModel
) -> JSONResponse:
    """Revierte propuestas en observación o aplicadas. Lo que no se puede vuelve en `omitidos`. Admin + CSRF."""
    from core.services.cromo.arbitro import motor
    from db.session import AsyncSessionLocal

    username = _require_admin(request)
    if not _validar_csrf(request, body.csrf_token, "arbitro_cromo_propuestas", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        resultado = await motor.revertir_manual(sesion, body.ids, username)
        await sesion.commit()
        if resultado["revertidos"]:
            await _encolar_arbitro_tras_decision(sesion, resultado["revertidos"], f"arbitro-revertir user={username}")
    return JSONResponse({"ok": True, **resultado})


@app.get("/api/admin/infra/arbitro-cromo/reglas")
async def arbitro_cromo_reglas_web(request: Request) -> JSONResponse:
    """Configuración de cada regla con su precisión histórica y si conviene pasarla a AUTO. Admin."""
    from fastapi.encoders import jsonable_encoder
    from core.services.cromo.arbitro import motor
    from db.session import AsyncSessionLocal

    _require_admin(request)
    async with AsyncSessionLocal() as sesion:
        reglas = await motor.precision_por_regla(sesion)
    return JSONResponse({"reglas": jsonable_encoder(reglas)})


@app.post("/api/admin/infra/arbitro-cromo/reglas")
async def arbitro_cromo_reglas_actualizar_web(
    request: Request, body: ArbitroReglaRequestModel
) -> JSONResponse:
    """Cambia modo, umbral y presupuesto de una regla. 422 ante valores inválidos. Admin + CSRF."""
    from core.services.cromo.arbitro import motor
    from db.session import AsyncSessionLocal

    username = _require_admin(request)
    if not _validar_csrf(request, body.csrf_token, "arbitro_cromo_reglas", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    async with AsyncSessionLocal() as sesion:
        try:
            await motor.actualizar_regla(
                sesion,
                body.codigo,
                modo=body.modo,
                umbral=body.umbral,
                presupuesto_por_corrida=body.presupuesto_por_corrida,
                usuario=username,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        await sesion.commit()
    return JSONResponse({"ok": True})


@app.post("/api/admin/infra/arbitro-cromo/normalizar")
async def arbitro_cromo_normalizar_web(
    request: Request, body: ArbitroNormalizarRequestModel
) -> JSONResponse:
    """Lanza el análisis retroactivo (alcance TODO) en el worker. 409 si ya hay otro en curso
    (EN_COLA/EN_CURSO de las últimas 6 h); 422 si alguna regla no existe. Admin + CSRF."""
    from core.services.cromo.arbitro import evaluaciones
    from core.services.cromo.arbitro.cola import encolar_evaluacion
    from core.services.cromo.arbitro.reglas import REGLAS
    from core.services.cromo.arbitro.senales import Alcance
    from db.session import AsyncSessionLocal

    username = _require_admin(request)
    if not _validar_csrf(request, body.csrf_token, "arbitro_cromo_normalizar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    reglas = body.reglas or None  # lista vacía = todas las reglas
    desconocidas = sorted(set(reglas or []) - {r.codigo for r in REGLAS})
    if desconocidas:
        return JSONResponse({"error": f"Reglas inexistentes: {desconocidas}"}, status_code=422)
    async with AsyncSessionLocal() as sesion:
        evaluacion_id, en_curso = await evaluaciones.crear_evaluacion_normalizador(
            sesion, username, reglas
        )
        if evaluacion_id is None:
            return JSONResponse(
                {"error": "Ya hay un análisis retroactivo en curso.", "evaluacion_id": en_curso},
                status_code=409,
            )
        await sesion.commit()
    encolada = await encolar_evaluacion(
        Alcance("TODO"), "NORMALIZADOR", motivo=f"manual:{username}",
        evaluacion_id=evaluacion_id, reglas=reglas,
    )
    if not encolada:
        # Sin cola no hay worker que la tome: se cierra la fila para no bloquear con 409 durante 6 h.
        async with AsyncSessionLocal() as sesion:
            await evaluaciones.marcar_fallida(sesion, evaluacion_id, evaluaciones.ERROR_NO_ENCOLADA)
            await sesion.commit()
        return JSONResponse(
            {"error": "No se pudo encolar el análisis retroactivo. Intentá nuevamente.", "evaluacion_id": evaluacion_id},
            status_code=503,
        )
    logger.info("action=arbitro_cromo_normalizar user=%s evaluacion_id=%s", username, evaluacion_id)
    return JSONResponse({"evaluacion_id": evaluacion_id}, status_code=202)


@app.get("/api/admin/infra/arbitro-cromo/evaluaciones")
async def arbitro_cromo_evaluaciones_web(
    request: Request, limit: int = Query(10, ge=1, le=50)
) -> JSONResponse:
    """Últimas evaluaciones del árbitro y el id de la que está en curso (o `null`). Admin."""
    from fastapi.encoders import jsonable_encoder
    from core.services.cromo.arbitro import evaluaciones
    from db.session import AsyncSessionLocal

    _require_admin(request)
    async with AsyncSessionLocal() as sesion:
        resultado = await evaluaciones.listar_evaluaciones(sesion, limit)
    return JSONResponse(jsonable_encoder(resultado))


def _serializar_cable_validacion(cable: Any) -> dict[str, Any]:
    return {
        "n_id": cable.n_id,
        "nombre": cable.nombre,
        "capacidad": cable.capacidad,
        "extremo_a_n_id": cable.extremo_a_n_id,
        "extremo_a_nombre": cable.extremo_a_nombre,
        "extremo_b_n_id": cable.extremo_b_n_id,
        "extremo_b_nombre": cable.extremo_b_nombre,
    }


def _serializar_tubo_validacion(tubo: Any) -> dict[str, Any]:
    return {"n_id": tubo.n_id, "cable_n_id": tubo.cable_n_id, "orden": tubo.orden, "nombre_color": tubo.nombre_color}


def _serializar_pelo_validacion(pelo: Any) -> dict[str, Any]:
    return {
        "n_id": pelo.n_id,
        "tubo_n_id": pelo.tubo_n_id,
        "cable_n_id": pelo.cable_n_id,
        "numero_pelo": pelo.numero_pelo,
        "color": pelo.color,
        "servicio_raw": pelo.servicio_raw,
        "servicio_numero": pelo.servicio_numero,
    }


def _serializar_fusion_validacion(fusion: Any) -> dict[str, Any]:
    return {
        "n_id": fusion.n_id,
        "botella_n_id": fusion.botella_n_id,
        "nombre_par": fusion.nombre_par,
        "pelo_a_n_id": fusion.pelo_a_n_id,
        "pelo_b_n_id": fusion.pelo_b_n_id,
    }


def _serializar_validacion_cromo(resultado: Any) -> dict[str, Any]:
    return {
        "n_id": resultado.n_id,
        "clase": resultado.clase,
        "tipo_objeto": resultado.tipo_objeto,
        "nombre": resultado.nombre,
        "notas": resultado.notas,
        "latitud": resultado.latitud,
        "longitud": resultado.longitud,
        "codigo_modelo": resultado.codigo_modelo,
        "id_legacy": resultado.id_legacy,
        "cables": [_serializar_cable_validacion(c) for c in resultado.cables],
        "tubos": [_serializar_tubo_validacion(t) for t in resultado.tubos],
        "pelos": [_serializar_pelo_validacion(p) for p in resultado.pelos],
        "fusiones": [_serializar_fusion_validacion(f) for f in resultado.fusiones],
        "errores_parseo": [{"n_id": e.n_id, "clase": e.clase, "motivo": e.motivo} for e in resultado.errores_parseo],
        "payload_raw": resultado.payload_raw,
    }


@app.get("/api/infra/cromo/validar/{n_id}")
async def cromo_validar_datos_web(request: Request, n_id: int) -> JSONResponse:
    """"Validar datos DB Cromo" (Tool Kit) — consulta un n_id en vivo contra Cromo y le aplica el
    MISMO parseo que usa la ingesta (`parse_objeto`/`parse_arbol_botella`/`extraer_tubos_y_pelos`):
    árbol completo de cables/tubos/pelos/fusiones, no sólo los atributos planos del objeto. Distinto
    de `GET /api/infra/cromo/elementos/{n_id}/vivo` (ese es plano, sin árbol) y de
    `VerificadorCromoView.vue` (que consulta servicios ya matcheados contra el inventario YA
    ingerido) — herramienta separada, confirmada explícitamente con el usuario. Sin sesión de DB en
    absoluto: cero acceso a la base de datos local, ni siquiera en lectura. Los servicios de cada
    pelo se devuelven crudos (`servicio_raw`/`servicio_numero`), nunca matcheados contra
    `app.servicios`. Sólo lectura, cualquier usuario autenticado."""
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo.validador_datos_service import validar_elemento_cromo
    from core.services.cromo.verificador import ObjetoNoEncontrado

    _require_auth(request)
    try:
        async with CromoClient(config=get_cromo_config()) as cliente:
            resultado = await validar_elemento_cromo(cliente, n_id)
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except CromoClientError as exc:
        return JSONResponse({"error": f"Cromo no respondió: {exc}"}, status_code=502)

    return JSONResponse(_serializar_validacion_cromo(resultado))


def _serializar_cable_detectado(cable: Any) -> dict[str, Any]:
    return {
        "n_id": cable.n_id,
        "nombre": cable.nombre,
        "extremo_a_n_id": cable.extremo_a_n_id,
        "extremo_b_n_id": cable.extremo_b_n_id,
        "estado_local": cable.estado_local,
    }


@app.get("/api/infra/cromo/botellas/{n_id}/cables-detectados")
async def cromo_botella_cables_detectados_web(request: Request, n_id: int) -> JSONResponse:
    """Verificador Cromo — "Cables detectados en Cromo": consulta la botella en vivo (siguiendo
    `hist[]`/`next_id` si el `n_id` quedó vacío por un caso de "ID dual") y compara sus cables
    contra `app.cromo_cables` local. Sólo lectura, nunca persiste — mismo criterio que el resto de
    `/api/infra/cromo/*`, cualquier usuario autenticado. El botón de escritura correspondiente es
    `POST /api/infra/botellas/{n_id}/repoblar-cables` (sólo admin)."""
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo.repoblacion_service import detectar_cables_faltantes
    from core.services.cromo.verificador import ObjetoNoEncontrado
    from db.session import AsyncSessionLocal

    _require_auth(request)
    try:
        async with AsyncSessionLocal() as sesion, CromoClient(config=get_cromo_config()) as cliente:
            resultado = await detectar_cables_faltantes(cliente, sesion, n_id)
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except CromoClientError as exc:
        return JSONResponse({"error": f"Cromo no respondió: {exc}"}, status_code=502)

    return JSONResponse(
        {
            "botella_n_id": resultado.botella_n_id,
            "ids_cadena": resultado.ids_cadena,
            "cables": [_serializar_cable_detectado(c) for c in resultado.cables],
        }
    )


class BotellaRepoblarCablesRequestModel(BaseModel):
    """Payload para repoblar los cables detectados en Cromo hacia la base local de una Botella."""

    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.post("/api/infra/botellas/{n_id}/repoblar-cables")
async def botella_repoblar_cables_web(request: Request, n_id: int, body: BotellaRepoblarCablesRequestModel) -> JSONResponse:
    """Verificador Cromo — "Repoblar Cables": toma los cables que `GET .../cables-detectados`
    encontró faltantes o desactualizados y los persiste en `app.cromo_cables`/`cromo_tubos`/
    `cromo_pelos` local, con el extremo correctamente anclado a esta Botella. Nunca escribe hacia
    Cromo (`CromoClient` es de sólo lectura por diseño) ni toca `CromoBotella`/`CromoFusion`. Sólo
    admin — ver `core/services/cromo/repoblacion_service.py::repoblar_cables`."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botella_repoblar_cables result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo.repoblacion_service import repoblar_cables
    from core.services.cromo.verificador import ObjetoNoEncontrado
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion, CromoClient(config=get_cromo_config()) as cliente:
            resultado = await repoblar_cables(cliente, sesion, botella_n_id=n_id, usuario=username)
    except ObjetoNoEncontrado as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except CromoClientError as exc:
        return JSONResponse({"error": f"Cromo no respondió: {exc}"}, status_code=502)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("action=botella_repoblar_cables_error user=%s n_id=%s error=%s", username, n_id, exc)
        return JSONResponse({"error": "No se pudo repoblar cables"}, status_code=500)

    if resultado.corrida_id is not None:
        await encolar_recalculo_duplicados_botellas(motivo=f"repoblar-cables n_id={n_id} usuario={username}")
    return JSONResponse(
        {
            "ok": True,
            "corrida_id": resultado.corrida_id,
            "botella_n_id": resultado.botella_n_id,
            "creados": resultado.creados,
            "actualizados": resultado.actualizados,
            "sin_cambios": resultado.sin_cambios,
            "errores": resultado.errores,
            "detalle": [{"n_id": i.n_id, "accion": i.accion, "detalle": i.detalle} for i in resultado.detalle],
        }
    )


class BotellaActualizarNombreRequestModel(BaseModel):
    """Payload para corregir a mano el nombre de una Botella Cromo."""

    nombre: str = Field(min_length=1, max_length=500)
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.patch("/api/infra/botellas/{n_id}/nombre")
async def botella_actualizar_nombre_web(request: Request, n_id: int, body: BotellaActualizarNombreRequestModel) -> JSONResponse:
    """Verificador Cromo — corrección manual de nombre duplicado/incorrecto. Marca
    `nombre_editado_manual=True` para que ninguna corrida de ingesta futura la pise (ver
    `core/services/cromo/ingesta.py::_procesar_botella_completa`). Si la Botella ya existe
    localmente es escritura local pura y no toca Cromo. Si todavía no existe
    localmente (caso "ID dual": Cromo reportó la misma Botella física bajo otro n_id en una corrida
    anterior), LEE Cromo en vivo (`CromoClient` de sólo lectura) para crearla antes de aplicar la
    corrección — nunca escribe hacia Cromo. En ese camino la fila puede quedar bajo un n_id DISTINTO
    al de la URL (el de la URL puede ser un id de versión; Cromo manda con su n_id de linaje), así
    que el `n_id` de la respuesta es siempre el real, más `n_id_solicitado` cuando difieren.
    Sólo admin."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botella_actualizar_nombre result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    from db.models.cromo import CromoBotella
    from db.session import AsyncSessionLocal

    nombre_normalizado = body.nombre.strip()
    if not nombre_normalizado:
        return JSONResponse({"error": "El nombre no puede quedar vacío."}, status_code=400)

    async with AsyncSessionLocal() as sesion:
        botella = await sesion.get(CromoBotella, n_id)
        if botella is None:
            from core.services.cromo.botella_creacion_service import (
                IdentidadYaResueltaError,
                crear_o_actualizar_botella_desde_vivo,
            )
            from core.services.cromo.client import CromoClient, CromoClientError
            from core.services.cromo.config import CromoConfigError, get_cromo_config
            from core.services.cromo.parser import ClaseExcluidaError
            from core.services.cromo.verificador import ObjetoNoEncontrado

            try:
                async with CromoClient(config=get_cromo_config()) as cliente:
                    resultado = await crear_o_actualizar_botella_desde_vivo(
                        cliente, sesion, n_id=n_id, usuario=username
                    )
            except ObjetoNoEncontrado as exc:
                return JSONResponse({"error": str(exc)}, status_code=404)
            except IdentidadYaResueltaError as exc:
                return JSONResponse(
                    {"error": str(exc), "n_id_correcto": exc.n_id_resuelto}, status_code=409
                )
            except ClaseExcluidaError as exc:
                return JSONResponse({"error": f"n_id={n_id} no es una Botella: {exc}"}, status_code=400)
            except CromoClientError as exc:
                return JSONResponse({"error": f"Cromo no respondió: {exc}"}, status_code=502)
            except CromoConfigError as exc:
                # Faltan credenciales/URL de Cromo: no es un 500 opaco, es "no pudimos hablar con
                # Cromo" — mismo 502 que `CromoClientError`, con la causa real en el log.
                logger.error(
                    "action=botella_actualizar_nombre result=fail reason=cromo_no_configurado n_id=%s error=%s",
                    n_id,
                    exc,
                )
                return JSONResponse({"error": f"Cromo no está configurado: {exc}"}, status_code=502)
            except HTTPException:
                raise
            except Exception as exc:
                # Red de seguridad final, mismo patrón que `botella_repoblar_cables_web`: cualquier
                # otra falla queda logueada con traza en vez de propagarse como 500 sin contexto.
                logger.exception(
                    "action=botella_actualizar_nombre result=fail reason=error_inesperado n_id=%s error=%s",
                    n_id,
                    exc,
                )
                return JSONResponse(
                    {"error": "Error inesperado al crear la Botella desde Cromo."}, status_code=500
                )

            logger.info(
                "action=botella_creada_desde_vivo user=%s n_id=%s n_id_solicitado=%s accion=%s corrida_id=%s",
                username,
                resultado.n_id,
                n_id,
                resultado.accion,
                resultado.corrida_id,
            )
            # La fila puede haber quedado bajo un n_id distinto al del path: el solicitado puede ser
            # un id de versión y `crear_o_actualizar_botella_desde_vivo` ancla a la identidad de
            # linaje que reporta Cromo (ver su docstring).
            botella = await sesion.get(CromoBotella, resultado.n_id)

        n_id_final = botella.n_id
        botella.nombre = nombre_normalizado
        botella.nombre_editado_manual = True
        await sesion.commit()

    logger.info(
        "action=botella_actualizar_nombre user=%s n_id=%s n_id_solicitado=%s nombre=%r",
        username,
        n_id_final,
        n_id,
        nombre_normalizado,
    )
    await encolar_recalculo_duplicados_botellas(
        motivo=f"actualizar-nombre n_id={n_id_final} usuario={username}"
    )
    respuesta = {"ok": True, "n_id": n_id_final, "nombre": nombre_normalizado}
    if n_id_final != n_id:
        respuesta["n_id_solicitado"] = n_id
    return JSONResponse(respuesta)


class BotellaSepararPadreRequestModel(BaseModel):
    """Payload para separar una Botella Cromo de su Cámara padre actual hacia una Cámara nueva."""

    nombre: str = Field(min_length=1, max_length=255)
    motivo: str = Field(min_length=1, max_length=1000)
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@app.post("/api/infra/botellas/{n_id}/separar-padre")
async def botella_separar_padre_web(request: Request, n_id: int, body: BotellaSepararPadreRequestModel) -> JSONResponse:
    """Verificador Cromo — separa una Botella agrupada erróneamente por nombre bajo una Cámara
    padre compartida: crea una Cámara nueva e independiente y reasigna `camara_id`. Rechaza si el
    nombre (siempre editable en el modal) colisiona, tras normalizar, con cualquier Cámara raíz
    existente. Nunca toca la Cámara padre anterior. Sólo admin — ver
    `core/services/cromo/separacion_service.py::separar_botella_de_padre`."""
    username = _require_admin(request)
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=botella_separar_padre result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    from core.services.cromo.separacion_service import (
        BotellaNoEncontradaError,
        SeparacionBotellaError,
        separar_botella_de_padre,
    )
    from db.session import SessionLocal

    with SessionLocal() as session:
        try:
            resultado = separar_botella_de_padre(
                session, botella_n_id=n_id, nombre=body.nombre, motivo=body.motivo, usuario=username
            )
        except BotellaNoEncontradaError as exc:
            session.rollback()
            return JSONResponse({"error": str(exc)}, status_code=404)
        except SeparacionBotellaError as exc:
            session.rollback()
            return JSONResponse({"error": str(exc)}, status_code=400)
        session.commit()

    logger.info(
        "action=botella_separar_padre user=%s botella_n_id=%s camara_anterior_id=%s camara_nueva_id=%s",
        username, resultado.botella_n_id, resultado.camara_anterior_id, resultado.camara_nueva_id,
    )
    await encolar_recalculo_duplicados_botellas(motivo=f"separar-padre n_id={n_id} usuario={username}")
    await _encolar_arbitro("BOTELLAS", [n_id], f"separar-padre n_id={n_id}")
    return JSONResponse({
        "ok": True,
        "botella_n_id": resultado.botella_n_id,
        "camara_anterior_id": resultado.camara_anterior_id,
        "camara_nueva_id": resultado.camara_nueva_id,
        "camara_nueva_nombre": resultado.camara_nueva_nombre,
    })


# =============================================================================
# TRACKING V2: ANÁLISIS Y RESOLUCIÓN INTELIGENTE
# =============================================================================


# ── Routers por dominio (antes del catch-all SPA) ───────────────────
app.include_router(sesion.router)
app.include_router(informes.router)
app.include_router(chat.router)
app.include_router(admin_datos.router)
app.include_router(servicios.router)


# ── SPA Catch-all (DEBE ser la última ruta) ─────────────────────────
# Devuelve el index.html del build Vite para todas las rutas no reconocidas.
# Esto permite que Vue Router maneje el routing del lado del cliente.
@app.get("/{path:path}")
async def spa_fallback(path: str) -> FileResponse:
    if SPA_INDEX.exists():
        return FileResponse(str(SPA_INDEX))
    return FileResponse(str(SPA_INDEX), status_code=404)
