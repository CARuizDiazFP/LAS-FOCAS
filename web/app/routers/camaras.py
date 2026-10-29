# Nombre de archivo: camaras.py
# Ubicación de archivo: web/app/routers/camaras.py
# Descripción: Rutas de Cámaras: consulta, baneos, notificaciones, exportación, búsqueda, ingresos y administración

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.services.baneo_aviso import (
    armar_eml_baneo,
    detalle_incidente_baneo,
    enviar_aviso_baneo,
    estado_config_email,
    parsear_destinatarios,
)
from core.services.baneo_operaciones import (
    LARGO_MOTIVO,
    LARGO_SERVICIO,
    LARGO_TICKET,
    crear_baneo_y_notificar,
    levantar_baneo_y_notificar,
    listar_incidentes_activos,
)
from core.services.camaras_exportacion import (
    AVISO_SIN_XLSX,
    a_csv,
    a_xlsx,
    filas_exportacion,
    nombre_archivo_exportacion,
)
from core.services.camaras_busqueda_avanzada import SearchRequest, buscar_camaras_avanzada
from core.services.camaras_consulta import (
    _collect_camara_rutas_info,
    _collect_camara_servicios_ids,
    buscar_camaras_por_terminos,
    listar_camaras,
    serializar_camara_basica,
)
from core.services.camaras_consulta import serializar_camara_panel as _serialize_camara_response

from modules.slack_baneo_notifier.eventos import notificar_evento_baneo

from ..comun import (
    _incluye_anulados,
    _serializar_bloqueos,
    _serialize_camara_ingreso,
    logger,
)
from ..dependencias import UsuarioSesion, requiere_csrf, usuario_admin, usuario_sesion
from ..errores import Conflicto, DatoInvalido, ErrorDeDominio, NoEncontrado, error_interno, nueva_ref

router = APIRouter(dependencies=[Depends(usuario_sesion), Depends(requiere_csrf)])

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


class CamaraEstadoUpdateRequest(BaseModel):
    """Payload para override manual del estado de una cámara."""

    estado: str
    motivo: str = Field(min_length=5, max_length=500)


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
def search_camaras_web(
    q: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = 100,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Busca cámaras por query y/o estado (misma consulta que la API: `listar_camaras`)."""

    username, role = usuario

    try:
        from core.services.camara_estado_service import get_camara_estado_contexto_batch
        from db.session import SessionLocal

        with SessionLocal() as session:
            encontradas = listar_camaras(session, q=q, estado=estado, limit=limit)
            contextos = get_camara_estado_contexto_batch(session, [e.camara.id for e in encontradas])
            camaras_response = [
                _serialize_camara_response(
                    camara=e.camara,
                    rutas_info=e.rutas_info,
                    servicios_ids=e.servicios_ids,
                    contexto=contextos.get(e.camara.id),
                    editable=role == "admin",
                )
                for e in encontradas
            ]

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

    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("search_camaras", exc, user=username)


@router.get("/api/infra/camaras/buscar")
def camaras_buscar_ligero_web(
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("camaras_buscar_ligero", exc)


@router.get("/api/infra/camaras/{camara_id}")
def get_camara_detail_web(
    camara_id: int,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Obtiene el resumen operativo base de una cámara para la vista de detalle."""

    _, role = usuario

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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("get_camara_detail", exc, camara_id=camara_id)


@router.get("/api/infra/camaras/{camara_id}/aliases")
def get_camara_aliases_web(camara_id: int) -> JSONResponse:
    """Obtiene los alias conocidos de una cámara."""

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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("get_camara_aliases", exc, camara_id=camara_id)


@router.get("/api/infra/camaras/{camara_id}/botellas")
def get_camara_botellas_web(
    camara_id: int,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
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

    _, role = usuario

    try:
        from core.services.camara_estado_service import get_camara_estado_contexto_batch
        from db.models.cromo import CromoBotella
        from db.models.infra import Camara
        from db.session import SessionLocal

        with SessionLocal() as session:
            camara = session.query(Camara).filter(Camara.id == camara_id).first()
            if not camara:
                return JSONResponse({"error": "Cámara no encontrada"}, status_code=404)

            contextos = get_camara_estado_contexto_batch(session, [botella.id for botella in camara.botellas])
            botellas_legado = [
                {
                    **_serialize_camara_response(
                        camara=botella,
                        rutas_info=_collect_camara_rutas_info(botella),
                        servicios_ids=_collect_camara_servicios_ids(botella),
                        contexto=contextos.get(botella.id),
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("get_camara_botellas", exc, camara_id=camara_id)


@router.get("/api/infra/camaras/{camara_id}/registros")
def get_camara_registros_web(
    camara_id: int,
    incluir_anulados: bool = False,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Obtiene registros operativos parciales de una cámara para la vista dedicada.

    Los ingresos anulados (baja lógica) no se listan. Un admin puede pedirlos con
    `?incluir_anulados=1` (la UI los muestra atenuados); para un usuario común el parámetro se ignora.
    """

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
            query_ingresos = session.query(Ingreso).filter(Ingreso.camara_id.in_(ids_grupo))
            if not _incluye_anulados(incluir_anulados, usuario):
                query_ingresos = query_ingresos.filter(Ingreso.vigente())
            ingresos_db = query_ingresos.order_by(nullslast(Ingreso.fecha_inicio.desc())).limit(50).all()

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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("get_camara_registros", exc, camara_id=camara_id)


# -----------------------------------------------------------------------------
# ALIAS: TRACKING DOWNLOAD (para compatibilidad con panel.js)
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# ENDPOINTS DE BANEO (Protocolo de Protección)
# -----------------------------------------------------------------------------

class BanCreateRequestModel(BaseModel):
    """Request para crear un baneo."""
    ticket_asociado: Optional[str] = Field(None, max_length=LARGO_TICKET)
    servicio_afectado_id: str = Field(..., max_length=LARGO_SERVICIO)
    servicio_protegido_id: str = Field(..., max_length=LARGO_SERVICIO)
    ruta_protegida_id: Optional[int] = None
    motivo: Optional[str] = Field(None, max_length=LARGO_MOTIVO)


class BanLiftRequestModel(BaseModel):
    """Request para levantar un baneo."""
    incidente_id: int
    motivo_cierre: Optional[str] = Field(None, max_length=LARGO_MOTIVO)


@router.post("/api/infra/ban/create")
def create_ban_web(
    ban_request: BanCreateRequestModel,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Crea un incidente de baneo y marca las cámaras como BANEADAS."""
    username, _ = usuario
    try:
        from db.session import SessionLocal

        with SessionLocal() as session:
            result = crear_baneo_y_notificar(
                session,
                ticket_asociado=ban_request.ticket_asociado,
                servicio_afectado_id=ban_request.servicio_afectado_id,
                servicio_protegido_id=ban_request.servicio_protegido_id,
                ruta_protegida_id=ban_request.ruta_protegida_id,
                motivo=ban_request.motivo,
                usuario_ejecutor=username,
                notificar=notificar_evento_baneo,
            )
            if result.success:
                logger.info(
                    "action=create_ban user=%s ticket=%s servicio_afectado=%s servicio_protegido=%s camaras=%d",
                    username,
                    ban_request.ticket_asociado,
                    ban_request.servicio_afectado_id,
                    ban_request.servicio_protegido_id,
                    result.camaras_baneadas,
                )
            else:
                logger.warning("action=create_ban_failed user=%s error=%s", username, result.message)
            return JSONResponse(result.to_dict())
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("create_ban", exc, cuerpo={"success": False}, user=username)


@router.get("/api/infra/ban/active")
def get_active_bans_web(usuario: UsuarioSesion = Depends(usuario_sesion)) -> JSONResponse:
    """Obtiene todos los incidentes de baneo activos con conteo de cámaras."""
    username, _ = usuario
    try:
        from db.session import SessionLocal

        with SessionLocal() as session:
            cuerpo = listar_incidentes_activos(session)
        logger.info("action=get_active_bans user=%s count=%d", username, cuerpo["total"])
        return JSONResponse(cuerpo)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("get_active_bans", exc, user=username)


@router.post("/api/infra/ban/lift")
def lift_ban_web(
    lift_request: BanLiftRequestModel,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Levanta un baneo y restaura el estado de las cámaras."""
    username, _ = usuario
    try:
        from db.session import SessionLocal

        with SessionLocal() as session:
            result = levantar_baneo_y_notificar(
                session,
                lift_request.incidente_id,
                usuario_ejecutor=username,
                motivo_cierre=lift_request.motivo_cierre,
                notificar=notificar_evento_baneo,
            )
            if result.success:
                logger.info(
                    "action=lift_ban user=%s incidente_id=%d camaras_restauradas=%d",
                    username,
                    lift_request.incidente_id,
                    result.camaras_restauradas,
                )
            else:
                logger.warning(
                    "action=lift_ban_failed user=%s incidente_id=%d error=%s",
                    username,
                    lift_request.incidente_id,
                    result.message,
                )
            return JSONResponse(result.to_dict())
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("lift_ban", exc, cuerpo={"success": False}, user=username)


# Después de /ban/active y /ban/lift: un {incidente_id} declarado antes los capturaría (y daría 422).
@router.get("/api/infra/ban/{incidente_id}")
def get_ban_detail_web(incidente_id: int, usuario: UsuarioSesion = Depends(usuario_sesion)) -> JSONResponse:
    """Detalle de un incidente de baneo con la plantilla guardada del aviso y el conteo de cámaras."""
    username, _ = usuario
    try:
        from db.session import SessionLocal

        with SessionLocal() as session:
            detalle = detalle_incidente_baneo(session, incidente_id)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("get_ban_detail", exc, user=username, incidente_id=incidente_id)
    if detalle is None:
        raise NoEncontrado(f"Incidente {incidente_id} no encontrado")
    return JSONResponse(detalle)


# -----------------------------------------------------------------------------
# ENDPOINTS DE GRUPOS BANEADOS (Cámara padre + Botellas) — listado admin y liberación masiva.
# Distinto del Protocolo de Protección arriba (`/api/infra/ban/*`, `IncidenteBaneo`): este listado
# agrupa por Cámara padre TODO baneo activo (incidente o no — override manual/import Excel también
# entran) y su única acción es "liberar" (= cambiar estado a LIBRE/estado_sugerido), nunca borrar
# filas — ver `core/services/baneos_grupos_service.py`.
# -----------------------------------------------------------------------------


@router.get("/api/admin/baneos/grupos", dependencies=[Depends(usuario_admin)])
def baneos_grupos_listar_web(
    q: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> JSONResponse:
    """Lista grupos baneados (Cámara padre raíz + sus Botellas legado/Cromo), paginado. `limit`
    siempre viene de query param acá (int) — el `limit=None` sin paginar de
    `listar_grupos_baneados` sólo lo usa internamente el reporte Excel de la Tarea 8, nunca este
    endpoint web."""

    try:
        from core.services.baneos_grupos_service import listar_grupos_baneados
        from db.session import SessionLocal

        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        with SessionLocal() as session:
            resultado = listar_grupos_baneados(session, q=q, limit=limit, offset=offset)
            return JSONResponse({"status": "ok", "limit": limit, "offset": offset, **resultado.to_dict()})
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("baneos_grupos_listar", exc)


class BaneosLiberarMasivoRequestModel(BaseModel):
    """Payload para liberar (desbanear) varios grupos de una — NO es un borrado físico."""

    camara_ids: list[int]
    motivo: str
    forzar: bool = False


@router.post("/api/admin/baneos/grupos/liberar")
def baneos_grupos_liberar_web(
    request: Request,
    body: BaneosLiberarMasivoRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Libera (desbanea) varios grupos de una — la única acción masiva nueva de este dominio.
    Guard de incidente activo por grupo (`core.services.baneos_grupos_service.liberar_grupos_masivo`):
    sin `forzar`, un grupo con un `IncidenteBaneo` activo detrás se omite en vez de desbanearse."""
    username = usuario.username
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("baneos_grupos_liberar", exc, user=username)


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
def send_email_notification_web(
    email_request: EmailNotifyRequestModel,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Envía un correo electrónico con información de baneos."""
    
    username, _ = usuario

    try:
        from db.session import SessionLocal

        with SessionLocal() as session:
            resultado = enviar_aviso_baneo(
                session,
                to=email_request.to,
                cc=email_request.cc,
                subject=email_request.subject,
                body=email_request.body,
                incidente_ids=email_request.incidente_ids,
                include_xls=email_request.include_xls,
                include_txt=email_request.include_txt,
            )

        logger.info(
            "action=send_email user=%s to=%s success=%s",
            username,
            email_request.to,
            resultado.success,
        )
        return JSONResponse(asdict(resultado))

    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno(
            "send_email", exc, cuerpo={"success": False, "message": "Error enviando email"}, user=username
        )


@router.get("/api/infra/notify/email/config")
async def get_email_config_web() -> JSONResponse:
    """Obtiene el estado de configuración del email."""

    try:
        return JSONResponse(estado_config_email())

    except Exception as exc:
        # Responde 200 (no 500) como siempre: sólo deja de exponer el texto de la excepción.
        ref = nueva_ref()
        logger.exception("action=get_email_config_error error=%s ref=%s", exc, ref)
        return JSONResponse({"configured": False, "error": f"Error interno (ref {ref})"})


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


@router.post("/api/infra/notify/download-eml")
def generate_eml_file(
    eml_request: EmlDownloadRequestModel,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> Response:
    """Genera un archivo .eml descargable con el correo de notificación.

    Alternativa cuando no se puede usar SMTP directamente (ej: Office 365 sin App Password):
    el usuario abre el .eml con su cliente de correo y lo envía a mano. El armado vive en
    `core.services.baneo_aviso.armar_eml_baneo`, compartido con la API.
    """
    username, _ = usuario

    try:
        destinatarios = parsear_destinatarios(eml_request.recipients)
        if not destinatarios:
            return JSONResponse({"error": "No se especificaron destinatarios válidos"}, status_code=400)

        from db.session import SessionLocal

        with SessionLocal() as session:
            eml = armar_eml_baneo(
                session,
                eml_request.incident_id,
                destinatarios=destinatarios,
                subject=eml_request.subject,
                html_body=eml_request.html_body,
                include_xls=eml_request.include_xls,
                include_txt=eml_request.include_txt,
            )
        if eml is None:
            return JSONResponse(
                {"error": f"Incidente {eml_request.incident_id} no encontrado"}, status_code=404
            )

        logger.info(
            "action=generate_eml user=%s incident_id=%d recipients=%d",
            username, eml_request.incident_id, len(destinatarios),
        )
        return Response(
            content=eml.contenido,
            media_type="message/rfc822",
            headers={"Content-Disposition": f'attachment; filename="{eml.nombre_archivo}"'},
        )

    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("generate_eml", exc, user=username)


# -----------------------------------------------------------------------------
# EXPORTACIÓN DE CÁMARAS
# -----------------------------------------------------------------------------

@router.get("/api/infra/export/cameras")
def export_cameras_web(
    filter_status: Optional[str] = None,
    servicio_id: Optional[str] = None,
    format: str = "csv",
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> Response:
    """Exporta listado de cámaras a CSV o XLSX."""

    username, _ = usuario

    try:
        from db.session import SessionLocal

        with SessionLocal() as session:
            rows = filas_exportacion(session, filter_status=filter_status, servicio_id=servicio_id)

            logger.info(
                "action=export_cameras user=%s filter_status=%s format=%s rows=%d",
                username,
                filter_status,
                format,
                len(rows),
            )

            cabeceras = {}
            if format.lower() == "xlsx":
                contenido_xlsx = a_xlsx(rows)
                if contenido_xlsx is not None:
                    return Response(
                        content=contenido_xlsx,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={
                            "Content-Disposition": f'attachment; filename="{nombre_archivo_exportacion("xlsx")}"',
                        },
                    )
                logger.warning("action=export_cameras warning=pandas_not_available fallback=csv")
                cabeceras["X-Export-Warning"] = AVISO_SIN_XLSX

            return Response(
                content=a_csv(rows),
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{nombre_archivo_exportacion("csv")}"',
                    **cabeceras,
                },
            )

    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("export_cameras", exc, user=username)


@router.post("/api/infra/search")
def advanced_search_camaras_web(
    body: SearchRequest,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Búsqueda avanzada de cámaras con filtros combinables (AND).

    Campos: service_id, address, status, cable, origen
    Operadores: eq, contains, starts_with, ends_with, in
    """

    username, _ = usuario

    try:
        from db.session import SessionLocal

        with SessionLocal() as session:
            resultado = buscar_camaras_avanzada(session, body.filters, limit=body.limit, offset=body.offset)
            camaras = [serializar_camara_basica(e) for e in resultado.camaras]

        logger.info(
            "action=advanced_search user=%s filters=%d total=%d returned=%d",
            username,
            len(body.filters),
            resultado.total,
            len(camaras),
        )

        return JSONResponse({
            "status": "ok",
            "total": resultado.total,
            "limit": body.limit,
            "offset": body.offset,
            "filters_applied": len(body.filters),
            "camaras": camaras,
        })

    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("advanced_search", exc, user=username)


class SmartSearchRequestModel(BaseModel):
    """Request para Smart Search con términos libres."""
    terms: list[str] = Field(default_factory=list, max_length=20)
    limit: int = Field(100, ge=1, le=500)
    offset: int = Field(0, ge=0)
    estado: Optional[str] = None
    incluir_no_operativas: bool = False


@router.get("/api/infra/camaras/{camara_id}/estado", dependencies=[Depends(usuario_admin)])
def get_camara_estado_web(camara_id: int) -> JSONResponse:
    """Obtiene el contexto operativo del estado de una cámara."""

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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("get_camara_estado", exc, camara_id=camara_id)


@router.post("/api/infra/camaras/{camara_id}/estado")
def update_camara_estado_web(
    request: Request,
    camara_id: int,
    body: CamaraEstadoUpdateRequest,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Permite a un administrador aplicar un override manual del estado."""

    username = usuario.username
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("update_camara_estado", exc, user=username, camara_id=camara_id)


# ── Endpoints admin: gestión de cámaras PENDIENTE_REVISION ───────────────


class RegistrarEgresoWebRequestModel(BaseModel):
    """Payload del botón "Registrar egreso" (vista Ingresos del Servicio). `momento` debe traer zona
    horaria — el frontend envía ISO 8601 en UTC; un valor naive se rechaza con 422 en vez de
    adivinar si era hora local o UTC."""

    momento: datetime
    motivo: str = Field(min_length=3, max_length=500)


# Resultado de `registrar_egreso_web` → status HTTP. Todo lo que no es OK es un rechazo de negocio
# ya auditado en `app.ingresos_correcciones`, no un error del servidor.
_EGRESO_WEB_STATUS = {
    "OK_EGRESO_CERRADO": 200,
    "INGRESO_NO_ENCONTRADO": 404,
    "INGRESO_YA_CERRADO": 409,
    "INGRESO_ANULADO": 409,
    "MOMENTO_INVALIDO": 422,
    "EGRESO_ANTERIOR_AL_INGRESO": 422,
}


@router.post("/api/infra/ingresos/{ingreso_id}/egreso")
def registrar_egreso_ingreso_web(
    request: Request, ingreso_id: int, body: RegistrarEgresoWebRequestModel,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Registra el egreso de un `Ingreso` que quedó "en curso" (el formulario de Egreso nunca llegó
    por Slack). Delegado entero en `ingreso_correccion_service.registrar_egreso_web` — mismas reglas
    y mismo log de auditoría que el comando Slack `Forzar egreso #<id>`, con `origen='web'`.

    Sin restricción de rol más allá de estar autenticado: mismo criterio que los comandos de Slack
    (cualquiera del canal puede corregir; la auditoría es el control — ver docstring del servicio)."""
    username, _ = usuario
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("registrar_egreso_web", exc, user=username, ingreso_id=ingreso_id)


# ── Corrección de ingresos desde el portal (sólo admin, 2026-10-23) ─────────────────────────────
#
# Mover (el ingreso existió pero quedó en la cámara equivocada) y anular (nunca ocurrió, baja lógica).
# Toda la lógica (validaciones, auditoría en `app.ingresos_correcciones`, FO Monitor) vive en
# `ingreso_correccion_service`; acá sólo CSRF, sesión admin y el mapeo resultado → error tipado.
# Cada rechazo de negocio ya quedó auditado por el servicio antes de llegar acá.


class MoverIngresoWebRequestModel(BaseModel):
    """`cromo_botella_destino_n_id` es opcional: sin él, el ingreso queda sin botella en el destino.
    El largo del motivo (3 a 500 tras `strip`) lo valida el servicio, que audita el rechazo; el tope
    de Pydantic sólo corta payloads abusivos."""

    camara_destino_id: int
    cromo_botella_destino_n_id: int | None = None
    motivo: str = Field(max_length=2000)


class AnularIngresoWebRequestModel(BaseModel):
    """Mismo criterio de motivo que `MoverIngresoWebRequestModel`."""

    motivo: str = Field(max_length=2000)


def _error_correccion_ingreso(resultado: Any) -> ErrorDeDominio:
    """Rechazo de negocio de mover/anular → error tipado con el texto del servicio (nunca deriva a
    terceros). Un resultado desconocido es un bug: `RuntimeError` → 500 con ref."""
    from core.services import ingreso_correccion_service as ics

    clases: dict[str, type[ErrorDeDominio]] = {
        ics.RESULTADO_INGRESO_NO_ENCONTRADO: NoEncontrado,
        ics.RESULTADO_CAMARA_NO_ENCONTRADA: NoEncontrado,
        ics.RESULTADO_MOTIVO_INVALIDO: DatoInvalido,
        ics.RESULTADO_BOTELLA_INVALIDA: DatoInvalido,
        ics.RESULTADO_DESTINO_NO_RAIZ: DatoInvalido,
        ics.RESULTADO_INGRESO_ANULADO: Conflicto,
        ics.RESULTADO_MISMO_DESTINO: Conflicto,
    }
    clase = clases.get(resultado.resultado)
    if clase is None:
        raise RuntimeError(f"resultado inesperado de corrección de ingreso: {resultado.resultado}")
    return clase(resultado.respuesta)


def _respuesta_correccion_ingreso(resultado: Any) -> JSONResponse:
    """Cuerpo 200 de mover/anular: el ingreso serializado como en los listados (más su cámara) y lo
    que pasó con FO Monitor. Se llama dentro de la sesión (resuelve `camara`/`cromo_botella`)."""
    ingreso = resultado.ingreso
    serializado = _serialize_camara_ingreso(ingreso)
    serializado["camara_id"] = ingreso.camara_id
    camara = getattr(ingreso, "camara", None)
    serializado["camara_nombre"] = camara.nombre if camara is not None else None
    return JSONResponse(
        {
            "ok": True,
            "resultado": resultado.resultado,
            "mensaje": resultado.respuesta,
            "ingreso": serializado,
            "intervenciones_fomon": list(resultado.intervenciones_fomon),
            "intervenciones_fomon_omitidas": [
                {"intervencion_id": o.intervencion_id, "motivo": o.motivo}
                for o in resultado.intervenciones_fomon_omitidas
            ],
        }
    )


@router.post("/api/admin/infra/ingresos/{ingreso_id}/mover")
def admin_mover_ingreso_web(
    request: Request, ingreso_id: int, body: MoverIngresoWebRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Mueve un ingreso a otra Cámara (y opcionalmente a una `CromoBotella` vigente del destino).
    Delegado en `ingreso_correccion_service.mover_ingreso_web`; 404 ingreso/cámara inexistente,
    409 ingreso anulado o mismo destino, 422 motivo o botella inválidos o destino que no es una
    cámara raíz (`camara_padre_id` seteado)."""
    username = usuario.username

    try:
        from core.services import ingreso_correccion_service as ics
        from db.session import SessionLocal

        with SessionLocal() as session:
            resultado = ics.mover_ingreso_web(
                session,
                ingreso_id=ingreso_id,
                camara_destino_id=body.camara_destino_id,
                cromo_botella_destino_n_id=body.cromo_botella_destino_n_id,
                motivo=body.motivo,
                usuario=username,
            )
            logger.info(
                "action=admin_mover_ingreso user=%s ingreso_id=%s camara_destino_id=%s botella=%s "
                "resultado=%s fomon=%s fomon_omitidas=%s",
                username,
                ingreso_id,
                body.camara_destino_id,
                body.cromo_botella_destino_n_id,
                resultado.resultado,
                resultado.intervenciones_fomon,
                [o.intervencion_id for o in resultado.intervenciones_fomon_omitidas],
            )
            if resultado.resultado != ics.RESULTADO_OK_INGRESO_MOVIDO:
                raise _error_correccion_ingreso(resultado)
            return _respuesta_correccion_ingreso(resultado)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("admin_mover_ingreso", exc, user=username, ingreso_id=ingreso_id)


@router.post("/api/admin/infra/ingresos/{ingreso_id}/anular")
def admin_anular_ingreso_web(
    request: Request, ingreso_id: int, body: AnularIngresoWebRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Anula (baja lógica) un ingreso que nunca ocurrió. Delegado en
    `ingreso_correccion_service.anular_ingreso_web`; 404 inexistente, 409 ya anulado, 422 motivo
    inválido. El `IngresoSinMatch` que lo había resuelto no se reabre (decisión 4 del plan)."""
    username = usuario.username

    try:
        from core.services import ingreso_correccion_service as ics
        from db.session import SessionLocal

        with SessionLocal() as session:
            resultado = ics.anular_ingreso_web(
                session,
                ingreso_id=ingreso_id,
                motivo=body.motivo,
                usuario=username,
            )
            logger.info(
                "action=admin_anular_ingreso user=%s ingreso_id=%s resultado=%s fomon=%s fomon_omitidas=%s",
                username,
                ingreso_id,
                resultado.resultado,
                resultado.intervenciones_fomon,
                [o.intervencion_id for o in resultado.intervenciones_fomon_omitidas],
            )
            if resultado.resultado != ics.RESULTADO_OK_INGRESO_ANULADO:
                raise _error_correccion_ingreso(resultado)
            return _respuesta_correccion_ingreso(resultado)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("admin_anular_ingreso", exc, user=username, ingreso_id=ingreso_id)


@router.get("/api/admin/infra/ingresos-sin-match", dependencies=[Depends(usuario_admin)])
def admin_ingresos_sin_match(
    revisado: Optional[bool] = None, origen: Optional[str] = None,
) -> JSONResponse:
    """Lista casos de ingreso (bot de Slack o carga de tracking) cuya cámara no matcheó contra el
    inventario (2026-08-11) — reemplaza el auto-registro `PENDIENTE_REVISION`. Es información de
    sólo lectura para revisión manual y mejora del regex, no crea ninguna Cámara. `revisado` filtra
    por el flag (default: todos, sin filtrar). `origen` filtra por uno o más valores separados por
    coma (ej. `?origen=excel_camaras` o `?origen=slack,tracking`; default: todos, sin filtrar)."""
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("admin_ingresos_sin_match", exc)


@router.post(
    "/api/admin/infra/ingresos-sin-match/{caso_id}/marcar-revisado", dependencies=[Depends(usuario_admin)]
)
def admin_marcar_revisado_ingreso_sin_match(caso_id: int) -> JSONResponse:
    """Marca un caso de ingreso sin match como revisado — no muta ningún dato de infraestructura,
    sólo el flag de triage."""
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("admin_marcar_revisado_ingreso_sin_match", exc)


class MarcarRevisadoMasivoRequestModel(BaseModel):
    """Payload para marcar en lote varios `IngresoSinMatch` como revisados."""

    ids: list[int]


@router.post("/api/admin/infra/ingresos-sin-match/marcar-revisado-masivo")
def admin_marcar_revisado_masivo_web(
    request: Request,
    body: MarcarRevisadoMasivoRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Marca en lote varios casos de ingreso sin match como revisados — es el 'Borrado' del visor de
    ingesta: sólo descarta de la vista, no muta ningún dato de infraestructura, la fila queda en la
    base para poder ajustar a futuro el regex/normalización de búsqueda."""
    username = usuario.username
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("admin_marcar_revisado_masivo", exc, user=username)


@router.get("/api/admin/infra/camaras/pendientes", dependencies=[Depends(usuario_admin)])
def admin_camaras_pendientes() -> JSONResponse:
    """Lista cámaras auto-registradas en estado PENDIENTE_REVISION."""
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("admin_camaras_pendientes", exc)


@router.post("/api/admin/infra/camaras/{camara_id}/aprobar", dependencies=[Depends(usuario_admin)])
def admin_aprobar_camara(camara_id: int) -> JSONResponse:
    """Aprueba una cámara PENDIENTE_REVISION, cambiando su estado a LIBRE."""
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("admin_aprobar_camara", exc, camara_id=camara_id)


class _ConvertirAliasRequest(BaseModel):
    camara_destino_id: int


@router.post("/api/admin/infra/camaras/{camara_id}/convertir-alias", dependencies=[Depends(usuario_admin)])
def admin_convertir_alias(
    camara_id: int,
    body: _ConvertirAliasRequest,
) -> JSONResponse:
    """Convierte una cámara PENDIENTE_REVISION en alias de otra cámara existente.

    - Crea un registro en ``app.camara_alias`` asociando el nombre de la cámara
      pendiente como alias de la cámara destino.
    - Elimina físicamente el registro pendiente.
    """
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("admin_convertir_alias", exc, camara_id=camara_id)


class _DarDeAltaRequest(BaseModel):
    nombre_canon: str


@router.post("/api/admin/infra/camaras/{camara_id}/dar-de-alta", dependencies=[Depends(usuario_admin)])
def admin_dar_de_alta_camara(
    camara_id: int,
    body: _DarDeAltaRequest,
) -> JSONResponse:
    """Promueve una cámara PENDIENTE_REVISION a cámara oficial (estado LIBRE).

    Actualiza el nombre al nombre canónico provisto por el admin, cambia el
    estado de ``PENDIENTE_REVISION`` a ``LIBRE``, y guarda el nombre original
    (el que ingresó el técnico) como un alias en ``app.camara_alias``, siempre
    que sea diferente al nombre canónico.
    """
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("admin_dar_de_alta", exc, camara_id=camara_id)


@router.delete("/api/admin/infra/camaras/pendientes/{camara_id}", dependencies=[Depends(usuario_admin)])
def admin_eliminar_camara_pendiente(
    camara_id: int,
) -> JSONResponse:
    """Elimina físicamente de la DB una cámara en estado PENDIENTE_REVISION.

    Solo se permite eliminar cámaras que estén en estado ``PENDIENTE_REVISION``.
    Para proteger contra borrados accidentales, registros en otros estados
    deben gestionarse por otros medios.

    Desde 2026-10-23 bloquea (409) si la cámara tiene ingresos, incluidos los anulados: la cascada
    del ORM (``Camara.ingresos``, ``delete-orphan``) los borraba físicamente. Mismo criterio que
    ``camara_botella_delete_service._bloqueo_camara``.
    """
    try:
        from db.models.infra import Camara, CamaraEstado, Ingreso
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
            if session.query(Ingreso.id).filter(Ingreso.camara_id == camara_id).first() is not None:
                raise Conflicto("No se puede eliminar: la cámara tiene ingresos asociados.")
            nombre_eliminado = camara.nombre
            session.delete(camara)
            session.commit()
            logger.info(
                "action=eliminar_pendiente camara_id=%s nombre='%s'",
                camara_id,
                nombre_eliminado,
            )
            return JSONResponse({"ok": True, "id": camara_id})
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("admin_eliminar_pendiente", exc, camara_id=camara_id)


@router.get("/api/admin/infra/camaras/viewer", dependencies=[Depends(usuario_admin)])
def camaras_viewer_listado_web(
    q: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = 60,
    offset: int = 0,
) -> JSONResponse:
    """Listado paginado de Cámaras raíz para el dashboard `/admin/servicios/viewer/Camaras` (vista
    dual grid/lista). Paginación real en SQL, sin el N+1 en memoria de `smart-search`."""
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("camaras_viewer_listado", exc)


@router.get("/api/admin/infra/camaras/viewer/duplicados", dependencies=[Depends(usuario_admin)])
def camaras_viewer_duplicados_web() -> JSONResponse:
    """Grupos de Cámaras raíz candidatas a duplicado por nombre normalizado extendido (sin
    similitud difusa). Devuelve TODOS los grupos sin paginar — la cantidad de grupos es órdenes de
    magnitud menor que el total de Cámaras raíz. Ver `core/services/camara_duplicados_service.py`."""
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("camaras_viewer_duplicados", exc)


@router.post("/api/infra/smart-search")
def smart_search_camaras_web(
    body: SmartSearchRequestModel,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Smart Search: búsqueda libre por términos.

    Cada término se busca en múltiples campos (nombre, dirección, fontine_id,
    servicios, cables, estado, origen). Los términos se combinan con AND.
    """

    username, role = usuario

    try:
        from core.services.camara_estado_service import get_camara_estado_contexto_batch
        from db.session import SessionLocal

        with SessionLocal() as session:
            resultado = buscar_camaras_por_terminos(
                session,
                body.terms,
                estado=body.estado,
                incluir_no_operativas=body.incluir_no_operativas,
                limit=body.limit,
                offset=body.offset,
            )

            contextos = get_camara_estado_contexto_batch(
                session, [encontrada.camara.id for encontrada in resultado.camaras]
            )
            camaras_response = []
            for encontrada in resultado.camaras:
                cam = encontrada.camara
                camaras_response.append(
                    _serialize_camara_response(
                        camara=cam,
                        rutas_info=encontrada.rutas_info,
                        servicios_ids=encontrada.servicios_ids,
                        contexto=contextos.get(cam.id),
                        editable=role == "admin",
                    )
                )

            if body.terms:
                logger.info(
                    "action=smart_search user=%s terms=%d estado=%s incluir_no_operativas=%s total=%d returned=%d",
                    username,
                    resultado.terminos_aplicados,
                    resultado.estado_filter or "ninguno",
                    body.incluir_no_operativas,
                    resultado.total,
                    len(camaras_response),
                )

            return JSONResponse({
                "status": "ok",
                "total": resultado.total,
                "limit": resultado.limit,
                "offset": resultado.offset,
                "filters_applied": resultado.terminos_aplicados + (1 if resultado.estado_filter else 0),
                "estado_filter": resultado.estado_filter,
                "incluir_no_operativas": body.incluir_no_operativas,
                "camaras": camaras_response,
            })

    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("smart_search", exc, user=username)


















































































































class CamaraEliminarRequestModel(BaseModel):
    """Payload para eliminar permanentemente una Cámara raíz genuinamente vacía (cascada a sus Botellas)."""

    camara_id: int


@router.post("/api/infra/camaras/eliminar")
def camaras_eliminar_web(
    request: Request,
    body: CamaraEliminarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Elimina permanentemente una Cámara raíz junto con TODAS sus Botellas (legado + Cromo) — todo
    o nada: si un solo hijo (o la propia Cámara) tiene Cables/Empalmes/Ingresos/Fusiones reales
    asociados, se rechaza la operación completa sin borrar nada. Cada Botella Cromo eliminada
    registra su n_id en `app.cromo_botella_alias` (`accion='ignorar'`). Ver
    `core/services/camara_botella_delete_service.py`."""
    username = usuario.username
    try:
        from core.services.camara_botella_delete_service import EliminacionBloqueadaError, eliminar_camara
        from db.session import SessionLocal

        with SessionLocal() as session:
            try:
                resultado = eliminar_camara(session, camara_id=body.camara_id, usuario=username)
            except EliminacionBloqueadaError as exc:
                session.rollback()
                # Mensaje de dominio armado por el servicio para el usuario (no es texto interno).
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("camaras_eliminar", exc, user=username)










class CamaraMergeRequestModel(BaseModel):
    """Payload para unificar dos Cámaras raíz duplicadas."""

    camara_principal_id: int
    camara_secundaria_id: int
    guardar_alias: bool = True


@router.post("/api/infra/camaras/merge")
def camaras_merge_web(
    request: Request,
    body: CamaraMergeRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Fusiona dos Cámaras raíz duplicadas: la principal hereda todo lo heredable de la secundaria
    (Botellas propias, Botellas Cromo, Cables, Empalmes, Ingresos, alias y auditoría/historial) y la
    secundaria se elimina físicamente. Ver `core/services/camara_merge_service.py`."""
    username = usuario.username
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
                # Mensaje de dominio armado por el servicio para el usuario (no es texto interno).
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("camaras_merge", exc, user=username)


class CamaraMergeGrupoRequestModel(BaseModel):
    """Payload para fusionar TODAS las Cámaras de un grupo de duplicados dentro de una sola principal."""

    camara_principal_id: int
    camara_secundaria_ids: list[int]
    guardar_alias: bool = True


@router.post("/api/infra/camaras/merge-grupo")
def camaras_merge_grupo_web(
    request: Request,
    body: CamaraMergeGrupoRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Fusiona TODAS las Cámaras de un grupo de duplicados dentro de una única principal, con un solo
    click admin. Mismo mecanismo que `POST /api/infra/camaras/merge` (`unificar_camaras`), aplicado en
    loop con `session.expire_all()` entre cada llamada — ver
    `core/services/camara_merge_service.py::fusionar_grupo_camaras`."""
    username = usuario.username
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
                # Mensaje de dominio armado por el servicio para el usuario (no es texto interno).
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("camaras_merge_grupo", exc, user=username)


class CamaraMergeMasivoRequestModel(BaseModel):
    """Payload para fusionar automáticamente TODOS los grupos de Cámaras duplicadas detectados."""

    guardar_alias: bool = True


@router.post("/api/infra/camaras/merge-masivo")
def camaras_merge_masivo_web(
    request: Request,
    body: CamaraMergeMasivoRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
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
    username = usuario.username
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
                    # Mensaje de dominio armado por el servicio para el usuario (no es texto interno).
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
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("camaras_merge_masivo", exc, user=username)
