# Nombre de archivo: fo_monitor_routes.py
# Ubicación de archivo: web/fo_monitor_routes.py
# Descripción: Endpoints /api/fo-monitor/* (intervenciones, GeoJSON del mapa, mapa base PMTiles con Range) y config admin

"""Rutas de FO Monitor para el SPA. Lectura: cualquier usuario autenticado. Mutaciones
(verificación manual, reconocer como ajena, config del piloto): sólo admin + CSRF en el body
(mismo criterio que `web/app/main.py`, `TESTING=true` lo saltea).

Mapa base offline: Starlette 0.38.6 (la versión fijada) no soporta HTTP Range en `FileResponse`/
`StaticFiles` y la librería `pmtiles` del navegador lo necesita sí o sí, así que
`/api/fo-monitor/basemap/{ruta}` implementa `Range: bytes=a-b` (206 + `Content-Range`). Los
archivos viven en un volumen de sólo lectura (`FOMON_BASEMAP_DIR`, default `/app/data/fo_monitor`),
fuera de la imagen.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from core.services.fo_monitor import consultas_web

logger = logging.getLogger("web.fo_monitor")

BASEMAP_DIR = Path(os.getenv("FOMON_BASEMAP_DIR", "/app/data/fo_monitor"))
BASEMAP_MODO = os.getenv("FOMON_BASEMAP_MODO", "local")  # local | osm
PMTILES_ARCHIVO = os.getenv("FOMON_BASEMAP_PMTILES", "amba.pmtiles")
_TIPOS = {
    ".pmtiles": "application/octet-stream", ".json": "application/json", ".pbf": "application/x-protobuf",
    ".png": "image/png", ".geojson": "application/geo+json",
}
_RE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CHUNK = 256 * 1024
_cache_red: dict[str, Any] = {"huella": None, "cuerpo": None, "etag": None}


def _sesion_local():
    from db.session import SessionLocal

    return SessionLocal()


def _auth(request: Request) -> tuple[str, str]:
    username = request.session.get("username")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return username, request.session.get("role", "user")


def _admin(request: Request, csrf_token: Optional[str]) -> str:
    username, role = _auth(request)
    if role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permisos insuficientes")
    testing = os.getenv("TESTING", "false").lower() == "true"
    if not testing and (not csrf_token or csrf_token != request.session.get("csrf")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF inválido")
    return username


class VerificacionManualBody(BaseModel):
    csrf_token: Optional[str] = None
    camara_id: Optional[int] = None
    botella_n_id: Optional[int] = None
    cable_n_id: Optional[int] = None


class ReconocimientoBody(BaseModel):
    csrf_token: Optional[str] = None
    motivo: str = Field(min_length=3, max_length=500)
    servicio_pk: Optional[int] = None


class ConfigBody(BaseModel):
    csrf_token: Optional[str] = None
    activo: Optional[bool] = None
    ventana_desde: Optional[datetime] = None
    ventana_hasta: Optional[datetime] = None
    tope_mensajes_diario: Optional[int] = Field(default=None, ge=0, le=5000)
    max_ids_por_mensaje: Optional[int] = Field(default=None, ge=1, le=20)
    timeout_base_s: Optional[int] = Field(default=None, ge=30, le=3600)
    timeout_por_servicio_s: Optional[int] = Field(default=None, ge=0, le=300)
    concurrencia: Optional[int] = Field(default=None, ge=1, le=10)
    prompt_version: Optional[str] = Field(default=None, pattern=r"^v[1-4]$")


def _rango(header: Optional[str], tamano: int) -> Optional[tuple[int, int]]:
    """`bytes=a-b`, `bytes=a-` o `bytes=-n` (sufijo). None si no hay header; ValueError si es inválido."""
    if not header:
        return None
    m = _RE_RANGE.match(header.strip())
    if not m or (not m.group(1) and not m.group(2)):
        raise ValueError(header)
    if not m.group(1):
        n = int(m.group(2))
        inicio, fin = max(0, tamano - n), tamano - 1
    else:
        inicio = int(m.group(1))
        fin = min(int(m.group(2)), tamano - 1) if m.group(2) else tamano - 1
    if inicio > fin or inicio >= tamano:
        raise ValueError(header)
    return inicio, fin


def _leer(ruta: Path, inicio: int, fin: int) -> Iterator[bytes]:
    with ruta.open("rb") as fh:
        fh.seek(inicio)
        restante = fin - inicio + 1
        while restante > 0:
            bloque = fh.read(min(_CHUNK, restante))
            if not bloque:
                break
            restante -= len(bloque)
            yield bloque


def servir_con_rango(ruta: Path, request: Request) -> Response:
    tamano = ruta.stat().st_size
    etag = '"%s"' % hashlib.md5(f"{ruta.name}-{tamano}-{ruta.stat().st_mtime_ns}".encode()).hexdigest()
    base = {"Accept-Ranges": "bytes", "ETag": etag, "Cache-Control": "private, max-age=86400"}
    tipo = _TIPOS.get(ruta.suffix.lower(), "application/octet-stream")
    try:
        rango = _rango(request.headers.get("range"), tamano)
    except ValueError:
        return Response(status_code=416, headers={**base, "Content-Range": f"bytes */{tamano}"})
    if rango is None:
        return StreamingResponse(_leer(ruta, 0, tamano - 1), media_type=tipo,
                                 headers={**base, "Content-Length": str(tamano)})
    inicio, fin = rango
    return StreamingResponse(
        _leer(ruta, inicio, fin), status_code=206, media_type=tipo,
        headers={**base, "Content-Range": f"bytes {inicio}-{fin}/{tamano}", "Content-Length": str(fin - inicio + 1)},
    )


def mount_fo_monitor_routes(app: FastAPI) -> None:
    @app.get("/api/fo-monitor/intervenciones")
    def fomon_listar(request: Request, estado: Optional[str] = None, desde: Optional[datetime] = None,
                     hasta: Optional[datetime] = None, tecnico: Optional[str] = None, cable: Optional[str] = None,
                     limit: int = 50, offset: int = 0):
        _auth(request)
        with _sesion_local() as s:
            return consultas_web.listar_intervenciones(s, estado=estado, desde=desde, hasta=hasta,
                                                       tecnico=tecnico, cable=cable, limit=limit, offset=offset)

    @app.get("/api/fo-monitor/intervenciones/{intervencion_id}")
    def fomon_detalle(request: Request, intervencion_id: int):
        _auth(request)
        with _sesion_local() as s:
            try:
                return consultas_web.detalle_intervencion(s, intervencion_id)
            except consultas_web.NoEncontrado:
                return JSONResponse({"error": "Intervención inexistente"}, status_code=404)

    @app.get("/api/fo-monitor/mapa/intervenciones")
    def fomon_mapa_intervenciones(request: Request, horas: int = 24):
        _auth(request)
        with _sesion_local() as s:
            return consultas_web.geojson_intervenciones(s, horas=horas)

    @app.get("/api/fo-monitor/mapa/red")
    def fomon_mapa_red(request: Request):
        _auth(request)
        with _sesion_local() as s:
            huella = consultas_web.huella_red(s)
            if _cache_red["huella"] != huella:
                cuerpo = consultas_web.geojson_red(s)
                _cache_red.update(huella=huella, cuerpo=cuerpo.encode(),
                                  etag='"%s"' % hashlib.md5(huella.encode()).hexdigest())
        if request.headers.get("if-none-match") == _cache_red["etag"]:
            return Response(status_code=304, headers={"ETag": _cache_red["etag"]})
        return Response(_cache_red["cuerpo"], media_type="application/geo+json",
                        headers={"ETag": _cache_red["etag"], "Cache-Control": "private, no-cache"})

    @app.get("/api/fo-monitor/mapa/botellas")
    def fomon_mapa_botellas(request: Request, bbox: Optional[str] = None, limit: int = 5000):
        _auth(request)
        with _sesion_local() as s:
            try:
                return consultas_web.geojson_botellas(s, bbox=bbox, limit=limit)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/fo-monitor/cables/{cable_n_id}/historial")
    def fomon_historial(request: Request, cable_n_id: int, limit: int = 50):
        _auth(request)
        with _sesion_local() as s:
            return consultas_web.historial_cable(s, cable_n_id, limit=limit)

    @app.get("/api/fo-monitor/mapa/config")
    def fomon_mapa_config(request: Request):
        _auth(request)
        disponible = (BASEMAP_DIR / PMTILES_ARCHIVO).is_file()
        modo = BASEMAP_MODO if BASEMAP_MODO == "osm" or disponible else "osm"
        return {
            "modo": modo,
            "pmtiles_url": f"/api/fo-monitor/basemap/{PMTILES_ARCHIVO}",
            "glyphs_url": "/api/fo-monitor/basemap/fonts/{fontstack}/{range}.pbf",
            "sprite_url": "/api/fo-monitor/basemap/sprites/v4/light",
            "pmtiles_disponible": disponible,
        }

    @app.get("/api/fo-monitor/basemap/{ruta:path}")
    def fomon_basemap(request: Request, ruta: str):
        _auth(request)
        base = BASEMAP_DIR.resolve()
        destino = (base / ruta).resolve()
        if base not in destino.parents or not destino.is_file():
            return JSONResponse({"error": "Archivo inexistente"}, status_code=404)
        return servir_con_rango(destino, request)

    @app.post("/api/fo-monitor/verificaciones")
    def fomon_verificacion_manual(request: Request, body: VerificacionManualBody):
        usuario = _admin(request, body.csrf_token)
        from datetime import timezone

        from core.services.fo_monitor.motor import crear_intervencion_manual

        with _sesion_local() as s:
            try:
                interv = crear_intervencion_manual(
                    s, usuario=usuario, ahora=datetime.now(timezone.utc), camara_id=body.camara_id,
                    botella_n_id=body.botella_n_id, cable_n_id=body.cable_n_id,
                )
                s.commit()
            except ValueError as exc:
                s.rollback()
                return JSONResponse({"error": str(exc)}, status_code=400)
            logger.info("action=fomon_verificacion_manual user=%s intervencion=%s", usuario, interv.id)
            return {"intervencion_id": interv.id}

    @app.post("/api/fo-monitor/intervenciones/{intervencion_id}/reconocimientos")
    def fomon_reconocer(request: Request, intervencion_id: int, body: ReconocimientoBody):
        usuario = _admin(request, body.csrf_token)
        with _sesion_local() as s:
            try:
                return consultas_web.reconocer(s, intervencion_id, usuario=usuario, motivo=body.motivo,
                                               servicio_pk=body.servicio_pk)
            except consultas_web.NoEncontrado:
                return JSONResponse({"error": "Intervención inexistente"}, status_code=404)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/admin/fo-monitor/config")
    def fomon_config_leer(request: Request):
        _, role = _auth(request)
        if role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permisos insuficientes")
        with _sesion_local() as s:
            return consultas_web.leer_config(s)

    @app.put("/api/admin/fo-monitor/config")
    def fomon_config_actualizar(request: Request, body: ConfigBody):
        usuario = _admin(request, body.csrf_token)
        cambios = body.model_dump(exclude_unset=True, exclude={"csrf_token"})
        with _sesion_local() as s:
            resultado = consultas_web.actualizar_config(s, cambios, usuario=usuario)
        logger.info("action=fomon_config user=%s cambios=%s", usuario, sorted(cambios))
        return resultado
