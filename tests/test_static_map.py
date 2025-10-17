# Nombre de archivo: test_static_map.py
# Ubicación de archivo: tests/test_static_map.py
# Descripción: Pruebas para la generación de mapas estáticos con estilo tipo Google

import pytest

pytest.importorskip("matplotlib")

from matplotlib import pyplot as plt  # noqa: E402

from core.maps.static_map import MapStyle, build_static_map_png


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
