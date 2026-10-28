# Nombre de archivo: test_web_http_interno.py
# Ubicación de archivo: tests/test_web_http_interno.py
# Descripción: El cliente httpx compartido de los proxies al API interno es único y se cierra al apagar la app

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from web.app import http_interno
from web.app.main import app


def test_proxies_reusan_el_mismo_cliente_y_se_cierra_al_apagar(monkeypatch, con_sesion) -> None:
    usados: list[httpx.AsyncClient] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [], "total": 0})

    with TestClient(app) as client:
        assert http_interno._cliente is not None  # abierto por el lifespan
        inyectado = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        monkeypatch.setattr(http_interno, "_cliente", inyectado)

        original = http_interno.cliente_api_interna

        def _espia() -> httpx.AsyncClient:
            c = original()
            usados.append(c)
            return c

        monkeypatch.setattr("web.app.routers.servicios.cliente_api_interna", _espia)
        con_sesion("user")
        assert client.get("/api/servicios/search?q=a").status_code == 200
        assert client.get("/api/servicios/search?q=b").status_code == 200
        assert len(usados) == 2 and usados[0] is usados[1] is inyectado

    # Al salir del lifespan el cliente vigente queda cerrado y la referencia liberada.
    assert inyectado.is_closed
    assert http_interno._cliente is None


def test_lifespan_conserva_los_handlers_on_event() -> None:
    """Con `lifespan=` Starlette ignora `@app.on_event`: el lifespan debe invocarlos igual."""
    with TestClient(app):
        assert getattr(app.state, "admin_ws_subscriber_task", None) is not None
