# Nombre de archivo: __init__.py
# Ubicación de archivo: api_app/__init__.py
# Descripción: Paquete shim que reexporta api.api_app para compatibilidad con imports legacy en tests

from importlib import import_module as _import_module
import sys as _sys

# Reexportar el paquete real para permitir from api_app.routes import ...
_real_pkg = _import_module("api.api_app")
_sys.modules.setdefault("api_app", _real_pkg)

# Asegurar reexportación de subpaquete routes
_routes_pkg = _import_module("api.api_app.routes")
_sys.modules["api_app.routes"] = _routes_pkg

# Publicar submódulos comunes
for _name in ["health", "reports", "ingest"]:
	try:
		_sub = _import_module(f"api.api_app.routes.{_name}")
		_sys.modules[f"api_app.routes.{_name}"] = _sub
	except Exception:
		pass

__all__ = ["routes"]
