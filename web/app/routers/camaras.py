# Nombre de archivo: camaras.py
# Ubicación de archivo: web/app/routers/camaras.py
# Descripción: Rutas de Cámaras: consulta, baneos, notificaciones, exportación, búsqueda, ingresos y administración

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.utils.tz import TZ_ARG

from ..comun import (
    _require_admin,
    _require_auth,
    _serializar_bloqueos,
    _serialize_camara_ingreso,
    logger,
)

router = APIRouter()

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


@router.get("/api/infra/camaras")
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


@router.get("/api/infra/camaras/buscar")
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


@router.get("/api/infra/camaras/{camara_id}")
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


@router.get("/api/infra/camaras/{camara_id}/aliases")
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


@router.get("/api/infra/camaras/{camara_id}/botellas")
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


@router.get("/api/infra/camaras/{camara_id}/registros")
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


@router.post("/api/infra/ban/create")
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


@router.get("/api/infra/ban/active")
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


@router.post("/api/infra/ban/lift")
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


@router.get("/api/admin/baneos/grupos")
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


@router.post("/api/admin/baneos/grupos/liberar")
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


@router.post("/api/infra/notify/email")
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


@router.get("/api/infra/notify/email/config")
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


@router.post("/api/infra/notify/download-eml")
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
    from datetime import datetime, timezone  # noqa: F811
    import io  # noqa: F811
    import re  # noqa: F811
    
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

@router.get("/api/infra/export/cameras")
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


@router.post("/api/infra/search")
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


@router.get("/api/infra/camaras/{camara_id}/estado")
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


@router.post("/api/infra/camaras/{camara_id}/estado")
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


@router.post("/api/infra/ingresos/{ingreso_id}/egreso")
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


@router.get("/api/admin/infra/ingresos-sin-match")
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


@router.post("/api/admin/infra/ingresos-sin-match/{caso_id}/marcar-revisado")
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


@router.post("/api/admin/infra/ingresos-sin-match/marcar-revisado-masivo")
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


@router.get("/api/admin/infra/camaras/pendientes")
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


@router.post("/api/admin/infra/camaras/{camara_id}/aprobar")
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


@router.post("/api/admin/infra/camaras/{camara_id}/convertir-alias")
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


@router.post("/api/admin/infra/camaras/{camara_id}/dar-de-alta")
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


@router.delete("/api/admin/infra/camaras/pendientes/{camara_id}")
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


@router.get("/api/admin/infra/camaras/viewer")
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


@router.get("/api/admin/infra/camaras/viewer/duplicados")
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


@router.post("/api/infra/smart-search")
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


















































































































class CamaraEliminarRequestModel(BaseModel):
    """Payload para eliminar permanentemente una Cámara raíz genuinamente vacía (cascada a sus Botellas)."""

    camara_id: int
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/infra/camaras/eliminar")
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










class CamaraMergeRequestModel(BaseModel):
    """Payload para unificar dos Cámaras raíz duplicadas."""

    camara_principal_id: int
    camara_secundaria_id: int
    guardar_alias: bool = True
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/infra/camaras/merge")
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


@router.post("/api/infra/camaras/merge-grupo")
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


@router.post("/api/infra/camaras/merge-masivo")
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
















































































































