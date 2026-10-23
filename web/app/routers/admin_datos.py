# Nombre de archivo: admin_datos.py
# Ubicación de archivo: web/app/routers/admin_datos.py
# Descripción: Rutas admin de datos: worker y listener de baneos, ingesta de Cámaras y de Cromo, clientes por categoría

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Annotated, Any, List, Literal, Optional

import httpx
import psycopg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile as StarletteUploadFile

from core.parsers.lista_clientes import EXTENSIONES_LISTA as EXTENSIONES_LISTA_CLIENTES

from ..comun import (
    _CROMO_WORKER_BASE_URL,
    _CROMO_WORKER_RUN_URL,
    DB_DSN,
    INTERNAL_API_BASE_URL,
    _es_destino_slack_valido,
    _internal_api_auth_headers,
    _marcar_corrida_fallida,
    _serializar_cromo_corrida,
    _validar_csrf,
    logger,
)
from ..dependencias import UsuarioSesion, usuario_admin, usuario_sesion
from ..errores import ErrorDeDominio, error_interno, error_servicio_externo, nueva_ref, payload_de_upstream

# Todo el router exige sesión; las rutas admin agregan `usuario_admin`. Tres rutas (config de baneos,
# health del worker e ingesta de Cámaras) conservan su chequeo de rol propio para seguir respondiendo
# 403 `{"error": "Solo admin"}` en lugar del `{"detail": "Permisos insuficientes"}` de `usuario_admin`.
router = APIRouter(dependencies=[Depends(usuario_sesion)])


# ── Servicios Baneos (admin) ────────────────────────────────────

_SLACK_WORKER_HEALTH_URL = os.getenv(
    "SLACK_WORKER_HEALTH_URL", "http://slack_baneo_worker:8095/health"
)
_SLACK_WORKER_RELOAD_URL = os.getenv(
    "SLACK_WORKER_RELOAD_URL", "http://slack_baneo_worker:8095/reload"
)
_SLACK_WORKER_TRIGGER_URL = os.getenv(
    "SLACK_WORKER_TRIGGER_URL", "http://slack_baneo_worker:8095/trigger"
)
_SLACK_WORKER_CONTAINER_NAME = os.getenv(
    "SLACK_WORKER_CONTAINER_NAME", "lasfocas-slack-baneo-worker"
)


def _normalizar_destinos_slack(raw_value: str) -> str:
    """Normaliza una lista separada por comas de canales o IDs Slack."""
    destinos = [destino.strip() for destino in raw_value.split(",") if destino.strip()]
    return ",".join(destinos)


async def _reload_slack_worker_config() -> None:
    """Solicita al worker de Slack que relea su configuración en caliente."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(_SLACK_WORKER_RELOAD_URL)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("No se pudo recargar la config del slack worker: %s", exc)


@router.get("/api/admin/servicios/baneos/config", dependencies=[Depends(usuario_admin)])
async def servicios_baneos_config_json() -> JSONResponse:
    """Devuelve la configuración del worker de baneos como JSON. Usado por el SPA Vue."""
    config_data: dict[str, Any] = {
        "intervalo_horas": 4,
        "slack_channels": "",
        "activo": True,
        "hora_inicio": None,
        "ultima_ejecucion": None,
        "ultimo_error": None,
    }
    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT intervalo_horas, slack_channels, activo, ultima_ejecucion, ultimo_error, hora_inicio "
                    "FROM app.config_servicios WHERE nombre_servicio = %s",
                    ("slack_baneo_notifier",),
                )
                row = cur.fetchone()
                if row:
                    config_data = {
                        "intervalo_horas": row[0],
                        "slack_channels": row[1],
                        "activo": row[2],
                        "ultima_ejecucion": row[3].isoformat() if row[3] else None,
                        "ultimo_error": row[4],
                        "hora_inicio": row[5],
                    }
    except Exception as exc:
        logger.error("Error leyendo config_servicios: %s", exc)
    return JSONResponse(config_data)


@router.post("/api/admin/servicios/baneos")
async def servicios_baneos_update(
    request: Request,
    intervalo_horas: int = Form(...),
    slack_channels: str = Form(""),
    activo: str = Form("off"),
    hora_inicio: str = Form(""),
    csrf_token: str = Form(...),
    usuario: UsuarioSesion = Depends(usuario_sesion),
):
    """Actualiza la configuración del worker de notificaciones de baneos."""
    _, role = usuario
    if role != "admin":
        return JSONResponse({"error": "Solo admin"}, status_code=403)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    if intervalo_horas < 1:
        return JSONResponse({"error": "El intervalo debe ser al menos 1 hora"}, status_code=400)

    # hora_inicio: string vacío → NULL; entero 0-23 → valor
    hora_inicio_val: int | None = None
    if hora_inicio.strip():
        try:
            hora_inicio_val = int(hora_inicio)
            if not (0 <= hora_inicio_val <= 23):
                return JSONResponse({"error": "hora_inicio debe estar entre 0 y 23"}, status_code=400)
        except ValueError:
            return JSONResponse({"error": "hora_inicio inválida"}, status_code=400)

    destinos_normalizados = _normalizar_destinos_slack(slack_channels)

    if len(destinos_normalizados) > 512:
        return JSONResponse({"error": "Los canales no deben superar 512 caracteres"}, status_code=400)

    destinos_invalidos = [
        destino for destino in destinos_normalizados.split(",") if destino and not _es_destino_slack_valido(destino)
    ]
    if destinos_invalidos:
        return JSONResponse(
            {
                "error": (
                    "Cada destino debe ser un nombre de canal con # "
                    "o un ID de Slack tipo C/G/D..."
                )
            },
            status_code=400,
        )

    activo_bool = activo.lower() in ("on", "true", "1", "yes")

    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE app.config_servicios "
                    "SET intervalo_horas = %s, slack_channels = %s, activo = %s, hora_inicio = %s "
                    "WHERE nombre_servicio = %s",
                    (intervalo_horas, destinos_normalizados, activo_bool, hora_inicio_val, "slack_baneo_notifier"),
                )
                if cur.rowcount == 0:
                    cur.execute(
                        "INSERT INTO app.config_servicios "
                        "(nombre_servicio, intervalo_horas, slack_channels, activo, hora_inicio) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        ("slack_baneo_notifier", intervalo_horas, destinos_normalizados, activo_bool, hora_inicio_val),
                    )
                conn.commit()
    except Exception as exc:
        return error_interno("servicios_baneos_config_update", exc)

    await _reload_slack_worker_config()

    return RedirectResponse(url="/admin/Servicios/Baneos", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api/admin/servicios/baneos/worker/start", dependencies=[Depends(usuario_admin)])
async def servicios_baneos_worker_start(request: Request):
    """Inicia el contenedor del worker de baneos si está detenido."""
    body = await request.form()
    if body.get("csrf_token") != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        import docker as docker_sdk  # type: ignore[import-untyped]
        client = docker_sdk.from_env()
        try:
            container = client.containers.get(_SLACK_WORKER_CONTAINER_NAME)
            if container.status == "running":
                return JSONResponse({"status": "already_running", "msg": "El worker ya está corriendo"})
            container.start()
            container.reload()
            return JSONResponse({"status": "started", "container_status": container.status})
        except docker_sdk.errors.NotFound:
            return JSONResponse(
                {"error": f"Contenedor '{_SLACK_WORKER_CONTAINER_NAME}' no encontrado. Ejecutá ./Start para crearlo."},
                status_code=404,
            )
    except Exception as exc:
        return error_interno("servicios_baneos_worker_start", exc)


@router.post("/api/admin/servicios/baneos/trigger", dependencies=[Depends(usuario_admin)])
async def servicios_baneos_trigger(request: Request):
    """Dispara una ejecución manual inmediata del worker de baneos."""
    body = await request.form()
    if body.get("csrf_token") != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_SLACK_WORKER_TRIGGER_URL)
            return JSONResponse(resp.json(), status_code=resp.status_code)
    except httpx.ConnectError:
        return JSONResponse(
            {"error": "Worker no accesible. Verificá que esté corriendo."},
            status_code=503,
        )
    except Exception as exc:
        return error_interno("servicios_baneos_trigger", exc)


@router.get("/api/admin/servicios/baneos/health")
async def servicios_baneos_health(usuario: UsuarioSesion = Depends(usuario_sesion)):
    """Proxy al health check del worker de notificaciones de baneos."""
    _, role = usuario
    if role != "admin":
        return JSONResponse({"error": "Solo admin"}, status_code=403)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(_SLACK_WORKER_HEALTH_URL)
            return JSONResponse(resp.json(), status_code=resp.status_code)
    except httpx.ConnectError:
        return JSONResponse(
            {"status": "offline", "service": "slack_baneo_worker", "error": "Worker no accesible"},
            status_code=503,
        )
    except Exception as exc:
        logger.error("Error consultando health del worker: %s", exc)
        return JSONResponse(
            {"status": "error", "service": "slack_baneo_worker"},
            status_code=500,
        )


# ── Listener de ingresos (Socket Mode) ─────────────────────────────────

_LISTENER_SERVICIO = "slack_ingreso_listener"


@router.get("/api/admin/servicios/baneos/listener", dependencies=[Depends(usuario_admin)])
async def listener_config_get() -> JSONResponse:
    """Devuelve la configuración actual del listener de ingresos."""
    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT activo, slack_channels, ultimo_error, workflow_ids, solo_workflows "
                    "FROM app.config_servicios "
                    "WHERE nombre_servicio = %s",
                    (_LISTENER_SERVICIO,),
                )
                row = cur.fetchone()
    except Exception as exc:
        return error_interno("listener_config_get", exc)

    if row is None:
        return JSONResponse({"activo": False, "canal_id": "", "ultimo_error": None, "workflow_ids": "", "solo_workflows": False})

    return JSONResponse(
        {
            "activo": bool(row[0]),
            "canal_id": row[1] or "",
            "ultimo_error": row[2],
            "workflow_ids": row[3] or "",
            "solo_workflows": bool(row[4]),
        }
    )


@router.post("/api/admin/servicios/baneos/listener", dependencies=[Depends(usuario_admin)])
async def listener_config_post(
    request: Request,
    activo: str = Form("off"),
    canal_id: str = Form(""),
    workflow_ids: str = Form(""),
    solo_workflows: str = Form("off"),
    csrf_token: str = Form(...),
) -> JSONResponse:
    """Actualiza la configuración del listener de ingresos y recarga el worker."""
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    canal_id_norm = canal_id.strip()
    activo_bool = activo.lower() in ("on", "true", "1", "yes")
    solo_workflows_bool = solo_workflows.lower() in ("on", "true", "1", "yes")
    # Normalizar workflow_ids: separar por coma, limpiar espacios
    workflow_ids_norm = ",".join(w.strip() for w in workflow_ids.split(",") if w.strip())
    if len(workflow_ids_norm) > 512:
        return JSONResponse({"error": "workflow_ids no debe superar 512 caracteres"}, status_code=400)

    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE app.config_servicios "
                    "SET activo = %s, slack_channels = %s, workflow_ids = %s, solo_workflows = %s "
                    "WHERE nombre_servicio = %s",
                    (activo_bool, canal_id_norm, workflow_ids_norm or None, solo_workflows_bool, _LISTENER_SERVICIO),
                )
                if cur.rowcount == 0:
                    cur.execute(
                        "INSERT INTO app.config_servicios "
                        "(nombre_servicio, intervalo_horas, slack_channels, activo, workflow_ids, solo_workflows) "
                        "VALUES (%s, 0, %s, %s, %s, %s)",
                        (_LISTENER_SERVICIO, canal_id_norm, activo_bool, workflow_ids_norm or None, solo_workflows_bool),
                    )
                conn.commit()
    except Exception as exc:
        return error_interno("listener_config_update", exc)

    await _reload_slack_worker_config()

    return JSONResponse({
        "ok": True,
        "activo": activo_bool,
        "canal_id": canal_id_norm,
        "workflow_ids": workflow_ids_norm,
        "solo_workflows": solo_workflows_bool,
    })


@router.post("/api/admin/ingesta/camaras")
async def camaras_ingest_web(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
    motivo_baneo: str = Form(...),
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Ingesta masiva de cámaras desde Excel con baneo administrativo (solo admin)."""

    username, role = usuario
    if role != "admin":
        return JSONResponse({"error": "Solo admin"}, status_code=403)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF invalido"}, status_code=403)

    motivo_baneo = motivo_baneo.strip()
    if not motivo_baneo:
        return JSONResponse({"error": "El motivo de baneo no puede estar vacío"}, status_code=400)

    if not file.filename:
        return JSONResponse({"error": "Falta nombre de archivo"}, status_code=400)

    name = file.filename.lower()
    if not (name.endswith(".xlsx") or name.endswith(".xlsm")):
        return JSONResponse({"error": "Formato no soportado (use .xlsx o .xlsm)"}, status_code=415)

    try:
        content = await file.read()
        files = {
            "file": (file.filename, content, file.content_type or "application/octet-stream"),
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{INTERNAL_API_BASE_URL}/ingest/camaras",
                files=files,
                data={"motivo_baneo": motivo_baneo, "usuario": username},
                headers=_internal_api_auth_headers(),
            )

        payload: dict[str, Any]
        payload = payload_de_upstream(response, "Error en ingesta de cámaras", "camaras_ingest_proxy")

        logger.info(
            "action=camaras_ingest_proxy user=%s filename=%s status=%s",
            username,
            file.filename,
            response.status_code,
        )
        return JSONResponse(payload, status_code=response.status_code)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_servicio_externo(
            "camaras_ingest_proxy", exc, "Error en ingesta de cámaras", status_code=500, user=username
        )


class AsociarSinMatchCamarasRequestModel(BaseModel):
    """Payload para resolver a mano uno o más `IngresoSinMatch` de ingesta de cámaras."""

    caso_ids: list[int]
    camara_id: int
    motivo: str | None = None
    csrf_token: str | None = None


@router.post("/api/admin/ingesta/camaras/asociar")
async def ingesta_camaras_asociar_web(
    request: Request,
    body: AsociarSinMatchCamarasRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Resuelve a mano uno o más nombres del Excel de ingesta que no matchearon (`IngresoSinMatch`,
    origen='excel_camaras') hacia una Cámara/Botella existente: crea un alias por cada uno (para que
    futuros Excel con el mismo texto matcheen solos) y banea el grupo destino una sola vez."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    if not body.caso_ids:
        return JSONResponse({"error": "No se especificaron casos a asociar"}, status_code=400)

    motivo = (body.motivo or "").strip() or "Baneo por ingesta Excel (asociación manual)"

    try:
        from core.services.camara_ingest_service import asociar_nombres_a_camara
        from db.session import SessionLocal

        with SessionLocal() as session:
            resultado = asociar_nombres_a_camara(
                session, caso_ids=body.caso_ids, camara_id=body.camara_id, motivo=motivo, usuario=username,
            )
            if not resultado.ok:
                session.rollback()
                return JSONResponse({"error": resultado.error}, status_code=404)
            session.commit()
            return JSONResponse({
                "ok": resultado.ok,
                "camara_id": resultado.camara_id,
                "camara_nombre": resultado.camara_nombre,
                "estado_final": resultado.estado_final,
                "baneo_aplicado": resultado.baneo_aplicado,
                "alias_creados": resultado.alias_creados,
                "alias_preexistentes": resultado.alias_preexistentes,
                "casos_marcados": resultado.casos_marcados,
                "conflictos": [
                    {
                        "caso_id": c.caso_id,
                        "nombre": c.nombre,
                        "camara_actual_id": c.camara_actual_id,
                        "camara_actual_nombre": c.camara_actual_nombre,
                    }
                    for c in resultado.conflictos
                ],
                "error": resultado.error,
            })
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("ingesta_camaras_asociar", exc, user=username)


# ── Endpoints admin: ingesta de inventario FO desde Cromo Red (Etapa 4) ──────
# Contrato completo: docs/Doc Privada/ingesta_cromo.md §9. Contexto público: docs/modulo_ingesta_cromo.md.


class CromoIngestaIniciarRequest(BaseModel):
    """Payload para disparar una corrida de ingesta Cromo.

    `modo` (Task 3): `None` (default) o `"COMPLETA"` corren la secuencia de siempre + ODFs;
    `"SOLO_ODF"` corre únicamente la fase de ODFs. Validado explícitamente en el handler contra
    `_MODOS_INGESTA_VALIDOS` porque acá no hay un enum de Pydantic (mismo criterio simple que el
    resto de este payload, p.ej. `psize` contra `PSIZE_PERMITIDOS`).
    """

    csrf_token: str
    clases: List[int] | None = None
    psize: int | None = None
    max_paginas: int | None = None
    modo: Optional[str] = None


class CromoIngestaCancelarRequest(BaseModel):
    """Payload para cancelar una corrida en curso."""

    csrf_token: str


class CromoSchedulerConfigRequest(BaseModel):
    """Payload para configurar el scheduler del worker dedicado (Etapa 7)."""

    csrf_token: str
    habilitado: bool
    intervalo_horas: int
    hora_inicio: Optional[int] = None
    psize: int
    max_paginas: Optional[int] = None
    clases: List[int]


# Los valores aceptados de `CromoIngestaIniciarRequest.modo` ya no viven acá: son
# `core.services.cromo.ingesta.MODOS_INGESTA`, derivados de la tabla `MODOS_ACOTADOS` que declara
# qué fase corre cada modo. Con siete modos, una lista duplicada es una lista que se desincroniza, y
# el síntoma sería un 400 sobre un modo que el frontend sí ofrece.
#
# El import es local al handler, como el resto de los imports de Cromo en este archivo.

_CROMO_WORKER_RELOAD_URL = f"{_CROMO_WORKER_BASE_URL}/reload"
_CROMO_WORKER_HEALTH_URL = f"{_CROMO_WORKER_BASE_URL}/health"


async def _reload_cromo_worker_config() -> None:
    """Solicita al worker de Cromo que relea su configuración en caliente. Best-effort: si el worker
    está caído, el próximo `/health`/corrida manual lo va a evidenciar; no bloquea el guardado."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(_CROMO_WORKER_RELOAD_URL)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("No se pudo recargar la config del worker de Cromo: %s", exc)


@router.post("/api/admin/ingesta/cromo")
async def cromo_ingesta_iniciar_web(
    request: Request, body: CromoIngestaIniciarRequest, usuario: UsuarioSesion = Depends(usuario_admin)
) -> JSONResponse:
    """Dispara una corrida de ingesta desde Cromo Red (sólo admin). Crea la corrida acá (para devolver
    el `corrida_id` de inmediato) y delega su ejecución al worker dedicado (Etapa 7)."""
    from core.services.cromo.config import CromoConfigError, PSIZE_PERMITIDOS, get_cromo_config
    from core.services.cromo.ingesta import CLASES_BOTELLA, MODOS_INGESTA, iniciar_corrida
    from db.session import AsyncSessionLocal

    username = usuario.username
    if body.csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    if body.psize is not None and body.psize not in PSIZE_PERMITIDOS:
        return JSONResponse(
            {"error": f"psize inválido. Valores permitidos: {sorted(PSIZE_PERMITIDOS)}"}, status_code=400
        )

    if body.modo is not None and body.modo not in MODOS_INGESTA:
        return JSONResponse(
            {"error": f"modo inválido. Valores permitidos: {sorted(MODOS_INGESTA)}"}, status_code=400
        )

    try:
        cromo_config = get_cromo_config()
    except CromoConfigError as exc:
        # El detalle (variables faltantes, valores recibidos) va sólo al log, con la misma ref.
        return error_servicio_externo(
            "cromo_ingesta_iniciar", exc, "Cromo no está configurado", status_code=503, user=username
        )

    psize_final = body.psize if body.psize is not None else cromo_config.psize_default
    clases_final = tuple(body.clases) if body.clases else CLASES_BOTELLA
    # Igual mecanismo genérico y aditivo que usa `repoblacion_service.py` (ver `iniciar_corrida`):
    # sólo se agrega a `params` cuando el caller pidió explícitamente algo distinto del default, así
    # una corrida COMPLETA sin `modo` en el body sigue reproduciendo el `params` de siempre.
    params_extra = {"modo": body.modo} if body.modo not in (None, "COMPLETA") else None

    async with AsyncSessionLocal() as sesion:
        corrida = await iniciar_corrida(
            sesion,
            usuario=username,
            psize=psize_final,
            max_paginas=body.max_paginas,
            clases=clases_final,
            params_extra=params_extra,
        )
        corrida_id = corrida.id

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(_CROMO_WORKER_RUN_URL, json={"corrida_id": corrida_id, "usuario": username})
            response.raise_for_status()
    except Exception as exc:
        # El motivo queda como evento ERROR de la corrida y llega a la UI (detalle y SSE): mensaje fijo
        # con ref; el texto de la excepción va sólo al log, con la misma ref.
        ref = nueva_ref()
        motivo = f"No se pudo delegar la corrida al worker de ingesta (ref {ref})"
        logger.error("action=cromo_ingesta_iniciar_error corrida_id=%s error=%s ref=%s", corrida_id, exc, ref)
        await _marcar_corrida_fallida(corrida_id, motivo)
        return JSONResponse(
            {"error": "El worker de ingesta no está disponible. Intentá nuevamente en unos segundos."},
            status_code=503,
        )

    logger.info("action=cromo_ingesta_iniciar user=%s corrida_id=%s psize=%s", username, corrida_id, psize_final)
    return JSONResponse({"corrida_id": corrida_id}, status_code=202)


@router.get("/api/admin/ingesta/cromo/config", dependencies=[Depends(usuario_admin)])
async def cromo_scheduler_config_obtener_web() -> JSONResponse:
    """Devuelve la configuración persistida del scheduler del worker de ingesta Cromo."""
    from db.models.cromo import CromoIngestaConfig
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        config = await sesion.get(CromoIngestaConfig, 1)
    if config is None:
        return JSONResponse({"error": "Configuración no encontrada"}, status_code=404)

    return JSONResponse(
        {
            "habilitado": config.habilitado,
            "intervalo_horas": config.intervalo_horas,
            "hora_inicio": config.hora_inicio,
            "psize": config.psize,
            "max_paginas": config.max_paginas,
            "clases": config.clases,
            "ultima_ejecucion": config.ultima_ejecucion.isoformat() if config.ultima_ejecucion else None,
            "ultimo_error": config.ultimo_error,
        }
    )


@router.post("/api/admin/ingesta/cromo/config", dependencies=[Depends(usuario_admin)])
async def cromo_scheduler_config_guardar_web(request: Request, body: CromoSchedulerConfigRequest) -> JSONResponse:
    """Actualiza la configuración del scheduler y le pide al worker que la relea (best-effort)."""
    from core.services.cromo.config import PSIZE_PERMITIDOS
    from db.models.cromo import CromoIngestaConfig
    from db.session import AsyncSessionLocal

    if body.csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    if body.psize not in PSIZE_PERMITIDOS:
        return JSONResponse(
            {"error": f"psize inválido. Valores permitidos: {sorted(PSIZE_PERMITIDOS)}"}, status_code=400
        )
    if body.intervalo_horas < 1:
        return JSONResponse({"error": "El intervalo debe ser al menos 1 hora"}, status_code=400)
    if body.hora_inicio is not None and not (0 <= body.hora_inicio <= 23):
        return JSONResponse({"error": "hora_inicio debe estar entre 0 y 23"}, status_code=400)
    if not body.clases:
        return JSONResponse({"error": "Elegí al menos una clase de botella"}, status_code=400)

    async with AsyncSessionLocal() as sesion:
        config = await sesion.get(CromoIngestaConfig, 1)
        if config is None:
            return JSONResponse({"error": "Configuración no encontrada"}, status_code=404)
        config.habilitado = body.habilitado
        config.intervalo_horas = body.intervalo_horas
        config.hora_inicio = body.hora_inicio
        config.psize = body.psize
        config.max_paginas = body.max_paginas
        config.clases = body.clases
        await sesion.commit()

    await _reload_cromo_worker_config()
    return JSONResponse({"ok": True})


@router.get("/api/admin/ingesta/cromo/config/health", dependencies=[Depends(usuario_admin)])
async def cromo_scheduler_health_web() -> JSONResponse:
    """Proxy al health check del worker dedicado de ingesta Cromo."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(_CROMO_WORKER_HEALTH_URL)
            return JSONResponse(resp.json(), status_code=resp.status_code)
    except httpx.ConnectError:
        return JSONResponse(
            {"status": "offline", "service": "cromo_ingesta", "error": "Worker no accesible"}, status_code=503
        )
    except Exception as exc:
        logger.error("Error consultando health del worker de Cromo: %s", exc)
        return JSONResponse({"status": "error", "service": "cromo_ingesta"}, status_code=500)


@router.post("/api/admin/ingesta/cromo/config/trigger")
async def cromo_scheduler_trigger_web(
    request: Request, body: CromoIngestaCancelarRequest, usuario: UsuarioSesion = Depends(usuario_admin)
) -> JSONResponse:
    """Dispara una ejecución manual inmediata usando la configuración guardada ("Ejecutar ahora")."""
    username = usuario.username
    if body.csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_CROMO_WORKER_RUN_URL, json={"usuario": username})
            return JSONResponse(resp.json(), status_code=resp.status_code)
    except httpx.ConnectError:
        return JSONResponse({"error": "Worker no accesible. Verificá que esté corriendo."}, status_code=503)
    except Exception as exc:
        return error_interno("cromo_scheduler_trigger", exc, user=username)


_CROMO_ACCION_A_EVENTO_SSE = {
    "INICIO": "inicio",
    "FASE": "fase",
    "PAGINA": "pagina",
    "RESUMEN": "resumen",
    "ERROR": "error",
    "REF_COLGADA": "error",
}


async def _cromo_eventos_a_sse(corrida_id: int, ultimo_id: int):
    """Traduce `cromo_ingesta_eventos` a mensajes SSE, con heartbeat y corte al terminar la corrida.

    No emite un mensaje por cada CREADA/ACTUALIZADA/SIN_CAMBIOS/OMITIDA (serían miles) — el progreso
    granular ya viaja en el evento `pagina`. `ultimo_id` sigue avanzando sobre esas filas igual, para
    que el replay por Last-Event-ID (que sólo conoce ids de mensajes SÍ emitidos) no las repita ni las
    pierda.
    """
    from sqlalchemy import text

    from db.session import AsyncSessionLocal

    ultima_actividad = time.monotonic()
    async with AsyncSessionLocal() as sesion:
        while True:
            filas = (
                await sesion.execute(
                    text(
                        "SELECT id, n_id, clase, accion, detalle FROM app.cromo_ingesta_eventos "
                        "WHERE corrida_id = :corrida_id AND id > :ultimo_id ORDER BY id"
                    ),
                    {"corrida_id": corrida_id, "ultimo_id": ultimo_id},
                )
            ).all()

            for evento_id, n_id, clase, accion, detalle in filas:
                ultimo_id = evento_id
                tipo_sse = _CROMO_ACCION_A_EVENTO_SSE.get(accion)
                if tipo_sse is None:
                    continue
                ultima_actividad = time.monotonic()
                if accion in ("INICIO", "FASE", "PAGINA", "RESUMEN"):
                    data = detalle or "{}"
                else:
                    data = json.dumps({"n_id": n_id, "clase": clase, "detalle": detalle})
                yield f"id: {evento_id}\nevent: {tipo_sse}\ndata: {data}\n\n"

            estado_fila = (
                await sesion.execute(
                    text("SELECT estado FROM app.cromo_ingesta_corridas WHERE id = :id"), {"id": corrida_id}
                )
            ).first()
            if estado_fila is None:
                return
            if estado_fila[0] != "EN_CURSO" and not filas:
                return

            if time.monotonic() - ultima_actividad > 15:
                yield ": heartbeat\n\n"
                ultima_actividad = time.monotonic()

            await asyncio.sleep(1.0)


@router.get("/api/admin/ingesta/cromo/corridas/{corrida_id}/stream", dependencies=[Depends(usuario_admin)])
async def cromo_ingesta_stream_web(
    request: Request, corrida_id: int, desde: Optional[int] = Query(default=None, ge=0)
) -> StreamingResponse:
    """SSE de progreso de una corrida. `EventSource` no manda headers custom (salvo `Last-Event-ID`,
    que el browser agrega solo al reconectar) — por eso no hay CSRF acá; la escritura ya quedó
    protegida en el POST que dispara la corrida. Igual requiere cookie de sesión autenticada.

    `desde` (opcional) es el último id de evento ya visto: un `EventSource` NUEVO (reconexión
    manual del cliente) no puede mandar `Last-Event-ID`, así que lo pasa en la URL para no
    repetir eventos. Si vienen los dos, gana el mayor.
    """
    ultimo_id = desde or 0
    last_event_id = request.headers.get("last-event-id")
    if last_event_id and last_event_id.isdigit():
        ultimo_id = max(ultimo_id, int(last_event_id))

    return StreamingResponse(
        _cromo_eventos_a_sse(corrida_id, ultimo_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/admin/ingesta/cromo/corridas", dependencies=[Depends(usuario_admin)])
async def cromo_ingesta_historico_web(limit: int = 20, offset: int = 0) -> JSONResponse:
    """Histórico paginado de corridas, más recientes primero."""
    from sqlalchemy import func, select

    from db.models.cromo import CromoIngestaCorrida
    from db.session import AsyncSessionLocal

    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    async with AsyncSessionLocal() as sesion:
        total = (await sesion.execute(select(func.count()).select_from(CromoIngestaCorrida))).scalar_one()
        filas = (
            await sesion.execute(
                select(CromoIngestaCorrida).order_by(CromoIngestaCorrida.id.desc()).limit(limit).offset(offset)
            )
        ).scalars().all()

    return JSONResponse(
        {"total": total, "limit": limit, "offset": offset, "corridas": [_serializar_cromo_corrida(c) for c in filas]}
    )


@router.get("/api/admin/ingesta/cromo/corridas/{corrida_id}", dependencies=[Depends(usuario_admin)])
async def cromo_ingesta_detalle_web(corrida_id: int, limit: int = 200) -> JSONResponse:
    """Detalle de una corrida con sus últimos eventos (más recientes primero)."""
    from sqlalchemy import text

    from db.models.cromo import CromoIngestaCorrida
    from db.session import AsyncSessionLocal

    limit = max(1, min(limit, 1000))

    async with AsyncSessionLocal() as sesion:
        corrida = await sesion.get(CromoIngestaCorrida, corrida_id)
        if corrida is None:
            return JSONResponse({"error": "Corrida no encontrada"}, status_code=404)
        eventos = (
            await sesion.execute(
                text(
                    "SELECT id, n_id, clase, accion, detalle, created_at FROM app.cromo_ingesta_eventos "
                    "WHERE corrida_id = :id ORDER BY id DESC LIMIT :limit"
                ),
                {"id": corrida_id, "limit": limit},
            )
        ).all()

    return JSONResponse(
        {
            "corrida": _serializar_cromo_corrida(corrida),
            "eventos": [
                {
                    "id": e[0],
                    "n_id": e[1],
                    "clase": e[2],
                    "accion": e[3],
                    "detalle": e[4],
                    "created_at": e[5].isoformat() if e[5] else None,
                }
                for e in eventos
            ],
        }
    )


@router.post("/api/admin/ingesta/cromo/corridas/{corrida_id}/cancelar")
async def cromo_ingesta_cancelar_web(
    request: Request,
    corrida_id: int,
    body: CromoIngestaCancelarRequest,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Marca la corrida para detenerse: el chequeo cooperativo entre páginas la corta y la cierra
    como CANCELADA al terminar la página en curso — no la interrumpe a mitad de una página.
    """
    from db.models.cromo import CromoIngestaCorrida
    from db.session import AsyncSessionLocal

    username = usuario.username
    if body.csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    async with AsyncSessionLocal() as sesion:
        corrida = await sesion.get(CromoIngestaCorrida, corrida_id)
        if corrida is None:
            return JSONResponse({"error": "Corrida no encontrada"}, status_code=404)
        if corrida.estado != "EN_CURSO":
            return JSONResponse(
                {"error": f"La corrida ya está {corrida.estado}, no se puede cancelar"}, status_code=409
            )
        corrida.estado = "CANCELADA"
        await sesion.commit()

    logger.info("action=cromo_ingesta_cancelar user=%s corrida_id=%s", username, corrida_id)
    return JSONResponse({"ok": True})


# ─── Clientes por categoría (proxy admin a /clientes del API interno) ────────
# Todos exigen rol admin; los que escriben, además CSRF (`_validar_csrf`, misma excepción de tests
# que el resto). El usuario de la sesión viaja en `X-Usuario` para la auditoría (`actualizado_por`).
# La lista oficial acepta archivo (multipart: `file` + `categoria` + `modo` + `csrf_token`) o JSON
# (`{nombres, categoria, modo, csrf_token}`) en la misma ruta, igual que el endpoint interno.

TAMANO_MAXIMO_LISTA_CLIENTES = 5 * 1024 * 1024  # 5 MB, mismo límite que el API interno
MARGEN_MULTIPART_LISTA_CLIENTES = 64 * 1024  # boundaries y campos del form en el pre-chequeo


async def _proxy_clientes(
    method: str,
    ruta: str,
    username: str,
    accion: str,
    *,
    cuerpo: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> JSONResponse:
    """Reenvía al API interno `/clientes{ruta}` con la API key y `X-Usuario`; devuelve su respuesta."""
    kwargs: dict[str, Any] = {"headers": {**_internal_api_auth_headers(), "X-Usuario": username}}
    if cuerpo is not None:
        kwargs["json"] = cuerpo
    if files is not None:
        kwargs["files"] = files
    if data is not None:
        kwargs["data"] = data
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.request(method, f"{INTERNAL_API_BASE_URL}/clientes{ruta}", **kwargs)

        payload: Any
        payload = payload_de_upstream(response, "Error en clientes por categoría", "clientes_categoria_proxy")

        logger.info("action=%s user=%s ruta=%s status=%s", accion, username, ruta, response.status_code)
        return JSONResponse(payload, status_code=response.status_code)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_servicio_externo(
            accion, exc, "Error en clientes por categoría", status_code=500, user=username, ruta=ruta
        )


# Mismos límites que `api/app/routes/clientes.py` (lista oficial y alias de cliente).
MAXIMO_NOMBRES_LISTA_CLIENTES = 2000
LARGO_MAXIMO_NOMBRE_CLIENTE = 255


class _ClientesCsrfModel(BaseModel):
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class ClientesCategoriaRequestModel(_ClientesCsrfModel):
    cliente_ids: list[int]
    categoria: int | None = None
    automatico: bool = False


class ClientesListaRequestModel(_ClientesCsrfModel):
    nombres: list[Annotated[str, Field(max_length=LARGO_MAXIMO_NOMBRE_CLIENTE)]] = Field(
        max_length=MAXIMO_NOMBRES_LISTA_CLIENTES
    )
    categoria: int | None  # obligatoria; `null` = sin categorizar
    modo: Literal["agregar", "reemplazar"] = "agregar"


class ClientesFusionarRequestModel(_ClientesCsrfModel):
    destino_id: int
    origen_ids: list[int] = Field(min_length=1)


class ClientesAliasRequestModel(_ClientesCsrfModel):
    nombre: str = Field(max_length=LARGO_MAXIMO_NOMBRE_CLIENTE)


@router.get("/api/admin/clientes/por-categoria")
async def clientes_por_categoria_web(usuario: UsuarioSesion = Depends(usuario_admin)) -> JSONResponse:
    """Clientes agrupados por categoría — sólo admin, lectura (sin CSRF)."""
    username = usuario.username
    return await _proxy_clientes("GET", "/por-categoria", username, "clientes_por_categoria")


@router.patch("/api/admin/clientes/categoria")
async def clientes_categoria_web(
    request: Request, body: ClientesCategoriaRequestModel, usuario: UsuarioSesion = Depends(usuario_admin)
) -> JSONResponse:
    """Cambia la categoría de uno o varios clientes (`null` = sin categorizar, `automatico`)."""
    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "clientes_categoria", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    return await _proxy_clientes(
        "PATCH", "/categoria", username, "clientes_categoria", cuerpo=body.model_dump(exclude={"csrf_token"})
    )


async def _proxy_lista_clientes(request: Request, operacion: str, username: str) -> JSONResponse:
    """Previsualizar/aplicar la lista oficial, desde archivo (multipart) o JSON.

    La sesión admin ya la validó `Depends(usuario_admin)` en la ruta, antes de leer el cuerpo.
    """
    accion = f"clientes_lista_{operacion}"
    ruta = f"/lista/{operacion}"
    content_type = request.headers.get("content-type", "").lower()

    if not content_type.startswith("multipart/form-data"):
        try:
            body = ClientesListaRequestModel.model_validate(await request.json())
        except Exception:  # noqa: BLE001 — JSON inválido, campos con tipo incorrecto o fuera de límite
            return JSONResponse(
                {
                    "error": f"Pedido de lista inválido (máximo {MAXIMO_NOMBRES_LISTA_CLIENTES} nombres de hasta "
                    f"{LARGO_MAXIMO_NOMBRE_CLIENTE} caracteres)"
                },
                status_code=400,
            )
        if not _validar_csrf(request, body.csrf_token, accion, username):
            return JSONResponse({"error": "CSRF inválido"}, status_code=403)
        return await _proxy_clientes("POST", ruta, username, accion, cuerpo=body.model_dump(exclude={"csrf_token"}))

    try:
        largo_declarado = int(request.headers.get("content-length") or 0)
    except ValueError:
        largo_declarado = 0
    if largo_declarado > TAMANO_MAXIMO_LISTA_CLIENTES + MARGEN_MULTIPART_LISTA_CLIENTES:
        return JSONResponse({"error": "El archivo supera los 5 MB"}, status_code=413)
    form = await request.form()
    csrf_token = form.get("csrf_token")
    if not _validar_csrf(request, csrf_token if isinstance(csrf_token, str) else None, accion, username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    archivo = form.get("file")
    if not isinstance(archivo, StarletteUploadFile) or not archivo.filename:
        return JSONResponse({"error": "Falta el archivo de la lista"}, status_code=400)
    if not archivo.filename.lower().endswith(EXTENSIONES_LISTA_CLIENTES):
        return JSONResponse({"error": "Formato no soportado (use .xlsx, .csv o .txt)"}, status_code=415)
    contenido = await archivo.read(TAMANO_MAXIMO_LISTA_CLIENTES + 1)
    if len(contenido) > TAMANO_MAXIMO_LISTA_CLIENTES:
        return JSONResponse({"error": "El archivo supera los 5 MB"}, status_code=413)
    if form.get("categoria") is None:
        return JSONResponse({"error": "Falta categoria (use 'sin' para sin categorizar)"}, status_code=400)
    campos = {campo: str(form.get(campo)) for campo in ("categoria", "modo") if form.get(campo) is not None}
    return await _proxy_clientes(
        "POST",
        ruta,
        username,
        accion,
        files={"file": (archivo.filename, contenido, archivo.content_type or "application/octet-stream")},
        data=campos,
    )


@router.post("/api/admin/clientes/lista/previsualizar")
async def clientes_lista_previsualizar_web(
    request: Request, usuario: UsuarioSesion = Depends(usuario_admin)
) -> JSONResponse:
    """Diff de aplicar una lista oficial de clientes (no escribe)."""
    return await _proxy_lista_clientes(request, "previsualizar", usuario.username)


@router.post("/api/admin/clientes/lista/aplicar")
async def clientes_lista_aplicar_web(request: Request, usuario: UsuarioSesion = Depends(usuario_admin)) -> JSONResponse:
    """Aplica una lista oficial de clientes (el API interno la vuelve a resolver)."""
    return await _proxy_lista_clientes(request, "aplicar", usuario.username)


@router.post("/api/admin/clientes/fusionar")
async def clientes_fusionar_web(
    request: Request, body: ClientesFusionarRequestModel, usuario: UsuarioSesion = Depends(usuario_admin)
) -> JSONResponse:
    """Fusiona clientes: mueve los alias de `origen_ids` al destino."""
    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "clientes_fusionar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    return await _proxy_clientes(
        "POST", "/fusionar", username, "clientes_fusionar", cuerpo=body.model_dump(exclude={"csrf_token"})
    )


@router.post("/api/admin/clientes/{cliente_id}/alias")
async def clientes_agregar_alias_web(
    request: Request,
    cliente_id: int,
    body: ClientesAliasRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Agrega un alias (nombre alternativo) a un cliente."""
    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "clientes_alias_agregar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    return await _proxy_clientes(
        "POST", f"/{cliente_id}/alias", username, "clientes_alias_agregar", cuerpo={"nombre": body.nombre}
    )


@router.delete("/api/admin/clientes/alias/{alias_id}")
async def clientes_quitar_alias_web(
    request: Request, alias_id: int, body: _ClientesCsrfModel, usuario: UsuarioSesion = Depends(usuario_admin)
) -> JSONResponse:
    """Quita un alias de cliente (el CSRF viaja en el cuerpo JSON del DELETE)."""
    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "clientes_alias_quitar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    return await _proxy_clientes("DELETE", f"/alias/{alias_id}", username, "clientes_alias_quitar")


@router.post("/api/admin/clientes/sincronizar")
async def clientes_sincronizar_web(
    request: Request, body: _ClientesCsrfModel, usuario: UsuarioSesion = Depends(usuario_admin)
) -> JSONResponse:
    """Sincronización global de categorías de clientes → servicios."""
    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "clientes_sincronizar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)
    return await _proxy_clientes("POST", "/sincronizar", username, "clientes_sincronizar")
