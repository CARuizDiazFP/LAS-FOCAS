# Nombre de archivo: servicios.py
# Ubicación de archivo: web/app/routers/servicios.py
# Descripción: Rutas de Servicios: búsqueda y categorías, rutas y tracking, ODF de servicios, camino óptico y empalmes

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..comun import (
    INTERNAL_API_BASE_URL,
    _encolar_arbitro,
    _internal_api_auth_headers,
    _serializar_pelo_semilla,
    _serialize_camara_ingreso,
    _servicio_existe,
    _validar_csrf,
    logger,
)
from ..dependencias import UsuarioSesion, usuario_admin, usuario_sesion
from ..errores import (
    Conflicto,
    ErrorDeDominio,
    NoEncontrado,
    error_interno,
    error_servicio_externo,
    payload_de_upstream,
)

router = APIRouter(dependencies=[Depends(usuario_sesion)])


def _find_servicio_por_identificador_web(session: Any, servicio_id: str) -> Optional[Any]:
    """Resuelve un `Servicio` por identificador flexible: `servicio_id`,
    `numero_primer_servicio` o `numero_linea`. Lookup compartido por
    `get_servicio_rutas_web` y `get_servicio_odfs` (ambos reciben el mismo tipo
    de identificador desde el frontend)."""

    from db.models.infra import Servicio
    from sqlalchemy import or_

    return (
        session.query(Servicio)
        .filter(
            or_(
                Servicio.servicio_id == servicio_id,
                Servicio.numero_primer_servicio == servicio_id,
                Servicio.numero_linea == servicio_id,
            )
        )
        .first()
    )


@router.get("/api/infra/servicios/{servicio_id}/rutas")
async def get_servicio_rutas_web(
    servicio_id: str,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Obtiene las rutas de un servicio para el wizard de baneo."""

    username, _ = usuario

    try:
        from db.session import SessionLocal

        with SessionLocal() as session:
            servicio = _find_servicio_por_identificador_web(session, servicio_id)

            if not servicio:
                return JSONResponse(
                    {"error": f"Servicio {servicio_id} no encontrado"},
                    status_code=404
                )
            
            rutas_info = []
            for ruta in servicio.rutas:
                rutas_info.append({
                    "id": ruta.id,
                    "nombre": ruta.nombre,
                    "tipo": ruta.tipo.value if ruta.tipo else "PRINCIPAL",
                    "hash_contenido": ruta.hash_contenido,
                    "empalmes_count": len(ruta.empalmes),
                    "activa": bool(ruta.activa),
                    "created_at": ruta.created_at.isoformat() if ruta.created_at else None,
                    "nombre_archivo_origen": ruta.nombre_archivo_origen,
                })
            
            logger.info(
                "action=get_servicio_rutas user=%s servicio_id=%s rutas=%d",
                username,
                servicio_id,
                len(rutas_info),
            )
            
            return JSONResponse({
                "status": "ok",
                "servicio_id": servicio.servicio_id,
                "servicio_db_id": servicio.id,
                "cliente": servicio.cliente,
                "rutas": rutas_info,
                "total_rutas": len(rutas_info),
            })
            
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("get_servicio_rutas", exc, user=username, servicio_id=servicio_id)


@router.get("/api/infra/servicios/{servicio_id}/odfs")
async def get_servicio_odfs(
    servicio_id: str,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Obtiene las ODFs/empalmes de tracking de todas las rutas de un servicio, para
    la vista de Detalle de Servicio.

    Este sistema es independiente del submódulo Cromo Red (`/infra/odfs`): las ODFs
    acá salen del archivo de tracking de ruta subido manualmente para el servicio
    (`RutaServicio.raw_file_content`), no de la ingesta automática de Cromo.

    `es_transito` (si un empalme es un punto de distribución tipo ODF) se deriva
    SIEMPRE en vivo parseando `raw_file_content` con `parse_tracking(...)` —
    la columna persistida `Empalme.es_transito` no es confiable: sólo se setea
    consistentemente en un camino de resolución de empalmes
    (`_action_confirm_upgrade` en `core/services/infra_service.py`); el resto de
    caminos que crean/reutilizan un `Empalme` (`_get_or_create_empalme`) la dejan
    en `False` por default aunque el empalme sea realmente un tránsito. En cambio
    `Empalme.camara_id` sí se setea consistentemente en todos los caminos, por eso
    es seguro usarla para enriquecer cada empalme con nombre/estado de cámara.
    """

    username, _ = usuario

    try:
        from core.parsers.tracking_parser import parse_tracking
        from db.models.infra import Empalme
        from db.session import SessionLocal
        from sqlalchemy.orm import joinedload

        with SessionLocal() as session:
            servicio = _find_servicio_por_identificador_web(session, servicio_id)

            if not servicio:
                return JSONResponse(
                    {"error": f"Servicio {servicio_id} no encontrado"},
                    status_code=404,
                )

            rutas_info: list[dict[str, Any]] = []
            tracking_ids: set[str] = set()

            for ruta in servicio.rutas:
                ruta_tipo = ruta.tipo.value if ruta.tipo else "PRINCIPAL"

                if not ruta.raw_file_content:
                    rutas_info.append(
                        {
                            "ruta_id": ruta.id,
                            "ruta_nombre": ruta.nombre,
                            "ruta_tipo": ruta_tipo,
                            "activa": bool(ruta.activa),
                            "sin_tracking": True,
                            "terminal_a": None,
                            "terminal_b": None,
                            "transitos_count": 0,
                            "empalmes_count": 0,
                            "empalmes": [],
                        }
                    )
                    continue

                parsed = parse_tracking(ruta.raw_file_content, ruta.nombre_archivo_origen or "")
                empalmes_parseados = parsed.get_empalmes()

                for entry in empalmes_parseados:
                    if entry.empalme_id:
                        tracking_ids.add(f"{servicio.servicio_id}_{entry.empalme_id}")

                rutas_info.append(
                    {
                        "ruta_id": ruta.id,
                        "ruta_nombre": ruta.nombre,
                        "ruta_tipo": ruta_tipo,
                        "activa": bool(ruta.activa),
                        "sin_tracking": False,
                        "terminal_a": (
                            {"odf_id": parsed.terminal_a[0], "conector": parsed.terminal_a[1]}
                            if parsed.terminal_a
                            else None
                        ),
                        "terminal_b": (
                            {"odf_id": parsed.terminal_b[0], "conector": parsed.terminal_b[1]}
                            if parsed.terminal_b
                            else None
                        ),
                        "transitos_count": parsed.transitos_count,
                        "empalmes_count": parsed.empalmes_count,
                        # Placeholder temporal con las entries parseadas en crudo — se
                        # reemplaza por su forma serializable abajo, una vez resuelto el
                        # enriquecimiento de cámara en batch (evita re-parsear el archivo).
                        "empalmes": empalmes_parseados,
                    }
                )

            # Enriquecimiento de cámara en UNA sola query batched (no N+1): se junta acá
            # el universo completo de tracking_empalme_id candidatos de todas las rutas.
            empalmes_db_por_tracking_id: dict[str, Any] = {}
            if tracking_ids:
                empalmes_db = (
                    session.query(Empalme)
                    .options(joinedload(Empalme.camara))
                    .filter(Empalme.tracking_empalme_id.in_(tracking_ids))
                    .all()
                )
                empalmes_db_por_tracking_id = {e.tracking_empalme_id: e for e in empalmes_db}

            # Bug real (2026-08-31, ticket duplicidad Buscador/ODFs): `transitos_count`/
            # `empalmes_count` son por-ruta, así que sumarlos entre rutas sobrecuenta cuando dos
            # rutas del mismo servicio (ej. "Principal" y "Principal - Pelo 2", dos pelos del MISMO
            # cable físico) atraviesan el mismo empalme — el usuario lo detectó en pantalla: "4
            # ODF(s)" cuando en realidad eran 2 ODFs físicas repetidas en ambas rutas. `empalme_id`
            # es la identidad estable de un empalme para este servicio (mismo criterio que
            # `tracking_id = f"{servicio.servicio_id}_{entry.empalme_id}"` de más arriba), así que
            # los totales ahora cuentan `empalme_id` DISTINTOS entre todas las rutas, no ocurrencias.
            odfs_distintas: set[str] = set()
            empalmes_distintos: set[str] = set()
            for ruta_info in rutas_info:
                if ruta_info["sin_tracking"]:
                    continue

                empalmes_serializados = []
                for entry in ruta_info["empalmes"]:
                    if entry.empalme_id:
                        empalmes_distintos.add(entry.empalme_id)
                        if entry.es_transito:
                            odfs_distintas.add(entry.empalme_id)
                    tracking_id = (
                        f"{servicio.servicio_id}_{entry.empalme_id}" if entry.empalme_id else None
                    )
                    empalme_db = empalmes_db_por_tracking_id.get(tracking_id) if tracking_id else None
                    camara = empalme_db.camara if empalme_db else None
                    empalmes_serializados.append(
                        {
                            "empalme_id": entry.empalme_id,
                            "descripcion": entry.empalme_descripcion,
                            "es_transito": entry.es_transito,
                            "camara_id": camara.id if camara else None,
                            "camara_nombre": camara.nombre if camara else None,
                            "camara_estado": camara.estado.value if camara and camara.estado else None,
                        }
                    )
                ruta_info["empalmes"] = empalmes_serializados

            total_odfs = len(odfs_distintas)
            total_empalmes = len(empalmes_distintos)

            logger.info(
                "action=get_servicio_odfs user=%s servicio_id=%s rutas=%d total_odfs=%d total_empalmes=%d",
                username,
                servicio_id,
                len(rutas_info),
                total_odfs,
                total_empalmes,
            )

            return JSONResponse(
                {
                    "status": "ok",
                    "servicio_id": servicio.servicio_id,
                    "total_odfs": total_odfs,
                    "total_empalmes": total_empalmes,
                    "rutas": rutas_info,
                }
            )

    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("get_servicio_odfs", exc, user=username, servicio_id=servicio_id)


@router.get("/api/infra/servicios/{servicio_id}/ingresos")
async def get_servicio_ingresos_web(
    servicio_id: str,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Obtiene los registros de ingreso de técnico (Slack) a las cámaras que atraviesa un
    servicio, para la vista de Detalle de Servicio.

    Las cámaras del servicio se resuelven vía `ProtectionService.get_camaras_for_servicio`
    (ya combina el camino legado `RutaServicio`/`Empalme` con Cromo en una sola llamada) para
    no reimplementar esa resolución acá.
    """

    username, _ = usuario

    try:
        from core.services.protection_service import ProtectionService
        from db.models.infra import Ingreso
        from db.session import SessionLocal
        from sqlalchemy import nullslast

        with SessionLocal() as session:
            servicio = _find_servicio_por_identificador_web(session, servicio_id)

            if not servicio:
                return JSONResponse(
                    {"error": f"Servicio {servicio_id} no encontrado"},
                    status_code=404,
                )

            camaras = ProtectionService(session).get_camaras_for_servicio(servicio.servicio_id)
            camaras_por_id = {camara.id: camara for camara in camaras}
            camara_ids = list(camaras_por_id.keys())

            ingresos_db: list[Any] = []
            if camara_ids:
                ingresos_db = (
                    session.query(Ingreso)
                    .filter(Ingreso.camara_id.in_(camara_ids))
                    .order_by(nullslast(Ingreso.fecha_inicio.desc()))
                    .limit(100)
                    .all()
                )

            ingresos_info = []
            for item in ingresos_db:
                serializado = _serialize_camara_ingreso(item)
                camara = camaras_por_id.get(item.camara_id)
                serializado["camara_id"] = item.camara_id
                serializado["camara_nombre"] = camara.nombre if camara else None
                ingresos_info.append(serializado)

            logger.info(
                "action=get_servicio_ingresos user=%s servicio_id=%s total=%d",
                username,
                servicio_id,
                len(ingresos_info),
            )

            return JSONResponse(
                {
                    "status": "ok",
                    "servicio_id": servicio.servicio_id,
                    "total": len(ingresos_info),
                    "ingresos": ingresos_info,
                }
            )

    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("get_servicio_ingresos", exc, user=username, servicio_id=servicio_id)


_PATRON_ODF_EN_LINEA = re.compile(r"(O-[\w-]+):\s*(\d+)")


def _punta_desde_parseo(punta: Any) -> Optional[dict[str, str]]:
    """Punta A/B a partir del objeto que devuelve `parse_tracking` (None si no hay punta)."""
    if not punta:
        return None
    return {
        "sitio": punta.sitio_descripcion or "",
        "identificador": punta.identificador_fisico or "",
        "conector": punta.pelo_conector or "",
    }


def _punta_desde_json(punta: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Punta A/B a partir del dict guardado en `contenido_original` (None si no hay punta)."""
    if not punta:
        return None
    return {
        "sitio": punta.get("sitio_descripcion", ""),
        "identificador": punta.get("identificador_fisico", ""),
        "conector": punta.get("pelo_conector", ""),
    }


def _punta_por_odf_de_tramos(entries: Any) -> Optional[dict[str, str]]:
    """Punta deducida del primer tramo con nombre de cable: sitio:conector tipo `O-xxxxx: n`.

    Corta en el primer tramo con cable aunque su línea no coincida con el patrón.
    """
    for entry in entries:
        if entry.tipo == "tramo" and entry.cable_nombre:
            coincidencia = _PATRON_ODF_EN_LINEA.search(entry.raw_line)
            if coincidencia:
                return {"sitio": coincidencia.group(1), "identificador": "", "conector": coincidencia.group(2)}
            return None
    return None


def _entradas_desde_parseo(entries: Any) -> list[dict[str, Any]]:
    """Secuencia cámara-cable a partir de las entradas de `parse_tracking`."""
    resultado: list[dict[str, Any]] = []
    for entry in entries:
        if entry.tipo == "empalme":
            resultado.append(
                {"tipo": "camara", "descripcion": entry.empalme_descripcion or "", "empalme_id": entry.empalme_id}
            )
        elif entry.tipo == "tramo":
            resultado.append(
                {"tipo": "cable", "nombre": entry.cable_nombre or "", "atenuacion_db": entry.atenuacion_db}
            )
    return resultado


def _entradas_desde_json(entries: Any) -> list[dict[str, Any]]:
    """Secuencia cámara-cable a partir de las entradas del JSON guardado."""
    resultado: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("tipo") == "empalme":
            resultado.append(
                {
                    "tipo": "camara",
                    "descripcion": entry.get("empalme_descripcion", ""),
                    "empalme_id": entry.get("empalme_id"),
                }
            )
        elif entry.get("tipo") == "tramo":
            resultado.append(
                {
                    "tipo": "cable",
                    "nombre": entry.get("cable_nombre", ""),
                    "atenuacion_db": entry.get("atenuacion_db"),
                }
            )
    return resultado


def _tracking_desde_raw(ruta: Any) -> dict[str, Any]:
    """Parsea el TXT original (`raw_file_content`); las puntas caen al ODF de los tramos si faltan."""
    from core.parsers.tracking_parser import parse_tracking

    parsed = parse_tracking(ruta.raw_file_content, ruta.nombre_archivo_origen or "")
    punta_a = _punta_desde_parseo(parsed.punta_a)
    punta_b = _punta_desde_parseo(parsed.punta_b)
    if not punta_a and parsed.entries:
        punta_a = _punta_por_odf_de_tramos(parsed.entries)
    if not punta_b and parsed.entries:
        punta_b = _punta_por_odf_de_tramos(reversed(parsed.entries))
    return {
        "tracking": _entradas_desde_parseo(parsed.entries),
        "punta_a": punta_a,
        "punta_b": punta_b,
        "transitos_count": parsed.transitos_count,
    }


def _tracking_desde_json(ruta: Any) -> dict[str, Any]:
    """Lee el JSON guardado en `contenido_original`; un JSON inválido se ignora (tracking vacío)."""
    try:
        parsed = json.loads(ruta.contenido_original)
        entries = parsed.get("entries", [])
        punta_a = _punta_desde_json(parsed.get("punta_a"))
        punta_b = _punta_desde_json(parsed.get("punta_b"))
        tracking = _entradas_desde_json(entries)
    except json.JSONDecodeError:
        return {"tracking": [], "punta_a": None, "punta_b": None, "transitos_count": None}
    return {"tracking": tracking, "punta_a": punta_a, "punta_b": punta_b, "transitos_count": None}


def _tracking_desde_empalmes(ruta: Any) -> list[dict[str, Any]]:
    """Secuencia de cámaras a partir de los empalmes de la base."""
    return [
        {
            "tipo": "camara",
            "descripcion": empalme.camara.nombre if empalme.camara else "Sin cámara",
            "empalme_id": empalme.tracking_empalme_id,
        }
        for empalme in ruta.empalmes
    ]


def _armar_tracking_de_ruta(ruta: Any) -> dict[str, Any]:
    """Tracking de la ruta: TXT original, si no JSON guardado, y si queda vacío los empalmes."""
    if ruta.raw_file_content:
        datos = _tracking_desde_raw(ruta)
    elif ruta.contenido_original:
        datos = _tracking_desde_json(ruta)
    else:
        datos = {"tracking": [], "punta_a": None, "punta_b": None, "transitos_count": None}
    if not datos["tracking"]:
        datos["tracking"] = _tracking_desde_empalmes(ruta)
    return datos


@router.get("/api/infra/rutas/{ruta_id}/tracking")
async def get_ruta_tracking(
    ruta_id: int,
) -> JSONResponse:
    """Obtiene el tracking completo de una ruta (secuencia cámara-cable-cámara)."""

    try:
        from db.models.infra import RutaServicio
        from db.session import SessionLocal

        with SessionLocal() as session:
            ruta = session.query(RutaServicio).filter(RutaServicio.id == ruta_id).first()

            if not ruta:
                return JSONResponse({"error": "Ruta no encontrada"}, status_code=404)

            datos = _armar_tracking_de_ruta(ruta)
            return JSONResponse({
                "status": "ok",
                "ruta_id": ruta.id,
                "servicio_id": ruta.servicio.servicio_id,
                "ruta_nombre": ruta.nombre,
                "ruta_tipo": ruta.tipo.value,
                **datos,
            })

    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("get_ruta_tracking", exc, ruta_id=ruta_id)


@router.get("/api/infra/rutas/{ruta_id}/download")
async def download_ruta_tracking(
    ruta_id: int,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> Response:
    """Descarga el tracking de una ruta como archivo TXT."""
    
    username, _ = usuario
    
    try:
        from db.models.infra import RutaServicio
        from db.session import SessionLocal
        import json as json_module
        
        with SessionLocal() as session:
            ruta = session.query(RutaServicio).filter(RutaServicio.id == ruta_id).first()
            
            if not ruta:
                return JSONResponse({"error": "Ruta no encontrada"}, status_code=404)
            
            # Reconstruir formato de tracking TXT
            servicio_id = ruta.servicio.servicio_id if ruta.servicio else "unknown"
            lines = [
                f"# Tracking de Ruta - Servicio {servicio_id}",
                f"# Ruta: {ruta.nombre} ({ruta.tipo.value if ruta.tipo else 'PRINCIPAL'})",
                f"# Exportado: {__import__('datetime').datetime.now().isoformat()}",
                "",
            ]
            
            # Intentar usar contenido original si existe
            if ruta.contenido_original:
                try:
                    parsed = json_module.loads(ruta.contenido_original)
                    entries = parsed.get("entries", [])
                    
                    for entry in entries:
                        if entry.get("tipo") == "empalme":
                            desc = entry.get("empalme_descripcion", "Empalme")
                            lines.append(f"EMPALME: {desc}")
                        elif entry.get("tipo") == "tramo":
                            cable = entry.get("cable_nombre", "Cable")
                            atten = entry.get("atenuacion_db", 0)
                            lines.append(f"  └─ CABLE: {cable} ({atten} dB)")
                except json_module.JSONDecodeError:
                    pass
            
            # Si no hay contenido original, usar empalmes de la ruta
            if len(lines) <= 4:
                for empalme in ruta.empalmes:
                    if empalme.camara:
                        lines.append(f"CAMARA: {empalme.camara.nombre or empalme.camara.direccion or 'Sin nombre'}")
                    lines.append(f"  └─ EMPALME: {empalme.descripcion or empalme.nombre or 'Empalme'}")
            
            content = "\\n".join(lines)
            filename = f"tracking_{servicio_id}_{ruta.nombre.replace(' ', '_')}.txt"
            
            logger.info("action=download_tracking user=%s ruta_id=%d servicio=%s", username, ruta_id, servicio_id)
            
            return Response(
                content=content,
                media_type="text/plain; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                }
            )
            
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("download_tracking", exc, ruta_id=ruta_id)


@router.get("/api/infra/tracking/{ruta_id}/download")
async def download_tracking_alias(
    ruta_id: int,
) -> Response:
    """Alias de /api/infra/rutas/{ruta_id}/download para compatibilidad."""
    
    try:
        from db.models.infra import RutaServicio
        from db.session import SessionLocal
        
        with SessionLocal() as session:
            ruta = session.query(RutaServicio).filter(RutaServicio.id == ruta_id).first()
            
            if not ruta:
                return JSONResponse({"error": "Ruta no encontrada"}, status_code=404)
            
            # Usar raw_file_content si existe
            if ruta.raw_file_content:
                filename = ruta.nombre_archivo_origen or f"tracking_ruta_{ruta_id}.txt"
                
                return Response(
                    content=ruta.raw_file_content,
                    media_type="text/plain; charset=utf-8",
                    headers={
                        "Content-Disposition": f'attachment; filename="{filename}"',
                    }
                )
            
            # No hay contenido original
            return JSONResponse(
                {"error": "Archivo original no disponible para esta ruta"},
                status_code=404
            )
            
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("download_tracking_alias", exc, ruta_id=ruta_id)


@router.post("/api/servicios/ingest")
async def servicios_ingest_web(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Ingesta de servicios SLA (solo admin) delegada a la API interna."""

    # "Solo admin" con su propio 403 (no `usuario_admin`): el mensaje no cambia.
    username, role = usuario
    if role != "admin":
        return JSONResponse({"error": "Solo admin"}, status_code=403)
    if csrf_token != request.session.get("csrf"):
        return JSONResponse({"error": "CSRF invalido"}, status_code=403)
    if not file.filename:
        return JSONResponse({"error": "Falta nombre de archivo"}, status_code=400)

    try:
        content = await file.read()
        files = {
            "file": (file.filename, content, file.content_type or "application/octet-stream"),
        }
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{INTERNAL_API_BASE_URL}/servicios/ingest",
                files=files,
                headers=_internal_api_auth_headers(),
            )

        payload: dict[str, Any]
        payload = payload_de_upstream(response, "Error en ingesta", "servicios_ingest_proxy")

        logger.info(
            "action=servicios_ingest_proxy user=%s filename=%s status=%s",
            username,
            file.filename,
            response.status_code,
        )
        return JSONResponse(payload, status_code=response.status_code)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("servicios_ingest_proxy", exc, user=username)


def _serializar_extremos_sin_odf(extremos: Any) -> list[dict[str, Any]]:
    """`[{extremo, nodo, equipo}, ...]` a partir de una secuencia de `ExtremoUltimaMilla` (listado,
    dataclass) o de filas `ServicioEquipoUltimaMilla` (detalle, ORM) — ambas exponen los mismos tres
    atributos, así que sirve para las dos. Serializa TODOS los extremos, nunca sólo el ganador: es
    requisito de diseño del plan que la prioridad de categorización nunca le oculte información al
    operador (ver `ServicioSinOdf.extremos` en `core/services/cromo/servicios_sin_odf.py`)."""
    return [{"extremo": e.extremo, "nodo": e.nodo, "equipo": e.equipo} for e in extremos]


async def _obtener_servicio_categorizado(sesion: Any, servicio_id: int) -> Optional[dict[str, Any]]:
    """Carga el Servicio (PK `app.servicios.id`) + sus extremos de última milla y les aplica la
    categorización PURA de `core/services/cromo/servicios_sin_odf.py` (`categorizar_extremos`,
    `subcategoria_sin_senal_prov`) — puro wiring de datos, la decisión de categoría/subcategoría
    siempre la toma ese módulo, nunca esta función. `None` si el Servicio no existe.

    La usan tanto `GET .../sugerencia` (mostrarle la causa al operador) como `POST .../asociar`
    (persistir la MISMA `categoria_causa`/`subcategoria` que el operador vio en el detalle, no
    recalcularla de otra forma en cada endpoint)."""
    from sqlalchemy import select

    from core.services.cromo.servicios_sin_odf import (
        CATEGORIA_SIN_SENAL_PROV,
        categorizar_extremos,
        subcategoria_sin_senal_prov,
    )
    from db.models.infra import Servicio, ServicioEquipoUltimaMilla

    servicio = (
        await sesion.execute(select(Servicio).where(Servicio.id == servicio_id))
    ).scalar_one_or_none()
    if servicio is None:
        return None

    extremos = list(
        (
            await sesion.execute(
                select(ServicioEquipoUltimaMilla)
                .where(ServicioEquipoUltimaMilla.servicio_id == servicio_id)
                .order_by(ServicioEquipoUltimaMilla.extremo)
            )
        ).scalars()
    )

    categoria_causa, _subcategoria_barata, _nodo, _equipo, indice_ganador = categorizar_extremos(
        [(e.equipo, e.nodo) for e in extremos]
    )
    subcategoria = None
    if categoria_causa == CATEGORIA_SIN_SENAL_PROV:
        subcategoria = await subcategoria_sin_senal_prov(sesion, servicio_id)

    return {
        "servicio": servicio,
        "extremos": extremos,
        "categoria_causa": categoria_causa,
        "subcategoria": subcategoria,
        "indice_extremo_categorizado": indice_ganador,
    }


async def _senal_direccion_contra_odf(sesion: Any, direccion_prov: Optional[str], odf_n_id: int) -> Any:
    """Devuelve el `SenalDireccion` de comparar `direccion_prov` contra la calle/altura de la ODF
    `odf_n_id` (`NO_SE_PUDO_COMPARAR` si esa ODF no tiene fila en `cromo_odfs`) — wiring sobre
    `core/services/cromo/direccion_comparacion.py`, cero lógica de comparación propia acá."""
    from sqlalchemy import select

    from core.services.cromo.direccion_comparacion import comparar_direccion_prov_vs_odf
    from db.models.cromo import CromoOdf

    fila = (
        await sesion.execute(select(CromoOdf.calle, CromoOdf.altura).where(CromoOdf.n_id == odf_n_id))
    ).first()
    return comparar_direccion_prov_vs_odf(direccion_prov, fila.calle if fila else None, fila.altura if fila else None)


async def _existe_odf(sesion: Any, odf_n_id: int) -> bool:
    """`True` si `odf_n_id` tiene fila PROPIA en `app.cromo_odfs` — mismo criterio ESTRICTO que ya
    exige `crear_override` antes de insertar un override (ver `_SQL_EXISTE_ODF` en
    `core/services/cromo/servicio_odf_override_service.py`). Ese helper es privado de otro módulo,
    así que acá se repite la misma pregunta vía el ORM en vez de importarlo — usado por
    `GET .../senal-direccion` (Task 6, fix round 1) para distinguir 404 "ODF no existe" de
    `NO_SE_PUDO_COMPARAR` "ODF existe pero sin calle/altura cargada", algo que
    `_senal_direccion_contra_odf` no puede distinguir por sí solo (colapsa las dos situaciones al
    mismo resultado)."""
    from sqlalchemy import select

    from db.models.cromo import CromoOdf

    fila = (await sesion.execute(select(CromoOdf.n_id).where(CromoOdf.n_id == odf_n_id))).first()
    return fila is not None


@router.get("/api/admin/infra/servicios-odf/listado", dependencies=[Depends(usuario_admin)])
async def servicios_sin_odf_listado_web(
    categoria: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> JSONResponse:
    """Listado paginado de Servicios Activos verificables sin ODF Cromo resuelta, con causa
    probable ya categorizada por fila — barata (sin sugerencia de ODF ni subcategoría de detalle,
    eso corre sólo bajo demanda en `GET .../sugerencia`, para no hacer N+1 en el paginado). Ver
    `core/services/cromo/servicios_sin_odf.py::listar_servicios_sin_odf`.

    Devuelve además `conteos_por_categoria` (las 4 categorías, sobre el mismo conjunto filtrado por
    `q` y ANTES del filtro `categoria`): son los chips de la UI, calculados en la misma pasada que
    el listado para que el frontend no tenga que pedir un request `limit=0` por categoría.

    `offset`/`limit` negativos o una `categoria` desconocida levantan `ValueError` en el servicio —
    se mapean acá a 400, nunca a un 500 ni a una página silenciosamente incorrecta."""
    from core.services.cromo.camino_optico_service import contar_semillas_por_servicio
    from core.services.cromo.servicios_sin_odf import listar_servicios_sin_odf
    from db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as sesion:
            resultado = await listar_servicios_sin_odf(
                sesion, limit=limit, offset=offset, categoria=categoria, q=q
            )
            # Una query batcheada para toda la página: le dice a la UI si el botón de camino va
            # o no, sin un request por tarjeta y sin tocar la query de detección.
            semillas_por_servicio = await contar_semillas_por_servicio(
                sesion, [item.id for item in resultado.items]
            )
    except ValueError as exc:
        # Mensaje de validación armado por el servicio (categoría/offset/limit): misma respuesta 400.
        raise ErrorDeDominio(str(exc)) from exc

    return JSONResponse(
        {
            "total": resultado.total,
            "limit": resultado.limit,
            "offset": resultado.offset,
            # Los 4 conteos de los chips viajan con el listado: el frontend NO tiene que pedir un
            # `limit=0` por categoría (eso re-corría la query completa del universo 4 veces más,
            # en paralelo con el listado, para devolver 4 enteros que esta misma pasada ya calculó).
            "conteos_por_categoria": resultado.conteos_por_categoria,
            "items": [
                {
                    "id": item.id,
                    "servicio_id": item.servicio_id,
                    "numero_primer_servicio": item.numero_primer_servicio,
                    "nombre_cliente": item.nombre_cliente,
                    "categoria_causa": item.categoria_causa,
                    "subcategoria": item.subcategoria,
                    "nodo": item.nodo,
                    "equipo": item.equipo,
                    "extremos": _serializar_extremos_sin_odf(item.extremos),
                    "indice_extremo_categorizado": item.indice_extremo_categorizado,
                    # 0 = `/path` no tiene input posible para este Servicio (el 77% del universo).
                    "pelos_semilla": semillas_por_servicio.get(item.id, 0),
                }
                for item in resultado.items
            ],
        }
    )


@router.get("/api/admin/infra/servicios-odf/{servicio_id}/sugerencia", dependencies=[Depends(usuario_admin)])
async def servicios_sin_odf_sugerencia_web(servicio_id: int) -> JSONResponse:
    """Detalle de causa + sugerencia de ODF para UN Servicio sin ODF: categoría/subcategoría
    completas (incluida la cascada `subcategoria_sin_senal_prov` on-demand), AMBOS extremos de
    última milla + el índice del que ganó la categorización, dirección PROV cruda del Servicio, y —
    sólo para `OLT_PON_COMPARTIDO` — la sugerencia de ODF de un hermano resuelto más la
    `senal_direccion` calculada contra esa ODF sugerida. Sólo lectura e informativo: NADA se
    auto-aplica acá, el operador confirma vía `POST .../asociar`. 404 si `servicio_id` no existe.

    Admin (`usuario_admin`), igual que los otros 3 endpoints del gestor. Antes era `_require_auth` "porque
    es consulta", citando `odfs/{id}/conectores` como precedente, y eso era un guard más ancho que
    no habilitaba ningún caso de uso: la única ruta de UI que lo consume
    (`/admin/servicios/viewer/ServiciosSinOdf`) es `meta: { requiresAdmin: true }`, así que sólo
    ampliaba la superficie. Y no es el mismo caso que el precedente: éste es el ÚNICO endpoint de
    la app del SPA que serializa `Servicio.direccion` (el domicilio del cliente) —
    `odfs/{id}/conectores` expone `nombre_cliente` pero no la dirección — y devuelve además el
    `nodo`/`equipo` de última milla, o sea topología de red. Con `_require_auth`, un usuario con rol
    `user` podía iterar `servicio_id` y cosechar número + cliente + domicilio + topología de los
    14.147 Servicios, mientras el listado, que muestra MENOS, sí exigía admin."""
    from core.services.cromo.servicios_sin_odf import (
        CATEGORIA_OLT_PON_COMPARTIDO,
        sugerencia_odf_para_servicio,
    )
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        detalle = await _obtener_servicio_categorizado(sesion, servicio_id)
        if detalle is None:
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)

        servicio = detalle["servicio"]
        sugerencia_payload = None
        senal_direccion = None
        if detalle["categoria_causa"] == CATEGORIA_OLT_PON_COMPARTIDO:
            sugerencia = await sugerencia_odf_para_servicio(sesion, servicio_id)
            if sugerencia is not None:
                # `cantidad_candidatas` NO es decorativo: el frontend lo necesita para no
                # presentar como única una elección entre 2-4 ODFs candidatas (88 de 1057
                # Servicios OLT con sugerencia tienen más de una, medido real 2026-09-09).
                sugerencia_payload = {
                    "odf_n_id": sugerencia.odf_n_id,
                    "nombre": sugerencia.nombre,
                    "cantidad_candidatas": sugerencia.cantidad_candidatas,
                }
                senal = await _senal_direccion_contra_odf(sesion, servicio.direccion, sugerencia.odf_n_id)
                senal_direccion = senal.value

    return JSONResponse(
        {
            "id": servicio.id,
            "servicio_id": servicio.servicio_id,
            "nombre_cliente": servicio.nombre_cliente,
            "direccion": servicio.direccion,
            "categoria_causa": detalle["categoria_causa"],
            "subcategoria": detalle["subcategoria"],
            "extremos": _serializar_extremos_sin_odf(detalle["extremos"]),
            "indice_extremo_categorizado": detalle["indice_extremo_categorizado"],
            "sugerencia": sugerencia_payload,
            "senal_direccion": senal_direccion,
        }
    )


@router.get(
    "/api/admin/infra/servicios-odf/{servicio_id}/senal-direccion", dependencies=[Depends(usuario_admin)]
)
async def servicios_sin_odf_senal_direccion_web(servicio_id: int, odf_n_id: Optional[int] = None) -> JSONResponse:
    """Preview de `senal_direccion` (Task 2) para una ODF que el operador eligió A MANO en el
    buscador del modal, ANTES de confirmar — puro read-only, nunca persiste nada. Fix round 1 de
    Task 6: `GET .../sugerencia` sólo calcula esta señal contra la ODF que la propia API sugirió, y
    esa sugerencia sólo existe para `OLT_PON_COMPARTIDO` (1537 de 2891 Servicios sin ODF, medido
    real 2026-09-09) — para el 47% restante, y para cualquier operador que rechace la sugerencia y
    busque otra ODF, el badge del frontend quedaba inerte justo donde más se necesita. Este
    endpoint cierra ese hueco sin mover la fuente de verdad: `POST .../asociar` sigue siendo quien
    recalcula y persiste la señal, contra la ODF REALMENTE elegida en su body — esto es sólo una
    ayuda visual previa.

    Mismo cálculo que ya usan `/sugerencia` y `POST /asociar`: reusa `_obtener_servicio_categorizado`
    (misma fuente de la dirección PROV cruda del Servicio) y `_senal_direccion_contra_odf` (wiring
    sobre `core/services/cromo/direccion_comparacion.py`) — cero lógica de comparación nueva acá.

    Admin (`usuario_admin`), mismo criterio que los otros 3 endpoints del gestor (ver la justificación en
    `/sugerencia`: el guard `_require_auth` que tenían los dos GET no habilitaba ningún caso de uso
    — la ruta de UI que los consume ya exige admin — y sólo ampliaba la superficie). 400 si falta
    `odf_n_id` (un tipo inválido, ej. `odf_n_id=abc`, ya lo rechaza la validación automática de
    FastAPI con 422 antes de llegar acá — mismo comportamiento que `limit`/`offset` en el listado).
    404 si el Servicio no existe, o si `odf_n_id` no tiene fila PROPIA en `app.cromo_odfs` — un
    `odf_n_id` inventado nunca debe devolver silenciosamente `no_se_pudo_comparar`, eso confundiría
    "ODF sin dirección cargada" con "ODF que no existe" (ver `_existe_odf`, mismo criterio ESTRICTO
    que ya exige `crear_override`)."""
    from db.session import AsyncSessionLocal

    if odf_n_id is None:
        return JSONResponse({"error": "odf_n_id es requerido"}, status_code=400)

    async with AsyncSessionLocal() as sesion:
        detalle = await _obtener_servicio_categorizado(sesion, servicio_id)
        if detalle is None:
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)

        if not await _existe_odf(sesion, odf_n_id):
            return JSONResponse({"error": "ODF no encontrada"}, status_code=404)

        servicio = detalle["servicio"]
        senal = await _senal_direccion_contra_odf(sesion, servicio.direccion, odf_n_id)

    return JSONResponse({"senal_direccion": senal.value})


class ServicioOdfAsociarRequestModel(BaseModel):
    """Payload para confirmar la asociación manual Servicio→ODF (`crear_override`, Task 4)."""

    odf_n_id: int
    pelo_n_id: Optional[int] = None
    notas: Optional[str] = None
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/admin/infra/servicios-odf/{servicio_id}/asociar")
async def servicios_sin_odf_asociar_web(
    request: Request,
    servicio_id: int,
    body: ServicioOdfAsociarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Confirma la asociación manual Servicio→ODF que el operador eligió (la sugerida, u otra que
    haya buscado a mano). Recalcula `senal_direccion` (Task 2) en el backend contra la ODF
    REALMENTE elegida en `body.odf_n_id` — nunca confía en lo que mandó el frontend, que puede
    haber elegido una ODF distinta a la sugerida — y la persiste vía `crear_override` (Task 4) junto
    con la MISMA `categoria_causa`/`subcategoria` que ve el operador en el detalle.

    `senal_direccion` es sólo informativa: un `no_coincide` se persiste y se devuelve igual, nunca
    bloquea la asociación. `ObjetoNoEncontrado` de `crear_override` (la ODF no tiene fila propia en
    `cromo_odfs`) se mapea a 404, nunca a un 500."""
    from core.services.cromo.servicio_odf_override_service import ObjetoNoEncontrado, crear_override
    from db.session import AsyncSessionLocal

    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=servicios_sin_odf_asociar result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        async with AsyncSessionLocal() as sesion:
            detalle = await _obtener_servicio_categorizado(sesion, servicio_id)
            if detalle is None:
                return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)

            servicio = detalle["servicio"]
            senal = await _senal_direccion_contra_odf(sesion, servicio.direccion, body.odf_n_id)

            try:
                await crear_override(
                    sesion,
                    servicio_id=servicio_id,
                    odf_n_id=body.odf_n_id,
                    pelo_n_id=body.pelo_n_id,
                    categoria_causa=detalle["categoria_causa"],
                    subcategoria=detalle["subcategoria"],
                    usuario=username,
                    notas=body.notas,
                    senal_direccion=senal,
                )
            except ObjetoNoEncontrado as exc:
                # Mensaje armado por `crear_override` para el usuario: misma respuesta 404.
                raise NoEncontrado(str(exc)) from exc

            await _encolar_arbitro("SERVICIOS", [servicio_id], f"asociar-odf servicio={servicio_id}")
            logger.info(
                "action=servicios_sin_odf_asociar user=%s servicio_id=%s odf_n_id=%s "
                "categoria_causa=%s senal_direccion=%s",
                username,
                servicio_id,
                body.odf_n_id,
                detalle["categoria_causa"],
                senal.value,
            )
            return JSONResponse(
                {"ok": True, "categoria_causa": detalle["categoria_causa"], "senal_direccion": senal.value}
            )
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("servicios_sin_odf_asociar", exc, user=username, servicio_id=servicio_id)


def _serializar_vinculo_local(vinculo: Any) -> Optional[dict[str, Any]]:
    if vinculo is None:
        return None
    return {
        "tabla": vinculo.tabla,
        "n_id": vinculo.n_id,
        "nombre": vinculo.nombre,
        "vigente": vinculo.vigente,
        "coincide_por": vinculo.coincide_por,
    }


def _serializar_nodo_camino(nodo: Any) -> dict[str, Any]:
    return {
        "orden": nodo.orden,
        "lado": nodo.lado,
        "id_cromo": nodo.id_cromo,
        "clase": nodo.clase,
        "tipo": nodo.tipo,
        "nombre": nodo.nombre,
        "repetido": nodo.repetido,
        "numero_pelo": nodo.numero_pelo,
        "color_pelo": nodo.color_pelo,
        "tubo_id": nodo.tubo_id,
        "tubo_color": nodo.tubo_color,
        "cable_id": nodo.cable_id,
        "cable_nombre": nodo.cable_nombre,
        "cable_capacidad": nodo.cable_capacidad,
        "distancia_geo_m": nodo.distancia_geo_m,
        "distancia_real_m": nodo.distancia_real_m,
        "botella_id": nodo.botella_id,
        "botella_nombre": nodo.botella_nombre,
        "conector_numero": nodo.conector_numero,
        "patchera_nombre": nodo.patchera_nombre,
        "odf_id": nodo.odf_id,
        "odf_nombre": nodo.odf_nombre,
        "servicio_at62": nodo.servicio_at62,
        # Red de acceso PON (clases 133/134/84/137/66). `splitter_ratio` viene de `at.83`: Cromo
        # publica el ratio, no se infiere por fan-out como en el detalle de empalmes de Botella.
        "splitter_id": nodo.splitter_id,
        "splitter_nombre": nodo.splitter_nombre,
        "splitter_ratio": nodo.splitter_ratio,
        "splitter_salidas": nodo.splitter_salidas,
        "puerto_nombre": nodo.puerto_nombre,
        "puerto_sentido": nodo.puerto_sentido,
        "tendido": nodo.tendido,
        # `vinculo_local` en `null` NO es un error: puede ser una clase que la ingesta no barre
        # o un objeto que Cromo movió después de la última corrida. Es dato de auditoría.
        "vinculo_local": _serializar_vinculo_local(nodo.vinculo_local),
    }


def _serializar_consistencia(consistencia: Any) -> Optional[dict[str, Any]]:
    if consistencia is None:
        return None
    return {
        "reglas": [
            {
                "regla": r.regla,
                "descripcion": r.descripcion,
                "total": r.total,
                "coincide": r.coincide,
                "discrepa": r.discrepa,
                "no_ingerido": r.no_ingerido,
            }
            for r in consistencia.reglas
        ],
        "inconsistencias": [
            {
                "regla": i.regla,
                "elemento_id": i.elemento_id,
                "tipo": i.tipo,
                "valor_path": i.valor_path,
                "valor_local": i.valor_local,
            }
            for i in consistencia.inconsistencias
        ],
        "total_discrepa": consistencia.total_discrepa,
        "total_no_ingerido": consistencia.total_no_ingerido,
    }


def _serializar_camino_optico(camino: Any, semillas: list[Any]) -> dict[str, Any]:
    return {
        "estado": camino.estado,
        "motivo": camino.motivo,
        "pelo_n_id": camino.pelo_n_id,
        # `identidad_cromo` instrumenta una incógnita del proveedor: medido real, `/path` acepta el
        # `n_id` estable y devuelve la raíz bajo ese mismo id. Si algún día respondiera con ids de
        # versión, se ve acá en vez de fallar en silencio.
        "identidad_cromo": {
            "id_pedido": camino.id_pedido,
            "id_raiz": camino.id_raiz,
            "raiz_es_mismo_id": camino.raiz_es_mismo_id,
        },
        "servicio_at62": camino.servicio_at62,
        "servicio_at61": camino.servicio_at61,
        "numero_pelo": camino.numero_pelo,
        "color_pelo": camino.color_pelo,
        "cable_id": camino.cable_id,
        "cable_nombre": camino.cable_nombre,
        "raiz": _serializar_nodo_camino(camino.raiz) if camino.raiz else None,
        "lado_a": [_serializar_nodo_camino(n) for n in camino.lado_a],
        "lado_b": [_serializar_nodo_camino(n) for n in camino.lado_b],
        "odfs": [
            {
                "odf_id": o.odf_id,
                "nombre": o.nombre,
                "lado": o.lado,
                "conector_numero": o.conector_numero,
                "patchera_nombre": o.patchera_nombre,
                "servicio_at62": o.servicio_at62,
                "es_extremo": o.es_extremo,
                "vinculo_local": _serializar_vinculo_local(o.vinculo_local),
            }
            for o in camino.odfs
        ],
        "estadisticas": {
            "nodos": camino.estadisticas.nodos,
            "pelos": camino.estadisticas.pelos,
            "fusiones": camino.estadisticas.fusiones,
            "conectores": camino.estadisticas.conectores,
            "cables": camino.estadisticas.cables,
            "splitters": camino.estadisticas.splitters,
            "cajas_pon": camino.estadisticas.cajas_pon,
            "cables_bajada": camino.estadisticas.cables_bajada,
            "odfs": camino.estadisticas.odfs,
            "no_resueltos": camino.estadisticas.no_resueltos,
            "longitud_geo_m": camino.estadisticas.longitud_geo_m,
            "longitud_optica_m": camino.estadisticas.longitud_optica_m,
        },
        "consistencia": _serializar_consistencia(camino.consistencia),
        "discrepancia_at62": (
            {
                "at62": camino.discrepancia.at62,
                "at61": camino.discrepancia.at61,
                "numero_regex": camino.discrepancia.numero_regex,
                "veredicto": camino.discrepancia.veredicto,
            }
            if camino.discrepancia
            else None
        ),
        "ids_no_resueltos": camino.ids_no_resueltos,
        "advertencias": camino.advertencias,
        "duracion_ms": camino.duracion_ms,
        "semillas_disponibles": len(semillas),
        "semillas_alternativas": [_serializar_pelo_semilla(s) for s in semillas],
        "payload_raw": camino.payload_raw,
    }


@router.get("/api/servicios/{servicio_id}/baneos")
async def servicio_baneos_web(servicio_id: int, limite: int = 50) -> JSONResponse:
    """Eventos de baneo en los que participa un Servicio, como protegido o como afectado.

    `app.incidentes_baneo` guarda los dos extremos como **texto** (`varchar(64)`), no como FK, así
    que el match va por las **tres identidades** del Servicio —`servicio_id`,
    `numero_primer_servicio` y `alias_ids`— igual que el resto del módulo. Matchear sólo por la PK
    perdería silenciosamente los baneos registrados bajo un número viejo del mismo Servicio, que es
    justo el caso que el histórico de IDs existe para contemplar.

    `rol` distingue si el Servicio fue el **protegido** (se baneó a otros para cuidarlo) o el
    **afectado** (se lo baneó para cuidar a un tercero): son dos lecturas muy distintas de la misma
    fila y mezclarlas confundiría al operador.
    """
    from sqlalchemy import text as _sql

    from db.session import AsyncSessionLocal

    limite = max(1, min(limite, 200))

    consulta = _sql(
        """
        WITH ident AS (
            SELECT ARRAY_REMOVE(
                       ARRAY[s.servicio_id, s.numero_primer_servicio]::varchar[]
                       || COALESCE(s.alias_ids, ARRAY[]::varchar[]),
                       NULL
                   ) AS ids
            FROM app.servicios s
            WHERE s.id = :servicio_id
        )
        SELECT b.id,
               b.ticket_asociado,
               b.servicio_afectado_id,
               b.servicio_protegido_id,
               b.usuario_ejecutor,
               b.motivo,
               b.fecha_inicio,
               b.fecha_fin,
               b.activo,
               CASE WHEN b.servicio_protegido_id = ANY(ident.ids) THEN 'PROTEGIDO'
                    ELSE 'AFECTADO' END AS rol
        FROM app.incidentes_baneo b, ident
        WHERE b.servicio_protegido_id = ANY(ident.ids)
           OR b.servicio_afectado_id = ANY(ident.ids)
        ORDER BY b.fecha_inicio DESC
        LIMIT :limite
        """
    )

    async with AsyncSessionLocal() as sesion:
        if not await _servicio_existe(sesion, servicio_id):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
        filas = (
            await sesion.execute(consulta, {"servicio_id": servicio_id, "limite": limite})
        ).mappings().all()

    eventos = [
        {
            "id": f["id"],
            "ticket_asociado": f["ticket_asociado"],
            "servicio_afectado_id": f["servicio_afectado_id"],
            "servicio_protegido_id": f["servicio_protegido_id"],
            "usuario_ejecutor": f["usuario_ejecutor"],
            "motivo": f["motivo"],
            "fecha_inicio": f["fecha_inicio"].isoformat() if f["fecha_inicio"] else None,
            "fecha_fin": f["fecha_fin"].isoformat() if f["fecha_fin"] else None,
            "activo": f["activo"],
            "rol": f["rol"],
        }
        for f in filas
    ]
    return JSONResponse(
        {
            "servicio_id": servicio_id,
            "total": len(eventos),
            "activos": sum(1 for e in eventos if e["activo"]),
            "eventos": eventos,
        }
    )


class PelosExcluirRequestModel(BaseModel):
    """Payload para sacar pelos huérfanos de un Servicio (de a uno o todos juntos)."""

    pelos_n_id: list[int] = Field(min_length=1, max_length=500, description="Pelos a excluir")
    motivo: str | None = Field(default=None, max_length=500, description="Por qué se excluyen")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class PeloRestaurarRequestModel(BaseModel):
    """Payload para devolver un pelo excluido a su Servicio."""

    pelo_n_id: int = Field(description="Pelo a restaurar")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/admin/infra/servicios-odf/{servicio_id}/pelos-excluidos")
async def servicios_pelo_excluir_web(
    request: Request,
    servicio_id: int,
    body: PelosExcluirRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Saca pelos del Servicio en local: dejan de ser semilla, de contar y de pesar en los caminos
    esperados, aunque Cromo conserve la etiqueta. Es para los huérfanos que quedaron con la
    etiqueta del Servicio fuera de todos sus caminos. Reversible con `/pelos-excluidos/restaurar`.
    Admin."""
    from core.services.cromo.pelos_excluidos import PeloNoPerteneceAlServicio, excluir_pelos
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "cromo_pelo_excluir", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    async with AsyncSessionLocal() as sesion:
        if not await _servicio_existe(sesion, servicio_id):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
        try:
            excluidos, ajenos = await excluir_pelos(
                sesion, servicio_id, body.pelos_n_id, usuario=username, motivo=body.motivo
            )
        except PeloNoPerteneceAlServicio as exc:
            # Mensaje armado por el servicio para el usuario: misma respuesta 409.
            raise Conflicto(str(exc)) from exc
    return JSONResponse({"ok": True, "excluidos": excluidos, "ajenos": ajenos})


@router.post("/api/admin/infra/servicios-odf/{servicio_id}/pelos-excluidos/restaurar")
async def servicios_pelo_restaurar_web(
    request: Request,
    servicio_id: int,
    body: PeloRestaurarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Devuelve al Servicio un pelo excluido. Admin."""
    from core.services.cromo.pelos_excluidos import restaurar_pelo
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "cromo_pelo_restaurar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    async with AsyncSessionLocal() as sesion:
        if not await _servicio_existe(sesion, servicio_id):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
        restaurado = await restaurar_pelo(sesion, servicio_id, body.pelo_n_id, usuario=username)
    if not restaurado:
        return JSONResponse(
            {"error": f"El pelo {body.pelo_n_id} no estaba excluido de este Servicio."},
            status_code=404,
        )
    return JSONResponse({"ok": True, "pelo_n_id": body.pelo_n_id})


class OdfConfirmadaItemModel(BaseModel):
    """Una ODF a confirmar para un Servicio, con su rol en el recorrido."""

    odf_n_id: int = Field(description="n_id de la ODF en cromo_odfs")
    rol: Literal["EXTREMO", "TRANSITO"] = Field(description="Extremo del servicio o ODF de tránsito")


class OdfConfirmarRequestModel(BaseModel):
    """Payload para confirmar ODF de un Servicio en lote."""

    odfs: list[OdfConfirmadaItemModel] = Field(min_length=1, max_length=50)
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class OdfDesconfirmarRequestModel(BaseModel):
    """Payload para quitar la confirmación de una ODF."""

    odf_n_id: int = Field(description="n_id de la ODF a des-confirmar")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class TrackingsEsperadosRequestModel(BaseModel):
    """Payload para declarar cuántos trackings espera el Servicio (`null` borra la declaración)."""

    cantidad: int | None = Field(default=None, gt=0, le=32767)
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.get("/api/admin/infra/servicios-odf/{servicio_id}/odf-confirmadas", dependencies=[Depends(usuario_admin)])
async def servicios_odf_confirmadas_listar_web(servicio_id: int) -> JSONResponse:
    """ODF confirmadas vigentes del Servicio y los trackings que se esperan. Admin."""
    from core.services.cromo.servicio_odf_confirmacion import declaraciones_del_servicio
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        if not await _servicio_existe(sesion, servicio_id):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
        declaradas = await declaraciones_del_servicio(sesion, servicio_id)
    return JSONResponse(
        {"odf_confirmadas": declaradas.confirmadas, "trackings_esperados": declaradas.trackings_esperados}
    )


@router.post("/api/admin/infra/servicios-odf/{servicio_id}/odf-confirmadas")
async def servicios_odf_confirmar_web(
    request: Request,
    servicio_id: int,
    body: OdfConfirmarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Confirma ODF del Servicio en lote (todo o nada). Un camino que toca una ODF confirmada es
    siempre TRAMO. Idempotente. 404 si alguna ODF no existe en el inventario. Admin."""
    from core.services.cromo.servicio_odf_confirmacion import confirmar
    from core.services.cromo.verificador import ObjetoNoEncontrado
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "cromo_odf_confirmar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    async with AsyncSessionLocal() as sesion:
        if not await _servicio_existe(sesion, servicio_id):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
        try:
            lista = await confirmar(
                sesion, servicio_id, [(o.odf_n_id, o.rol) for o in body.odfs], usuario=username
            )
        except ObjetoNoEncontrado as exc:
            # Mensaje armado por el servicio para el usuario: misma respuesta 404.
            raise NoEncontrado(str(exc)) from exc
    await _encolar_arbitro("SERVICIOS", [servicio_id], f"odf-confirmar servicio={servicio_id}")
    return JSONResponse({"ok": True, "odf_confirmadas": lista})


@router.post("/api/admin/infra/servicios-odf/{servicio_id}/odf-confirmadas/desconfirmar")
async def servicios_odf_desconfirmar_web(
    request: Request,
    servicio_id: int,
    body: OdfDesconfirmarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Quita la confirmación de una ODF (queda el historial). Admin."""
    from core.services.cromo.servicio_odf_confirmacion import desconfirmar, listar
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "cromo_odf_desconfirmar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    async with AsyncSessionLocal() as sesion:
        if not await _servicio_existe(sesion, servicio_id):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
        if not await desconfirmar(sesion, servicio_id, body.odf_n_id):
            return JSONResponse(
                {"error": f"La ODF {body.odf_n_id} no estaba confirmada para este Servicio."},
                status_code=404,
            )
        lista = await listar(sesion, servicio_id)
    await _encolar_arbitro("SERVICIOS", [servicio_id], f"odf-desconfirmar servicio={servicio_id}")
    return JSONResponse({"ok": True, "odf_confirmadas": lista})


@router.post("/api/admin/infra/servicios-odf/{servicio_id}/trackings-esperados")
async def servicios_trackings_esperados_web(
    request: Request,
    servicio_id: int,
    body: TrackingsEsperadosRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Declara cuántos trackings espera el Servicio; `cantidad: null` borra la declaración. Admin."""
    from core.services.cromo.servicio_odf_confirmacion import declarar_trackings_esperados
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "cromo_trackings_esperados", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    async with AsyncSessionLocal() as sesion:
        if not await declarar_trackings_esperados(sesion, servicio_id, body.cantidad):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
    return JSONResponse({"ok": True, "trackings_esperados": body.cantidad})


class PosicionVigenteDeclararRequestModel(BaseModel):
    """Payload para declarar conectores de ODF como posición vigente del Servicio, en lote."""

    conectores_n_id: list[int] = Field(
        min_length=1, max_length=8, description="Conectores (`cromo_odf_conectores.n_id`) a declarar"
    )
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class PosicionVigenteRetirarRequestModel(BaseModel):
    """Payload para retirar a mano la posición vigente de un conector."""

    conector_n_id: int = Field(description="Conector declarado a retirar")
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


def _serializar_posicion_declarada(d: Any, aviso: Any) -> dict[str, Any]:
    """Una posición declarada vigente. `valida`/`aviso` salen de `validar_en_db` y `arrastrar_par`:
    el inventario ingerido ya no la sostiene, o no sostiene a su par (la corrida de tracking la va a
    retirar), pero acá sólo se informa."""
    from core.services.cromo.servicio_posicion_vigente import texto_aviso

    return {
        "id": d.id,
        "conector_n_id": d.conector_n_id,
        "posicion": d.posicion,
        "odf_n_id": d.odf_n_id,
        "odf_nombre": d.odf_nombre,
        "bandeja_n_id": d.bandeja_n_id,
        "bandeja_nombre": d.bandeja_nombre,
        "numero_conector": d.numero_conector,
        "pelo_n_id_declarado": d.pelo_declarado,
        "pelo_n_id_actual": d.pelo_actual,
        "pelos_candidatos": list(d.pelos_candidatos),
        "declarado_por": d.declarado_por,
        "declarado_en": d.declarado_en.isoformat() if d.declarado_en else None,
        "valida": aviso is None,
        "aviso": texto_aviso(aviso) if aviso is not None else None,
        "codigo_aviso": aviso.codigo if aviso is not None else None,
    }


def _serializar_posicion_posible(p: Any, posibles: Any, declarados: set[int]) -> dict[str, Any]:
    """Una posición posible para el selector. `servicio_activo_ajeno` es otro servicio Activo cuyo
    pelo también matchea (sólo puede pasar si matchea a este también: si no, el filtro compartido
    ya lo sacó de la lista)."""
    from core.services.cromo.servicio_posicion_vigente import par_sugerido

    return {
        "conector_n_id": p.conector_n_id,
        "posicion": p.posicion,
        "odf_n_id": p.odf_n_id,
        "odf_nombre": p.odf_nombre,
        "odf_clase": p.odf_clase,
        "bandeja_n_id": p.bandeja_n_id,
        "bandeja_nombre": p.bandeja_nombre,
        "numero_conector": p.numero_conector,
        "pelo_n_id": p.pelo_n_id,
        "numero_pelo": p.numero_pelo,
        "pelos_candidatos": list(p.pelos_candidatos),
        "cable_n_id": p.cable_n_id,
        "cable_nombre": p.cable_nombre,
        "etiqueta_pelo": p.etiqueta_pelo,
        "etiqueta_ajena": p.etiqueta_ajena,
        "estado_pelo": p.estado_pelo,
        "servicio_resuelto": p.servicio_resuelto,
        "servicio_id_historico": p.servicio_id_historico,
        "patch_conector_n_id": p.patch_conector_n_id,
        "por_resuelto": p.por_resuelto,
        "por_pelo": p.por_pelo,
        "servicio_activo_ajeno": p.servicio_activo_ajeno,
        "par_sugerido_n_id": par_sugerido(p, posibles),
        "declarada": p.conector_n_id in declarados,
    }


def _serializar_declaradas(declaradas: Any) -> list[dict[str, Any]]:
    # Con el arrastre del par (`arrastrar_par`): la que la corrida va a retirar junto con su par
    # tampoco se muestra como válida.
    from core.services.cromo.servicio_posicion_vigente import arrastrar_par, validar_en_db

    avisos = {a.declaracion_id: a for a in arrastrar_par(declaradas, validar_en_db(declaradas))}
    return [_serializar_posicion_declarada(d, avisos.get(d.id)) for d in declaradas]


@router.get("/api/admin/infra/servicios-odf/{servicio_id}/posicion-vigente", dependencies=[Depends(usuario_admin)])
async def servicios_posicion_vigente_listar_web(servicio_id: int) -> JSONResponse:
    """Posiciones vigentes declaradas del Servicio y las posibles para el selector. Sólo informa:
    no retira nada (retirar es efecto de la corrida de tracking). Admin."""
    from core.services.cromo import servicio_posicion_vigente as pv
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as sesion:
        if not await _servicio_existe(sesion, servicio_id):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
        declaradas = await pv.listar_declaradas(sesion, servicio_id)
        posibles = await pv.posiciones_posibles(sesion, servicio_id)
    declarados = {d.conector_n_id for d in declaradas}
    return JSONResponse(
        {
            "declaradas": _serializar_declaradas(declaradas),
            "posibles": [_serializar_posicion_posible(p, posibles, declarados) for p in posibles],
        }
    )


@router.post("/api/admin/infra/servicios-odf/{servicio_id}/posicion-vigente")
async def servicios_posicion_vigente_declarar_web(
    request: Request,
    servicio_id: int,
    body: PosicionVigenteDeclararRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Declara conectores como posición vigente del Servicio (todo o nada; los ya vigentes quedan).
    El tracking sale de ahí: sus caminos son VIGENTE y los tramos calculados pasan a ADICIONAL.
    409 si algún conector no es posición posible o no tiene pelo. Admin."""
    from core.services.cromo import servicio_posicion_vigente as pv
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "cromo_posicion_vigente_declarar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    async with AsyncSessionLocal() as sesion:
        if not await _servicio_existe(sesion, servicio_id):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
        try:
            declaradas = await pv.declarar(
                sesion, servicio_id, body.conectores_n_id, usuario=username
            )
        except pv.PosicionNoValida as exc:
            # Mensaje armado por el servicio para el usuario: misma respuesta 409.
            raise Conflicto(str(exc)) from exc
    logger.info(
        "action=cromo_posicion_vigente evento=declarar user=%s servicio_id=%s conectores=%s",
        username,
        servicio_id,
        body.conectores_n_id,
    )
    return JSONResponse({"ok": True, "declaradas": _serializar_declaradas(declaradas)})


@router.post("/api/admin/infra/servicios-odf/{servicio_id}/posicion-vigente/retirar")
async def servicios_posicion_vigente_retirar_web(
    request: Request,
    servicio_id: int,
    body: PosicionVigenteRetirarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Retira a mano (`MANUAL`) la posición vigente de un conector; queda el historial. 404 si el
    conector no tenía declaración vigente. Admin."""
    from core.services.cromo import servicio_posicion_vigente as pv
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "cromo_posicion_vigente_retirar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    async with AsyncSessionLocal() as sesion:
        if not await _servicio_existe(sesion, servicio_id):
            return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
        if not await pv.retirar_manual(sesion, servicio_id, body.conector_n_id, usuario=username):
            return JSONResponse(
                {
                    "error": (
                        f"El conector {body.conector_n_id} no tenía una posición vigente "
                        "declarada para este Servicio."
                    )
                },
                status_code=404,
            )
        declaradas = await pv.listar_declaradas(sesion, servicio_id)
    logger.info(
        "action=cromo_posicion_vigente evento=retirar_manual user=%s servicio_id=%s conector=%s",
        username,
        servicio_id,
        body.conector_n_id,
    )
    return JSONResponse({"ok": True, "declaradas": _serializar_declaradas(declaradas)})


class CaminoNormalizarRequestModel(BaseModel):
    """Payload para normalizar las inconsistencias de la auditoría de un camino óptico."""

    pelo_n_id: int = Field(description="Pelo semilla cuyo camino se auditó")
    elemento_ids: list[int] | None = Field(
        default=None,
        description="Elementos puntuales a normalizar. Sin esto se normaliza todo lo inconsistente.",
    )
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


class CaminoRelevarOdfRequestModel(BaseModel):
    """Payload para relevar las ODFs que atraviesa el camino de un pelo."""

    pelo_n_id: int = Field(description="Pelo semilla cuyo camino descubre las ODFs")
    odfs_n_id: list[int] | None = Field(
        default=None, description="ODFs puntuales a relevar. Sin esto se relevan todas las del camino."
    )
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/admin/infra/servicios-odf/{servicio_id}/camino-optico/normalizar")
async def servicios_sin_odf_camino_normalizar_web(
    request: Request,
    servicio_id: int,
    body: CaminoNormalizarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Normaliza las discrepancias de la tabla "Consistencia con lo ingerido", tomando Cromo como
    referencia.

    **Reingesta dirigida, no escritura del valor declarado por el camino**: se vuelve a traer de
    Cromo el objeto real y se lo persiste por el mismo parser y los mismos upserts que usa la
    ingesta regular, con su corrida sintética auditable. Escribe inventario, así que es admin.

    Las inconsistencias se recalculan en el servidor: el cliente dice qué quiere normalizar, pero
    qué está realmente mal lo decide quien va a escribir.
    """
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo.normalizacion_consistencia_service import (
        CaminoNoResoluble,
        normalizar_inconsistencias,
    )
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "camino_normalizar", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        async with AsyncSessionLocal() as sesion:
            if not await _servicio_existe(sesion, servicio_id):
                return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
            async with CromoClient(config=get_cromo_config()) as cliente:
                resultado = await normalizar_inconsistencias(
                    cliente,
                    sesion,
                    pelo_n_id=body.pelo_n_id,
                    usuario=username,
                    elemento_ids=body.elemento_ids,
                )
    except CaminoNoResoluble as exc:
        return JSONResponse({"error": exc.motivo, "estado": exc.estado}, status_code=409)
    except CromoClientError as exc:
        return error_servicio_externo(
            "camino_normalizar", exc, "Cromo no respondió", user=username, servicio_id=servicio_id
        )
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("camino_normalizar", exc, user=username, servicio_id=servicio_id)

    return JSONResponse(
        {
            "ok": True,
            "corrida_id": resultado.corrida_id,
            "pelo_n_id": resultado.pelo_n_id,
            "creados": resultado.creados,
            "actualizados": resultado.actualizados,
            "sin_cambios": resultado.sin_cambios,
            "errores": resultado.errores,
            "total_discrepa_previo": resultado.total_discrepa_previo,
            "total_no_ingerido_previo": resultado.total_no_ingerido_previo,
            "detalle": [
                {"elemento_id": i.elemento_id, "regla": i.regla, "accion": i.accion, "detalle": i.detalle}
                for i in resultado.detalle
            ],
        }
    )


@router.post("/api/admin/infra/servicios-odf/{servicio_id}/camino-optico/relevar-odf")
async def servicios_sin_odf_camino_relevar_odf_web(
    request: Request,
    servicio_id: int,
    body: CaminoRelevarOdfRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Releva las ODFs que atraviesa el camino, para poblar sus posiciones de patchera.

    Es lo que destraba el caso "la ODF de este Servicio no está relevada": sin conectores
    ingeridos no hay forma de saber qué posición le corresponde al Servicio, y por eso la descarga
    de trackings no puede preseleccionar nada. Releva sólo lo que el camino ya descubrió, no todo
    el universo de ODFs.
    """
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from core.services.cromo.normalizacion_consistencia_service import (
        CaminoNoResoluble,
        relevar_odfs_del_servicio,
    )
    from db.session import AsyncSessionLocal

    username = usuario.username
    if not _validar_csrf(request, body.csrf_token, "camino_relevar_odf", username):
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        async with AsyncSessionLocal() as sesion:
            if not await _servicio_existe(sesion, servicio_id):
                return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
            async with CromoClient(config=get_cromo_config()) as cliente:
                resultado = await relevar_odfs_del_servicio(
                    cliente,
                    sesion,
                    pelo_n_id=body.pelo_n_id,
                    usuario=username,
                    odfs_n_id=body.odfs_n_id,
                )
    except CaminoNoResoluble as exc:
        return JSONResponse({"error": exc.motivo, "estado": exc.estado}, status_code=409)
    except CromoClientError as exc:
        return error_servicio_externo(
            "camino_relevar_odf", exc, "Cromo no respondió", user=username, servicio_id=servicio_id
        )
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("camino_relevar_odf", exc, user=username, servicio_id=servicio_id)

    return JSONResponse(
        {
            "ok": True,
            "corrida_id": resultado.corrida_id,
            "relevadas": resultado.normalizados,
            "errores": resultado.errores,
            "detalle": [
                {"odf_n_id": i.elemento_id, "accion": i.accion, "detalle": i.detalle}
                for i in resultado.detalle
            ],
        }
    )


@router.get("/api/admin/infra/servicios-odf/{servicio_id}/camino-optico")
async def servicios_sin_odf_camino_optico_web(
    servicio_id: int,
    pelo_n_id: Optional[int] = None,
    raw: bool = False,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Camino óptico completo de un Servicio, con su auditoría de consistencia.

    Admin (`usuario_admin`) por el mismo criterio ya escrito para `/sugerencia`: devuelve MÁS topología
    que aquél (el recorrido entero, cable por cable) y además gasta recursos del proveedor en cada
    request. La única UI que lo consume es `/admin/servicios/viewer/ServiciosSinOdf`, que ya es
    `requiresAdmin`.

    `estado ∈ {OK, SIN_SEMILLA, SIN_CAMINO}` **siempre con HTTP 200**: `SIN_SEMILLA` es el caso
    del 77% de los Servicios del gestor, y usar un código de error para el caso mayoritario y
    legítimo llena los logs de falsos incidentes y empuja la lógica de negocio al handler de
    errores del frontend. Es la misma forma que ya tiene `/sugerencia` (200 con nulls).

    `raw=true` agrega el payload crudo de Cromo. Por omisión no viaja: un camino real son ~880
    nodos con todos sus atributos, cientos de KB por request.
    """
    from core.services.cromo.camino_optico_service import (
        PeloAjenoAlServicio,
        resolver_camino_de_servicio,
    )
    from core.services.cromo.client import CromoClient, CromoClientError
    from core.services.cromo.config import get_cromo_config
    from db.session import AsyncSessionLocal

    username = usuario.username

    try:
        async with AsyncSessionLocal() as sesion:
            if not await _servicio_existe(sesion, servicio_id):
                return JSONResponse({"error": "Servicio no encontrado"}, status_code=404)
            async with CromoClient(config=get_cromo_config()) as cliente:
                camino, semillas = await resolver_camino_de_servicio(
                    cliente, sesion, servicio_id, pelo_n_id=pelo_n_id, incluir_raw=raw
                )
            if camino.estado == "OK":
                # Evidencia para el árbitro; nunca cambia la respuesta HTTP.
                try:
                    from core.services.cromo.arbitro.evidencia import (
                        camino_truncado,
                        entrada_de_camino,
                        registrar_y_encolar,
                    )

                    entrada = entrada_de_camino(camino)
                    if entrada is not None:
                        await registrar_y_encolar(
                            sesion,
                            servicio_id,
                            [entrada],
                            completo=not camino_truncado(camino),
                            fuente="WEB",
                        )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "action=arbitro_evidencia evento=enganche_fallido servicio_id=%s",
                        servicio_id,
                        exc_info=True,
                    )
    except PeloAjenoAlServicio as exc:
        # Mensaje armado por el servicio para el usuario: misma respuesta 400.
        raise ErrorDeDominio(str(exc)) from exc
    except CromoClientError as exc:
        return error_servicio_externo(
            "cromo_camino_optico", exc, "Cromo no respondió", user=username, servicio_id=servicio_id
        )

    logger.info(
        "action=cromo_camino_optico user=%s servicio_id=%s estado=%s pelo_n_id=%s "
        "nodos=%s discrepa=%s no_ingerido=%s duracion_ms=%s",
        username,
        servicio_id,
        camino.estado,
        camino.pelo_n_id,
        camino.estadisticas.nodos,
        camino.consistencia.total_discrepa if camino.consistencia else None,
        camino.consistencia.total_no_ingerido if camino.consistencia else None,
        camino.duracion_ms,
    )
    return JSONResponse(_serializar_camino_optico(camino, semillas))


@router.get("/api/servicios/search")
async def servicios_search_web(
    q: str | None = None,
    numero_primer_servicio: str | None = None,
    cliente: str | None = None,
    domicilio: str | None = None,
    tipo: str | None = None,
    estado: str | None = None,
    categoria: str | None = None,
    limit: int = 30,
    offset: int = 0,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Búsqueda paginada de servicios para usuarios autenticados."""

    username, _ = usuario
    params = {
        "q": q,
        "numero_primer_servicio": numero_primer_servicio,
        "cliente": cliente,
        "domicilio": domicilio,
        "tipo": tipo,
        "estado": estado,
        "categoria": categoria,
        "limit": max(1, min(limit, 200)),
        "offset": max(offset, 0),
    }
    params = {k: v for k, v in params.items() if v not in (None, "")}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{INTERNAL_API_BASE_URL}/servicios/search",
                params=params,
                headers=_internal_api_auth_headers(),
            )

        payload: dict[str, Any]
        payload = payload_de_upstream(response, "Error consultando servicios", "servicios_list_proxy")

        logger.info(
            "action=servicios_search_proxy user=%s q=%s limit=%s offset=%s status=%s",
            username,
            q,
            params.get("limit"),
            params.get("offset"),
            response.status_code,
        )
        return JSONResponse(payload, status_code=response.status_code)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("servicios_search_proxy", exc, user=username)


@router.get("/api/servicios/detail")
async def servicios_detail_web(
    id: str,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Detalle de servicio por ID (origen o línea), con resolución a ID canónico."""

    username, _ = usuario
    id_consultado = (id or "").strip()
    if not id_consultado:
        return JSONResponse({"error": "ID requerido"}, status_code=400)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{INTERNAL_API_BASE_URL}/servicios/detail",
                params={"id": id_consultado},
                headers=_internal_api_auth_headers(),
            )

        payload: dict[str, Any]
        payload = payload_de_upstream(response, "Error consultando detalle de servicio", "servicio_detail_proxy")

        logger.info(
            "action=servicios_detail_proxy user=%s id=%s status=%s",
            username,
            id_consultado,
            response.status_code,
        )
        return JSONResponse(payload, status_code=response.status_code)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("servicios_detail_proxy", exc, user=username, id=id_consultado)


class ServicioCategoriaUpdateRequestModel(BaseModel):
    categoria: int
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.patch("/api/servicios/{id}/categoria")
async def servicio_categoria_web(
    request: Request,
    id: int,
    body: ServicioCategoriaUpdateRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Cambia la categoría (C0-C6) de un Servicio individual — sólo admin. Proxya al endpoint
    interno, mismo patrón que `servicios_search_web`/`servicios_detail_web`."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=servicio_categoria result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.patch(
                f"{INTERNAL_API_BASE_URL}/servicios/{id}/categoria",
                json={"categoria": body.categoria},
                headers=_internal_api_auth_headers(),
            )

        payload: dict[str, Any]
        payload = payload_de_upstream(response, "Error actualizando categoría", "servicio_categoria_proxy")

        logger.info(
            "action=servicio_categoria user=%s id=%s categoria=%s status=%s",
            username,
            id,
            body.categoria,
            response.status_code,
        )
        return JSONResponse(payload, status_code=response.status_code)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("servicio_categoria", exc, user=username, id=id)


class ServicioCategoriaHeredarRequestModel(BaseModel):
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.patch("/api/servicios/{id}/categoria/heredar")
async def servicio_categoria_heredar_web(
    request: Request,
    id: int,
    body: ServicioCategoriaHeredarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Quita la excepción de categoría de un Servicio para que vuelva a heredar la de su cliente —
    sólo admin. Proxya al endpoint interno, mismo patrón que `servicio_categoria_web`."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=servicio_categoria_heredar result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.patch(
                f"{INTERNAL_API_BASE_URL}/servicios/{id}/categoria/heredar",
                headers=_internal_api_auth_headers(),
            )

        payload: dict[str, Any]
        payload = payload_de_upstream(response, "Error restaurando la categoría heredada", "servicio_categoria_restaurar_proxy")

        logger.info(
            "action=servicio_categoria_heredar user=%s id=%s status=%s",
            username,
            id,
            response.status_code,
        )
        return JSONResponse(payload, status_code=response.status_code)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("servicio_categoria_heredar", exc, user=username, id=id)


class ServicioVerificableUpdateRequestModel(BaseModel):
    es_verificable: bool
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.patch("/api/servicios/{id}/verificable")
async def servicio_verificable_web(
    request: Request,
    id: int,
    body: ServicioVerificableUpdateRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Fija el override de verificabilidad de un Servicio individual — sólo admin. Proxya al
    endpoint interno, mismo patrón que `servicio_categoria_web`."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=servicio_verificable result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.patch(
                f"{INTERNAL_API_BASE_URL}/servicios/{id}/verificable",
                json={"es_verificable": body.es_verificable},
                headers=_internal_api_auth_headers(),
            )

        payload: dict[str, Any]
        payload = payload_de_upstream(response, "Error actualizando verificabilidad", "servicio_verificabilidad_proxy")

        logger.info(
            "action=servicio_verificable user=%s id=%s es_verificable=%s status=%s",
            username,
            id,
            body.es_verificable,
            response.status_code,
        )
        return JSONResponse(payload, status_code=response.status_code)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("servicio_verificable", exc, user=username, id=id)


class ServicioProvRefrescarRequestModel(BaseModel):
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.post("/api/servicios/prov/refrescar")
async def servicio_prov_refrescar_web(
    request: Request,
    id: str,
    body: ServicioProvRefrescarRequestModel,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Dispara el refresco on-demand de un Servicio contra PROV. Proxya al endpoint interno, mismo
    patrón que `servicios_detail_web`/`servicio_categoria_web` — visible a cualquier usuario
    autenticado (no sólo admin), igual que el botón en `ServicioDetalleView.vue` (Task 10), que no
    está condicionado a `isAdmin`."""
    username, _ = usuario
    id_consultado = (id or "").strip()
    if not id_consultado:
        return JSONResponse({"error": "ID requerido"}, status_code=400)

    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=servicio_prov_refrescar result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    try:
        # 70s, no los 30s del resto de los proxies de este archivo: el backend acota sus
        # reintentos a PROV a `_PROV_REFRESCAR_MAX_REINTENTOS=1` (~61s de peor caso, ver
        # api/app/routes/servicios.py) — este timeout necesita margen sobre ese peor caso, no
        # sobre el default de 30s que usan las demás rutas (que no llaman a una API externa).
        async with httpx.AsyncClient(timeout=70.0) as client:
            response = await client.post(
                f"{INTERNAL_API_BASE_URL}/servicios/prov/refrescar",
                params={"id": id_consultado},
                headers=_internal_api_auth_headers(),
            )

        payload: dict[str, Any]
        payload = payload_de_upstream(response, "Error refrescando servicio desde PROV", "servicio_refresh_prov_proxy")

        logger.info(
            "action=servicio_prov_refrescar user=%s id=%s status=%s",
            username,
            id_consultado,
            response.status_code,
        )
        return JSONResponse(payload, status_code=response.status_code)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("servicio_prov_refrescar", exc, user=username, id=id_consultado)


class ServiciosCategoriaMasivaRequestModel(BaseModel):
    servicio_ids: list[int]
    categoria: int
    csrf_token: str | None = Field(default=None, description="Token CSRF de la sesión")


@router.patch("/api/servicios/bulk-categoria")
async def servicios_categoria_masiva_web(
    request: Request,
    body: ServiciosCategoriaMasivaRequestModel,
    usuario: UsuarioSesion = Depends(usuario_admin),
) -> JSONResponse:
    """Cambia la categoría (C0-C6) de un lote de Servicios — sólo admin. Proxya al endpoint interno."""
    username = usuario.username
    expected_csrf = request.session.get("csrf")
    testing_mode = os.getenv("TESTING", "false").lower() == "true"
    if not testing_mode and (not body.csrf_token or body.csrf_token != expected_csrf):
        logger.warning("action=servicios_categoria_masiva result=fail reason=csrf user=%s", username)
        return JSONResponse({"error": "CSRF inválido"}, status_code=403)

    if not body.servicio_ids:
        return JSONResponse({"error": "No se especificaron servicios a actualizar"}, status_code=400)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.patch(
                f"{INTERNAL_API_BASE_URL}/servicios/bulk-categoria",
                json={"servicio_ids": body.servicio_ids, "categoria": body.categoria},
                headers=_internal_api_auth_headers(),
            )

        payload: dict[str, Any]
        payload = payload_de_upstream(response, "Error actualizando categoría", "servicio_categoria_proxy")

        logger.info(
            "action=servicios_categoria_masiva user=%s cantidad=%d categoria=%s status=%s",
            username,
            len(body.servicio_ids),
            body.categoria,
            response.status_code,
        )
        return JSONResponse(payload, status_code=response.status_code)
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:  # noqa: BLE001
        return error_interno("servicios_categoria_masiva", exc, user=username)


@router.post("/api/infra/upload_tracking")
async def upload_tracking_web(
    file: UploadFile = File(...),
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Procesa un archivo de tracking de fibra óptica."""

    username, _ = usuario

    # Validar extensión
    if not file.filename or not file.filename.lower().endswith(".txt"):
        return JSONResponse(
            {"error": "El archivo debe tener extensión .txt"},
            status_code=400
        )

    try:
        from core.parsers.tracking_parser import parse_tracking
        from core.services.infra_service import (
            _get_or_create_empalme,
            _resolve_camara_o_registrar_sin_match,
        )
        from db.models.infra import Servicio
        from db.session import SessionLocal

        # Leer contenido
        content = await file.read()
        try:
            raw_text = content.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = content.decode("latin-1")

        # Parsear
        result = parse_tracking(raw_text, file.filename)

        if not result.servicio_id:
            return JSONResponse(
                {"error": f"No se pudo extraer el ID del servicio desde: {file.filename}"},
                status_code=400
            )

        topologia = result.get_topologia()
        if not topologia:
            return JSONResponse(
                {"error": "No se encontraron empalmes/ubicaciones en el archivo"},
                status_code=400
            )

        logger.info(
            "action=upload_tracking user=%s filename=%s servicio_id=%s empalmes=%d",
            username,
            file.filename,
            result.servicio_id,
            len(topologia),
        )

        camaras_existentes = 0
        ubicaciones_sin_match = 0
        empalmes_registrados = 0

        with SessionLocal() as session:
            # Obtener o crear servicio
            servicio = session.query(Servicio).filter(
                Servicio.servicio_id == result.servicio_id
            ).first()

            if servicio:
                servicio.nombre_archivo_origen = file.filename
            else:
                servicio = Servicio(
                    servicio_id=result.servicio_id,
                    nombre_archivo_origen=file.filename,
                )
                session.add(servicio)
                session.flush()

            servicio.raw_tracking_data = result.to_dict()

            # Procesar empalmes — la búsqueda de cámara/botella y el registro de "sin match" están
            # unificados en `core.services.infra_service` (Tarea 3 del refactor "Adjuntar
            # tracking", 2026-08-23): antes esta ruta tenía su propia búsqueda O(n) duplicada de
            # `api/app/routes/infra.py` e `InfraService`.
            for empalme_id, ubicacion in topologia:
                # Cromo Red es la fuente de verdad del inventario: nunca se crea una Camara nueva.
                # Sin match, se registra un IngresoSinMatch (dentro de la función) y el empalme
                # queda sin camara_id — el procesamiento nunca se bloquea por esto.
                camara = _resolve_camara_o_registrar_sin_match(
                    session, ubicacion, filename=file.filename, servicio_id=result.servicio_id
                )
                if camara is not None:
                    camaras_existentes += 1
                else:
                    ubicaciones_sin_match += 1

                # Registrar empalme — `_get_or_create_empalme` nunca pisa con `None` un
                # `camara_id` previo válido de una corrida anterior cuando esta corrida no matchea.
                tracking_id_completo = f"{result.servicio_id}_{empalme_id}"
                empalme, empalme_nuevo = _get_or_create_empalme(session, tracking_id_completo, camara)
                if servicio not in empalme.servicios:
                    empalme.servicios.append(servicio)
                if empalme_nuevo:
                    empalmes_registrados += 1

            session.commit()

            logger.info(
                "action=upload_tracking_complete user=%s servicio_id=%s camaras_existentes=%d "
                "ubicaciones_sin_match=%d empalmes=%d",
                username,
                result.servicio_id,
                camaras_existentes,
                ubicaciones_sin_match,
                empalmes_registrados,
            )

            return JSONResponse({
                "status": "ok",
                "servicios_procesados": 1,
                "servicio_id": result.servicio_id,
                "camaras_existentes": camaras_existentes,
                "ubicaciones_sin_match": ubicaciones_sin_match,
                "empalmes_registrados": empalmes_registrados,
                "mensaje": f"Tracking del servicio {result.servicio_id} procesado correctamente",
            })

    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("upload_tracking", exc, user=username, filename=file.filename)


class TrackingResolveRequestModel(BaseModel):
    """Request para resolver un tracking."""
    action: str  # CREATE_NEW, MERGE_APPEND, REPLACE, BRANCH, CONFIRM_UPGRADE
    content: str
    filename: str
    target_ruta_id: Optional[int] = None
    new_ruta_name: Optional[str] = None
    new_ruta_tipo: Optional[str] = None  # PRINCIPAL, BACKUP, ALTERNATIVA
    # Campos para upgrade
    old_service_id: Optional[str] = None  # ID del servicio a migrar
    old_service_db_id: Optional[int] = None  # DB ID del servicio a migrar


@router.post("/api/infra/trackings/analyze")
async def analyze_tracking_web(
    file: UploadFile = File(...),
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Analiza un archivo de tracking (Fase 1 del Portero).
    
    Detecta si el servicio es nuevo, idéntico o hay conflicto.
    """
    username, _ = usuario
    
    # Leer contenido del archivo
    raw_bytes = await file.read()
    try:
        raw_content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raw_content = raw_bytes.decode("latin-1")
    
    filename_used = file.filename or "unknown.txt"
    
    try:
        from core.services.infra_service import InfraService
        from db.session import SessionLocal
        
        with SessionLocal() as session:
            service = InfraService(session)
            result = service.analyze_tracking(raw_content, filename_used)
            
            logger.info(
                "action=analyze_tracking user=%s filename=%s status=%s servicio=%s",
                username,
                filename_used,
                result.status.value,
                result.servicio_id,
            )
            
            # Convertir rutas_existentes a dict
            rutas_list = []
            for r in result.rutas_existentes:
                rutas_list.append(r.to_dict())
            
            # Sugerir acción basada en el status
            suggested_action = None
            if result.status.value == "NEW":
                suggested_action = "CREATE_NEW"
            elif result.status.value == "IDENTICAL":
                suggested_action = "SKIP"
            elif result.status.value == "CONFLICT":
                suggested_action = "REPLACE"  # Default, el usuario puede elegir otra
            elif result.status.value == "POTENTIAL_UPGRADE":
                suggested_action = "CONFIRM_UPGRADE"
            
            return JSONResponse({
                "status": result.status.value,
                "servicio_id": result.servicio_id,
                "servicio_db_id": result.servicio_db_id,
                "nuevo_hash": result.nuevo_hash,
                "rutas_existentes": rutas_list,
                "ruta_identica_id": result.ruta_identica_id,
                "parsed_empalmes_count": result.parsed_empalmes_count,
                "empalmes_nuevos": result.parsed_empalmes_count,
                "message": result.message,
                "error": result.error,
                "suggested_action": suggested_action,
                "hash_match": result.ruta_identica_id is not None,
                "upgrade_info": result.upgrade_info.to_dict() if result.upgrade_info else None,
                "strand_info": result.strand_info.to_dict() if result.strand_info else None,
                "punta_a_sitio": result.punta_a_sitio,
                "punta_b_sitio": result.punta_b_sitio,
            })
            
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("analyze_tracking", exc, user=username, filename=filename_used)


@router.post("/api/infra/trackings/resolve")
async def resolve_tracking_web(
    body: TrackingResolveRequestModel,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Resuelve un tracking ejecutando la acción (Fase 2 del Portero).
    
    Acciones: CREATE_NEW, MERGE_APPEND, REPLACE, BRANCH, ADD_STRAND, SKIP
    """
    username, _ = usuario
    
    # Validar acción
    valid_actions = ["CREATE_NEW", "MERGE_APPEND", "REPLACE", "BRANCH", "ADD_STRAND", "SKIP", "CONFIRM_UPGRADE"]
    action_upper = body.action.upper()
    if action_upper not in valid_actions:
        return JSONResponse(
            {"error": f"Acción inválida: {body.action}. Opciones: {', '.join(valid_actions)}"},
            status_code=400
        )
    
    # SKIP no hace nada
    if action_upper == "SKIP":
        return JSONResponse({
            "success": True,
            "action": "SKIP",
            "message": "Operación omitida por el usuario",
        })
    
    # CONFIRM_UPGRADE: Migrar servicio antiguo al nuevo ID
    if action_upper == "CONFIRM_UPGRADE":
        if not body.old_service_id or not body.old_service_db_id:
            return JSONResponse(
                {"error": "Se requiere old_service_id y old_service_db_id para CONFIRM_UPGRADE"},
                status_code=400
            )
        
        try:
            from core.services.infra_service import InfraService
            from core.parsers.tracking_parser import parse_tracking
            from db.session import SessionLocal
            
            with SessionLocal() as session:
                service = InfraService(session)
                
                # Parsear el nuevo archivo para obtener el nuevo ID
                parsed = parse_tracking(body.content, body.filename)
                new_service_id = parsed.servicio_id
                new_alias = parsed.alias_id
                
                # Ejecutar el upgrade
                result = service.execute_upgrade(
                    old_service_db_id=body.old_service_db_id,
                    new_service_id=new_service_id,
                    new_alias=new_alias,
                    raw_content=body.content,
                    filename=body.filename,
                )
                
                logger.info(
                    "action=confirm_upgrade user=%s old_id=%s new_id=%s success=%s",
                    username,
                    body.old_service_id,
                    new_service_id,
                    result.get('success', False),
                )
                
                return JSONResponse(result)
                
        except (HTTPException, ErrorDeDominio):
            raise
        except Exception as exc:
            return error_interno("confirm_upgrade", exc, user=username, old_id=body.old_service_id)
    
    try:
        from core.services.infra_service import InfraService, ResolveAction, RutaTipo
        from db.session import SessionLocal
        
        # Convertir acción
        action = ResolveAction(action_upper)
        
        # Convertir tipo de ruta si se especifica
        ruta_tipo = RutaTipo.ALTERNATIVA
        if body.new_ruta_tipo:
            try:
                ruta_tipo = RutaTipo(body.new_ruta_tipo.upper())
            except ValueError:
                pass  # Usar default
        
        with SessionLocal() as session:
            service = InfraService(session)
            result = service.resolve_tracking(
                action=action,
                raw_content=body.content,
                filename=body.filename,
                target_ruta_id=body.target_ruta_id,
                new_ruta_name=body.new_ruta_name,
                new_ruta_tipo=ruta_tipo,
            )
            
            logger.info(
                "action=resolve_tracking user=%s action=%s servicio=%s success=%s",
                username,
                action_upper,
                result.servicio_id,
                result.success,
            )
            
            return JSONResponse({
                "success": result.success,
                "action": result.action.value,
                "servicio_id": result.servicio_id,
                "servicio_db_id": result.servicio_db_id,
                "ruta_id": result.ruta_id,
                "ruta_nombre": result.ruta_nombre,
                "camaras_nuevas": result.camaras_nuevas,
                "camaras_existentes": result.camaras_existentes,
                "empalmes_creados": result.empalmes_creados,
                "empalmes_asociados": result.empalmes_asociados,
                "ubicaciones_sin_match": result.ubicaciones_sin_match,
                "message": result.message,
                "error": result.error,
            })
            
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("resolve_tracking", exc, user=username, action=body.action)


@router.delete("/api/infra/servicios/{servicio_id}/empalmes")
async def delete_servicio_empalmes_web(
    servicio_id: str,
    usuario: UsuarioSesion = Depends(usuario_sesion),
) -> JSONResponse:
    """Elimina todas las asociaciones de empalmes de un servicio.
    
    ⚠️ PRECAUCIÓN: Operación destructiva.
    """
    username, _ = usuario
    
    try:
        from db.models.infra import Servicio
        from db.session import SessionLocal
        
        with SessionLocal() as session:
            servicio = session.query(Servicio).filter(
                Servicio.servicio_id == servicio_id
            ).first()
            
            if not servicio:
                return JSONResponse(
                    {"error": f"Servicio {servicio_id} no encontrado"},
                    status_code=404
                )
            
            # Contar antes de eliminar
            empalmes_legacy_count = len(servicio.empalmes)
            rutas_count = len(servicio.rutas)
            
            # Eliminar asociaciones legacy
            servicio.empalmes.clear()
            
            # Eliminar rutas
            for ruta in list(servicio.rutas):
                session.delete(ruta)
            
            session.commit()
            
            logger.info(
                "action=delete_servicio_empalmes user=%s servicio_id=%s empalmes=%d rutas=%d",
                username,
                servicio_id,
                empalmes_legacy_count,
                rutas_count,
            )
            
            return JSONResponse({
                "status": "ok",
                "servicio_id": servicio_id,
                "message": f"Eliminadas {empalmes_legacy_count} asociaciones y {rutas_count} rutas",
                "empalmes_legacy_eliminados": empalmes_legacy_count,
                "rutas_eliminadas": rutas_count,
            })
            
    except (HTTPException, ErrorDeDominio):
        raise
    except Exception as exc:
        return error_interno("delete_servicio_empalmes", exc, user=username, servicio_id=servicio_id)
