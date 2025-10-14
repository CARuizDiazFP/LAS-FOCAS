# Nombre de archivo: __init__.py
# Ubicación de archivo: api_app/routes/__init__.py
# Descripción: Paquete shim de rutas que reexporta api.api_app.routes para compatibilidad con tests

from importlib import import_module as _import_module
import sys as _sys

_real_pkg = _import_module("api.api_app.routes")

# Asegurar que los submódulos reales queden accesibles vía este paquete
for _name in getattr(_real_pkg, "__all__", ["health", "reports", "ingest"]):
    try:
        _sub = _import_module(f"api.api_app.routes.{_name}")
        _sys.modules[f"api_app.routes.{_name}"] = _sub
    except Exception:
        pass

__all__ = ["health", "reports", "ingest"]
