# Nombre de archivo: test_web_imports_layout_contenedor.py
# Ubicación de archivo: tests/test_web_imports_layout_contenedor.py
# Descripción: Los módulos sueltos de web/ no pueden importar `web.app` sin fallback (en la imagen es `app`)

from __future__ import annotations

import ast
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def _imports_web_app_sin_fallback(ruta: Path) -> list[int]:
    """Líneas con `from web.app...`/`import web.app...` fuera de un `try` que atrape ModuleNotFoundError."""
    arbol = ast.parse(ruta.read_text())
    protegidas: set[int] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Try) and any(
            isinstance(h.type, ast.Name) and h.type.id in {"ModuleNotFoundError", "ImportError"} for h in nodo.handlers
        ):
            protegidas.update(n.lineno for sub in nodo.body for n in ast.walk(sub) if hasattr(n, "lineno"))
    malas = []
    for nodo in ast.walk(arbol):
        modulo = None
        if isinstance(nodo, ast.ImportFrom) and nodo.module:
            modulo = nodo.module
        elif isinstance(nodo, ast.Import):
            modulo = next((a.name for a in nodo.names if a.name.startswith("web.app")), None)
        if modulo and (modulo == "web.app" or modulo.startswith("web.app.")) and nodo.lineno not in protegidas:
            malas.append(nodo.lineno)
    return malas


def test_modulos_sueltos_de_web_no_importan_web_app_sin_fallback():
    # web/Dockerfile copia web/app como /app/app y los módulos sueltos (fo_monitor_routes, chat_ws,
    # admin_ws) como /app/web/*.py: dentro del contenedor `web.app` no existe.
    hallazgos = {
        str(ruta.relative_to(WEB.parent)): lineas
        for ruta in sorted(WEB.glob("*.py"))
        if (lineas := _imports_web_app_sin_fallback(ruta))
    }
    assert not hallazgos, f"importan web.app sin fallback a `app`: {hallazgos}"


def test_paquete_web_app_no_se_importa_a_si_mismo_como_web_app():
    # Dentro de web/app vale lo mismo: en la imagen el paquete se llama `app`, así que un
    # `from web.app.x import ...` tira ModuleNotFoundError al arrancar uvicorn aunque la suite pase.
    # Real (2026-10-28, P12): main.py y http_interno.py lo hacían y el web de dev no arrancó.
    hallazgos = {
        str(ruta.relative_to(WEB.parent)): lineas
        for ruta in sorted((WEB / "app").rglob("*.py"))
        if (lineas := _imports_web_app_sin_fallback(ruta))
    }
    assert not hallazgos, f"web/app importa web.app (usar import relativo): {hallazgos}"
