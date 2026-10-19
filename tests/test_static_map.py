# Nombre de archivo: test_static_map.py
# Ubicación de archivo: tests/test_static_map.py
# Descripción: Pruebas para la generación de mapas estáticos con estilo tipo Google

import pytest

pytest.importorskip("matplotlib")

from matplotlib import pyplot as plt  # noqa: E402

from core.maps.static_map import MapStyle, build_static_map_png, fit_bounds_to_aspect


def test_build_static_map_png_creates_image_without_axes(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    original_subplots = plt.subplots

    def capture(*args, **kwargs):  # noqa: ANN001
        fig, ax = original_subplots(*args, **kwargs)
        captured["fig"] = fig
        captured["ax"] = ax
        return fig, ax

    monkeypatch.setattr(plt, "subplots", capture)

    output = tmp_path / "map.png"
    build_static_map_png([
        (-34.6037, -58.3816),
        (-34.6120, -58.3850),
    ], output, style=MapStyle(provider=None))

    assert output.exists()
    assert output.stat().st_size > 0

    ax = captured["ax"]
    assert hasattr(ax, "get_xaxis")
    assert not ax.get_xaxis().get_visible()
    assert not ax.get_yaxis().get_visible()
    assert all(not spine.get_visible() for spine in ax.spines.values())


@pytest.mark.parametrize(
    "points",
    [
        [(-34.6037, -58.3816)],
        [(-34.6037, -58.3816), (-34.6120, -58.3850)],
        [(-34.60, -58.50), (-34.61, -58.30)],
    ],
)
def test_encuadre_respeta_proporcion_de_la_figura(tmp_path, monkeypatch, points):
    captured: dict[str, object] = {}
    original_subplots = plt.subplots

    def capture(*args, **kwargs):  # noqa: ANN001
        fig, ax = original_subplots(*args, **kwargs)
        captured["ax"] = ax
        return fig, ax

    monkeypatch.setattr(plt, "subplots", capture)
    style = MapStyle(provider=None, figsize=(6.9, 9.8), dpi=50)
    output = tmp_path / "map.png"
    build_static_map_png(points, output, style=style)

    ax = captured["ax"]
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    assert abs((x1 - x0) / (y1 - y0) - 6.9 / 9.8) < 1e-6
    for lat, lon in points:
        assert x0 < lon < x1
        assert y0 < lat < y1

    from PIL import Image

    with Image.open(output) as img:
        assert img.size == (round(6.9 * 50), round(9.8 * 50))


def test_palette_colors_reduce_el_png_a_paleta(tmp_path):
    from PIL import Image

    output = tmp_path / "pal.png"
    build_static_map_png(
        [(-34.6, -58.4), (-34.61, -58.41)],
        output,
        style=MapStyle(provider=None, dpi=40, palette_colors=64),
    )
    with Image.open(output) as img:
        assert img.mode == "P"


def test_fit_bounds_to_aspect_expande_eje_corto():
    xlim, ylim = fit_bounds_to_aspect((0.0, 10.0), (0.0, 10.0), 0.5)
    assert xlim == (0.0, 10.0)
    assert ylim == (-5.0, 15.0)
    xlim, ylim = fit_bounds_to_aspect((0.0, 2.0), (0.0, 10.0), 0.5)
    assert xlim == (-1.5, 3.5)
    assert ylim == (0.0, 10.0)


def test_tiles_se_piden_con_user_agent_identificable(tmp_path, monkeypatch):
    """OSM bloquea el User-Agent genérico de contextily ("Access blocked")."""

    import sys
    import types

    from core.maps import static_map

    usado: dict[str, str] = {}
    fake_ctx = types.ModuleType("contextily")
    fake_ctx.tile = types.SimpleNamespace(USER_AGENT="contextily-generico")
    fake_ctx.providers = types.SimpleNamespace(
        OpenStreetMap=types.SimpleNamespace(Mapnik="osm-mapnik")
    )

    def _add_basemap(ax, source, crs, attribution_size):  # noqa: ANN001
        usado["ua"] = fake_ctx.tile.USER_AGENT
        usado["source"] = source

    fake_ctx.add_basemap = _add_basemap

    class _Transformer:
        @staticmethod
        def from_crs(*args, **kwargs):  # noqa: ANN002, ANN003
            return types.SimpleNamespace(transform=lambda lon, lat: (lon * 1000, lat * 1000))

    fake_pyproj = types.ModuleType("pyproj")
    fake_pyproj.Transformer = _Transformer
    monkeypatch.setitem(sys.modules, "contextily", fake_ctx)
    monkeypatch.setitem(sys.modules, "pyproj", fake_pyproj)

    monkeypatch.delenv("MAPS_TILE_USER_AGENT", raising=False)
    build_static_map_png([(-34.6, -58.4)], tmp_path / "a.png", style=MapStyle(dpi=30))
    assert usado["source"] == "osm-mapnik"
    assert usado["ua"] == static_map.DEFAULT_TILE_USER_AGENT
    assert "contextily" not in usado["ua"]

    monkeypatch.setenv("MAPS_TILE_USER_AGENT", "Otra-App/2.0")
    build_static_map_png([(-34.6, -58.4)], tmp_path / "b.png", style=MapStyle(dpi=30))
    assert usado["ua"] == "Otra-App/2.0"
