# Nombre de archivo: static_map.py
# Ubicación de archivo: core/maps/static_map.py
# Descripción: Utilidades para generar mapas estáticos en PNG a partir de coordenadas

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

try:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt  # noqa: E402

    _MATPLOTLIB_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - entornos sin matplotlib
    matplotlib = None  # type: ignore[assignment]
    plt = None  # type: ignore[assignment]
    _MATPLOTLIB_AVAILABLE = False

logger = logging.getLogger(__name__)


Point = Tuple[float, float]

# Los servidores de tiles de OpenStreetMap bloquean el User-Agent genérico de
# contextily ("contextily-<uuid>") y devuelven, con HTTP 200, una imagen de
# "Access blocked" en lugar del tile: el mapa salía tapado por esos avisos.
# La política de uso de OSM exige un User-Agent que identifique a la aplicación.
DEFAULT_TILE_USER_AGENT = "LAS-FOCAS/1.0 (Metrotel; informes de infraestructura FO; +https://www.metrotel.com.ar)"


def _tile_user_agent() -> str:
    return (os.getenv("MAPS_TILE_USER_AGENT") or "").strip() or DEFAULT_TILE_USER_AGENT


@dataclass(frozen=True)
class MapStyle:
    """Configura la apariencia del mapa estático."""

    provider: str | None = "OpenStreetMap.Mapnik"
    dpi: int = 220
    figsize: Tuple[float, float] = (6.2, 4.8)
    marker: str = "x"
    marker_size: int = 180
    marker_color: str = "#0B5394"
    halo_size: int = 320
    halo_color: str = "#000000"
    halo_alpha: float = 0.18
    line_width: float = 3.6
    pad_ratio: float = 0.12
    min_pad_meters: float = 320.0
    single_point_meters: float = 420.0
    min_pad_degrees: float = 0.05
    # Si se indica, el PNG se reduce a una paleta de N colores (los tiles de
    # calles ya son de paleta): baja el peso ~4x sin pérdida visible.
    palette_colors: int | None = None


def build_static_map_png(
    points: Sequence[Tuple[float | None, float | None]],
    out_path: Path,
    style: MapStyle = MapStyle(),
) -> Path:
    """Genera un mapa estático con estilo "calles" similar a Google Maps."""

    if not _MATPLOTLIB_AVAILABLE or plt is None:
        raise RuntimeError("Matplotlib no está disponible para generar mapas estáticos")

    valid_points = _sanitize_points(points)
    if not valid_points:
        raise ValueError("Se requieren coordenadas válidas para generar el mapa")

    fig, ax = plt.subplots(figsize=style.figsize, dpi=style.dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f7f9fb")

    basemap_was_drawn = False
    try:
        if style.provider:
            import contextily as ctx  # type: ignore
            from pyproj import Transformer  # type: ignore

            ctx.tile.USER_AGENT = _tile_user_agent()

            transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
            xs: List[float] = []
            ys: List[float] = []
            for lat, lon in valid_points:
                x, y = transformer.transform(lon, lat)
                xs.append(x)
                ys.append(y)

            _draw_points(ax, xs, ys, style)
            _configure_bbox_projected(ax, xs, ys, style)
            ctx.add_basemap(
                ax,
                source=_resolve_provider(ctx, style.provider),
                crs="EPSG:3857",
                attribution_size=0,
            )
            ax.set_xticks([])
            ax.set_yticks([])
            basemap_was_drawn = True
        else:
            raise RuntimeError("Proveedor deshabilitado")
    except Exception:  # noqa: BLE001
        logger.exception("action=build_static_map_png stage=basemap_unavailable")
        longitudes = [lon for _, lon in valid_points]
        latitudes = [lat for lat, _ in valid_points]
        _draw_points(ax, longitudes, latitudes, style)
        _configure_bbox_geographic(ax, latitudes, longitudes, style)

    _remove_axes(ax)
    # El eje ocupa toda la figura: el PNG conserva exactamente la proporción de
    # ``figsize`` y el encuadre ya fue ajustado a esa misma proporción.
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=style.dpi)
    plt.close(fig)
    if style.palette_colors:
        _quantize_png(out_path, style.palette_colors)

    logger.info(
        "action=build_static_map_png stage=success path=%s points=%s basemap=%s",
        out_path,
        len(valid_points),
        basemap_was_drawn,
    )
    return out_path


def _quantize_png(path: Path, colors: int) -> None:
    try:
        from PIL import Image
    except ModuleNotFoundError:  # pragma: no cover - Pillow viene con matplotlib
        return
    with Image.open(path) as img:
        reduced = img.convert("RGB").quantize(
            colors=colors,
            method=Image.Quantize.MEDIANCUT,
            dither=Image.Dither.NONE,
        )
    reduced.save(path, optimize=True)


def _sanitize_points(points: Iterable[Tuple[float | None, float | None]]) -> List[Point]:
    cleaned: List[Point] = []
    for lat, lon in points:
        if lat is None or lon is None:
            continue
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):  # noqa: BLE001
            continue
        if math.isnan(lat_f) or math.isnan(lon_f):  # type: ignore[arg-type]
            continue
        cleaned.append((lat_f, lon_f))
    return cleaned


def _resolve_provider(ctx_module, provider: str):  # type: ignore[anno-var]
    node = ctx_module.providers
    for segment in provider.split("."):
        node = getattr(node, segment)
    return node


def _draw_points(ax, xs: List[float], ys: List[float], style: MapStyle) -> None:
    ax.scatter(
        xs,
        ys,
        marker="o",
        s=style.halo_size,
        linewidths=0,
        color=style.halo_color,
        alpha=style.halo_alpha,
        zorder=4,
    )
    ax.scatter(
        xs,
        ys,
        marker=style.marker,
        s=style.marker_size,
        linewidths=style.line_width,
        color=style.marker_color,
        zorder=5,
    )


def _configure_bbox_projected(ax, xs: List[float], ys: List[float], style: MapStyle) -> None:
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if len(xs) == 1:
        pad_x = pad_y = style.single_point_meters
    else:
        pad_x = max((max_x - min_x) * style.pad_ratio, style.min_pad_meters)
        pad_y = max((max_y - min_y) * style.pad_ratio, style.min_pad_meters)
    _apply_limits(ax, (min_x - pad_x, max_x + pad_x), (min_y - pad_y, max_y + pad_y), style)


def _configure_bbox_geographic(ax, latitudes: List[float], longitudes: List[float], style: MapStyle) -> None:
    min_lat, max_lat = min(latitudes), max(latitudes)
    min_lon, max_lon = min(longitudes), max(longitudes)
    if len(latitudes) == 1:
        pad_lon = pad_lat = style.min_pad_degrees
    else:
        pad_lon = max((max_lon - min_lon) * style.pad_ratio, style.min_pad_degrees)
        pad_lat = max((max_lat - min_lat) * style.pad_ratio, style.min_pad_degrees)
    _apply_limits(
        ax,
        (min_lon - pad_lon, max_lon + pad_lon),
        (min_lat - pad_lat, max_lat + pad_lat),
        style,
    )


def fit_bounds_to_aspect(
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    aspect: float,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Expande el eje corto del encuadre para que ancho/alto == ``aspect``.

    Mantiene el centro y nunca recorta: todos los puntos siguen dentro.
    """

    x0, x1 = xlim
    y0, y1 = ylim
    width = x1 - x0
    height = y1 - y0
    if width <= 0 or height <= 0 or aspect <= 0:
        return xlim, ylim
    if width / height < aspect:
        new_width = height * aspect
        cx = (x0 + x1) / 2
        return (cx - new_width / 2, cx + new_width / 2), ylim
    new_height = width / aspect
    cy = (y0 + y1) / 2
    return xlim, (cy - new_height / 2, cy + new_height / 2)


def _apply_limits(
    ax,
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    style: MapStyle,
) -> None:
    width_in, height_in = style.figsize
    xlim, ylim = fit_bounds_to_aspect(xlim, ylim, width_in / height_in)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)


def _remove_axes(ax) -> None:
    ax.set_axis_off()
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    for spine in ax.spines.values():
        spine.set_visible(False)