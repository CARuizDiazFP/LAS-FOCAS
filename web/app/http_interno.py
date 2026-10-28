# Nombre de archivo: http_interno.py
# Ubicación de archivo: web/app/http_interno.py
# Descripción: Cliente httpx compartido (un pool por proceso) para los proxies del panel web al API interno

from __future__ import annotations

import httpx

from web.app.comun import INTERNAL_API_BASE_URL

# Cliente único del proceso. Se abre en el lifespan de la app; si no hay lifespan activo (por ejemplo
# `TestClient(app)` sin context manager) se crea de forma perezosa en el primer uso.
# El timeout NO se fija acá: cada pedido lo pasa por su cuenta (`timeout=...`).
_cliente: httpx.AsyncClient | None = None


def _nuevo_cliente() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=INTERNAL_API_BASE_URL)


def cliente_api_interna() -> httpx.AsyncClient:
    """Devuelve el cliente compartido; si no existe o fue cerrado, crea uno nuevo y lo reusa."""
    global _cliente
    if _cliente is None or _cliente.is_closed:
        _cliente = _nuevo_cliente()
    return _cliente


async def abrir_cliente_api_interna() -> None:
    """Crea el cliente compartido al iniciar la app (idempotente)."""
    cliente_api_interna()


async def cerrar_cliente_api_interna() -> None:
    """Cierra el cliente compartido al apagar la app y libera la referencia."""
    global _cliente
    cliente, _cliente = _cliente, None
    if cliente is not None and not cliente.is_closed:
        await cliente.aclose()
