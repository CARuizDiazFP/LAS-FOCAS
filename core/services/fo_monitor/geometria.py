# Nombre de archivo: geometria.py
# Ubicación de archivo: core/services/fo_monitor/geometria.py
# Descripción: Polilínea de cable Cromo (pts_raw, EPSG:22185) → WGS84 simplificada + bbox, y carga incremental en fomon_cable_geo

"""Geometría de cables para el mapa de FO Monitor.

`app.cromo_cables.pts_raw` es una lista plana `[E, N, E, N, ...]` en Gauss-Krüger Faja 5 / POSGAR94
(EPSG:22185), sin reproyectar (medido 2026-10-13: 33.659 cables vigentes, todos con ≥ 2 puntos; el
extremo A queda a 1,5 m de su botella en p50/p99). Se simplifica en metros ANTES de reproyectar
(Douglas-Peucker sobre las coordenadas proyectadas) y se redondea a 6 decimales (~0,1 m).

Sin PostGIS (la imagen `postgres:16-alpine` no trae la extensión): el bbox se guarda en columnas
float y el filtro espacial es un rango simple, suficiente para ~34k filas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from pyproj import Transformer
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.services.cromo.camino_optico_service import CLASES_CABLE

_GK5_A_WGS84 = Transformer.from_crs("EPSG:22185", "EPSG:4326", always_xy=True)
TOLERANCIA_M = 1.0
DISTANCIA_EXTREMO_SOSPECHOSA_M = 100.0


@dataclass(frozen=True)
class Geometria:
    coords: list[list[float]]  # [[lon, lat], ...]
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


def _pares(pts_raw: Sequence[float]) -> list[tuple[float, float]]:
    valores = [float(v) for v in pts_raw]
    return [(valores[i], valores[i + 1]) for i in range(0, len(valores) - 1, 2)]


def _dist_punto_segmento(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def simplificar(puntos: list[tuple[float, float]], tolerancia: float = TOLERANCIA_M) -> list[tuple[float, float]]:
    """Douglas-Peucker iterativo (sin recursión: hay cables de 131 vértices)."""
    if len(puntos) <= 2:
        return list(puntos)
    conservar = [False] * len(puntos)
    conservar[0] = conservar[-1] = True
    pila = [(0, len(puntos) - 1)]
    while pila:
        ini, fin = pila.pop()
        max_d, idx = 0.0, -1
        for i in range(ini + 1, fin):
            d = _dist_punto_segmento(puntos[i], puntos[ini], puntos[fin])
            if d > max_d:
                max_d, idx = d, i
        if idx != -1 and max_d > tolerancia:
            conservar[idx] = True
            pila.extend(((ini, idx), (idx, fin)))
    return [p for p, k in zip(puntos, conservar) if k]


def geometria_desde_pts(pts_raw: Optional[Sequence[float]], tolerancia: float = TOLERANCIA_M) -> Optional[Geometria]:
    if not pts_raw or len(pts_raw) < 4:
        return None
    puntos = simplificar(_pares(pts_raw), tolerancia)
    xs, ys = zip(*puntos)
    lons, lats = _GK5_A_WGS84.transform(xs, ys)
    coords = [[round(lon, 6), round(lat, 6)] for lon, lat in zip(lons, lats)]
    return Geometria(coords, min(lons), min(lats), max(lons), max(lats))


def distancia_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    dx = (lon2 - lon1) * 111_320 * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * 110_540
    return math.hypot(dx, dy)


def calidad(geo: Geometria, extremo_a: Optional[tuple[float, float]], extremo_b: Optional[tuple[float, float]]) -> Optional[str]:
    """Marca un cable cuyo trazado no arranca/termina cerca de sus botellas. Cada extremo (lat, lon)
    tiene que estar cerca de ALGUNA punta: el trazado puede venir dibujado de B hacia A."""
    puntas = (geo.coords[0], geo.coords[-1])
    for extremo in (extremo_a, extremo_b):
        if extremo is None:
            continue
        lat, lon = extremo
        if min(distancia_m(p[0], p[1], lon, lat) for p in puntas) > DISTANCIA_EXTREMO_SOSPECHOSA_M:
            return "extremo_lejano"
    return None


_SQL_CABLES = text(
    """
    SELECT c.n_id, c.vmax, c.pts_raw,
           ba.latitud AS a_lat, ba.longitud AS a_lon, bb.latitud AS b_lat, bb.longitud AS b_lon
    FROM app.cromo_cables c
    LEFT JOIN app.fomon_cable_geo g ON g.cable_n_id = c.n_id
    LEFT JOIN app.cromo_botellas ba ON ba.n_id = c.extremo_a_n_id
    LEFT JOIN app.cromo_botellas bb ON bb.n_id = c.extremo_b_n_id
    WHERE c.vigente AND c.clase = ANY(:clases ::smallint[]) AND c.n_id > :desde
      AND (g.cable_n_id IS NULL OR g.vmax IS DISTINCT FROM c.vmax OR :forzar)
    ORDER BY c.n_id
    LIMIT :lote
    """
)

_SQL_UPSERT = text(
    """
    INSERT INTO app.fomon_cable_geo (cable_n_id, coords, min_lon, min_lat, max_lon, max_lat, vmax, calidad, actualizado_at)
    VALUES (:n_id, CAST(:coords AS jsonb), :min_lon, :min_lat, :max_lon, :max_lat, :vmax, :calidad, now())
    ON CONFLICT (cable_n_id) DO UPDATE SET
        coords = EXCLUDED.coords, min_lon = EXCLUDED.min_lon, min_lat = EXCLUDED.min_lat,
        max_lon = EXCLUDED.max_lon, max_lat = EXCLUDED.max_lat, vmax = EXCLUDED.vmax,
        calidad = EXCLUDED.calidad, actualizado_at = now()
    """
)

_SQL_PURGAR = text(
    """
    DELETE FROM app.fomon_cable_geo g
    WHERE NOT EXISTS (
        SELECT 1 FROM app.cromo_cables c
        WHERE c.n_id = g.cable_n_id AND c.vigente AND c.clase = ANY(:clases ::smallint[])
    )
    """
)


@dataclass
class ResumenGeo:
    actualizados: int = 0
    sin_geometria: int = 0
    marcados_calidad: int = 0
    purgados: int = 0


def actualizar_geometrias(session: Session, *, forzar: bool = False, lote: int = 2000,
                          clases: Iterable[int] = CLASES_CABLE) -> ResumenGeo:
    """Carga incremental: sólo cables nuevos o con `vmax` distinto. Idempotente."""
    import json

    resumen = ResumenGeo()
    clases = sorted(clases)
    desde = 0
    while True:
        filas = session.execute(_SQL_CABLES, {"clases": clases, "forzar": forzar, "lote": lote, "desde": desde}).all()
        if not filas:
            break
        desde = filas[-1].n_id
        for f in filas:
            geo = geometria_desde_pts(f.pts_raw)
            if geo is None:
                resumen.sin_geometria += 1
                continue
            marca = calidad(
                geo,
                (f.a_lat, f.a_lon) if f.a_lat is not None else None,
                (f.b_lat, f.b_lon) if f.b_lat is not None else None,
            )
            resumen.marcados_calidad += marca is not None
            session.execute(_SQL_UPSERT, {
                "n_id": f.n_id, "coords": json.dumps(geo.coords), "min_lon": geo.min_lon, "min_lat": geo.min_lat,
                "max_lon": geo.max_lon, "max_lat": geo.max_lat, "vmax": f.vmax, "calidad": marca,
            })
            resumen.actualizados += 1
        session.commit()
    resumen.purgados = session.execute(_SQL_PURGAR, {"clases": clases}).rowcount or 0
    session.commit()
    return resumen
