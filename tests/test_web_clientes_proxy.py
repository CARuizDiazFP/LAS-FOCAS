# Nombre de archivo: test_web_clientes_proxy.py
# Ubicación de archivo: tests/test_web_clientes_proxy.py
# Descripción: Pruebas del proxy web /api/admin/clientes/* (admin + CSRF + X-Usuario), sin red ni DB real

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient  # type: ignore

from core.password import hash_password
from web.app.main import app


class _Cur:
    def __init__(self, row: tuple) -> None:
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql: str, params=None) -> None:
        return None

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row: tuple) -> None:
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _Cur(self._row)

    def commit(self) -> None:
        return None


class _Resp:
    status_code = 200

    def json(self) -> dict:
        return {"ok": True}


def _fake_async_client(llamadas: list[dict[str, Any]]):
    class _AsyncClient:
        def __init__(self, timeout: float | None = None) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method: str, url: str, **kwargs):
            llamadas.append({"method": method, "url": url, **kwargs})
            return _Resp()

    return _AsyncClient


def _cliente_logueado(monkeypatch, rol: str) -> tuple[TestClient, str, list[dict[str, Any]]]:
    from web.app import main as web_main

    pwd_hash = hash_password("clave")
    monkeypatch.setattr(web_main.psycopg, "connect", lambda dsn: _Conn((pwd_hash, rol)))
    llamadas: list[dict[str, Any]] = []
    monkeypatch.setattr(web_main.httpx, "AsyncClient", _fake_async_client(llamadas))
    client = TestClient(app)
    csrf = client.post("/api/auth/login", json={"username": "ana", "password": "clave"}).json()["csrf"]
    return client, csrf, llamadas


def _pedidos_json(csrf: str) -> list[tuple[str, str, dict, str, str, dict]]:
    """(método web, ruta web, body, método interno, ruta interna, json esperado)."""
    return [
        (
            "PATCH",
            "/api/admin/clientes/categoria",
            {"cliente_ids": [1, 2], "categoria": None, "csrf_token": csrf},
            "PATCH",
            "/clientes/categoria",
            {"cliente_ids": [1, 2], "categoria": None, "automatico": False},
        ),
        (
            "POST",
            "/api/admin/clientes/lista/previsualizar",
            {"nombres": ["BANCO UNO"], "categoria": 6, "modo": "reemplazar", "csrf_token": csrf},
            "POST",
            "/clientes/lista/previsualizar",
            {"nombres": ["BANCO UNO"], "categoria": 6, "modo": "reemplazar"},
        ),
        (
            "POST",
            "/api/admin/clientes/lista/aplicar",
            {"nombres": ["BANCO UNO"], "categoria": 6, "csrf_token": csrf},
            "POST",
            "/clientes/lista/aplicar",
            {"nombres": ["BANCO UNO"], "categoria": 6, "modo": "agregar"},
        ),
        (
            "POST",
            "/api/admin/clientes/fusionar",
            {"destino_id": 1, "origen_ids": [2, 3], "csrf_token": csrf},
            "POST",
            "/clientes/fusionar",
            {"destino_id": 1, "origen_ids": [2, 3]},
        ),
        (
            "POST",
            "/api/admin/clientes/5/alias",
            {"nombre": "Banco Uno SA", "csrf_token": csrf},
            "POST",
            "/clientes/5/alias",
            {"nombre": "Banco Uno SA"},
        ),
        ("DELETE", "/api/admin/clientes/alias/9", {"csrf_token": csrf}, "DELETE", "/clientes/alias/9", None),
        ("POST", "/api/admin/clientes/sincronizar", {"csrf_token": csrf}, "POST", "/clientes/sincronizar", None),
    ]


def test_listado_requiere_admin_y_no_csrf(monkeypatch) -> None:
    client, _, llamadas = _cliente_logueado(monkeypatch, "admin")

    res = client.get("/api/admin/clientes/por-categoria")

    assert res.status_code == 200
    assert llamadas[0]["method"] == "GET"
    assert llamadas[0]["url"].endswith("/clientes/por-categoria")


def test_proxy_json_reenvia_payload_y_usuario(monkeypatch) -> None:
    client, csrf, llamadas = _cliente_logueado(monkeypatch, "admin")

    for metodo, ruta, body, metodo_int, ruta_int, json_esperado in _pedidos_json(csrf):
        llamadas.clear()
        res = client.request(metodo, ruta, json=body)

        assert res.status_code == 200, (ruta, res.text)
        assert len(llamadas) == 1, ruta
        assert llamadas[0]["method"] == metodo_int
        assert llamadas[0]["url"].endswith(ruta_int)
        assert llamadas[0].get("json") == json_esperado, ruta
        assert llamadas[0]["headers"]["X-Usuario"] == "ana"
        assert llamadas[0]["headers"]["Authorization"].startswith("Bearer ")


def test_proxy_json_rechaza_csrf_invalido(monkeypatch) -> None:
    monkeypatch.delenv("TESTING", raising=False)
    client, _, llamadas = _cliente_logueado(monkeypatch, "admin")

    for metodo, ruta, body, *_ in _pedidos_json("invalido"):
        res = client.request(metodo, ruta, json=body)
        assert res.status_code == 403, ruta
    assert llamadas == []


def test_todo_requiere_admin(monkeypatch) -> None:
    client, csrf, llamadas = _cliente_logueado(monkeypatch, "user")

    assert client.get("/api/admin/clientes/por-categoria").status_code == 403
    for metodo, ruta, body, *_ in _pedidos_json(csrf):
        assert client.request(metodo, ruta, json=body).status_code == 403, ruta
    res = client.post(
        "/api/admin/clientes/lista/aplicar",
        files={"file": ("lista.txt", b"BANCO UNO\n", "text/plain")},
        data={"categoria": "6", "csrf_token": csrf},
    )
    assert res.status_code == 403
    assert llamadas == []


def test_sin_sesion_devuelve_401(monkeypatch) -> None:
    client = TestClient(app)
    assert client.get("/api/admin/clientes/por-categoria").status_code == 401


@pytest.mark.parametrize("ruta", ["/api/admin/clientes/lista/previsualizar", "/api/admin/clientes/lista/aplicar"])
def test_upload_reenvia_archivo_y_campos(monkeypatch, ruta: str) -> None:
    client, csrf, llamadas = _cliente_logueado(monkeypatch, "admin")

    res = client.post(
        ruta,
        files={"file": ("lista.csv", b"Cliente\nBANCO UNO\n", "text/csv")},
        data={"categoria": "sin", "modo": "reemplazar", "csrf_token": csrf},
    )

    assert res.status_code == 200, res.text
    llamada = llamadas[0]
    assert llamada["method"] == "POST"
    assert llamada["url"].endswith(ruta.replace("/api/admin", ""))
    assert llamada["files"]["file"][:2] == ("lista.csv", b"Cliente\nBANCO UNO\n")
    assert llamada["data"] == {"categoria": "sin", "modo": "reemplazar"}
    assert llamada["headers"]["X-Usuario"] == "ana"


def test_upload_rechaza_csrf_invalido(monkeypatch) -> None:
    monkeypatch.delenv("TESTING", raising=False)
    client, _, llamadas = _cliente_logueado(monkeypatch, "admin")

    res = client.post(
        "/api/admin/clientes/lista/previsualizar",
        files={"file": ("lista.txt", b"BANCO UNO\n", "text/plain")},
        data={"categoria": "6", "csrf_token": "invalido"},
    )

    assert res.status_code == 403
    assert llamadas == []


def test_upload_valida_extension_y_tamano_antes_de_reenviar(monkeypatch) -> None:
    client, csrf, llamadas = _cliente_logueado(monkeypatch, "admin")

    pdf = client.post(
        "/api/admin/clientes/lista/previsualizar",
        files={"file": ("lista.pdf", b"%PDF", "application/pdf")},
        data={"categoria": "6", "csrf_token": csrf},
    )
    grande = client.post(
        "/api/admin/clientes/lista/previsualizar",
        files={"file": ("lista.txt", b"x" * (5 * 1024 * 1024 + 1), "text/plain")},
        data={"categoria": "6", "csrf_token": csrf},
    )

    assert pdf.status_code == 415
    assert grande.status_code == 413
    assert llamadas == []
