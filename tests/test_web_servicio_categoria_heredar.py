# Nombre de archivo: test_web_servicio_categoria_heredar.py
# Ubicación de archivo: tests/test_web_servicio_categoria_heredar.py
# Descripción: Pruebas del proxy web PATCH /api/servicios/{id}/categoria/heredar (admin + CSRF), sin red ni DB real

from __future__ import annotations

from typing import Optional

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


def _connect_con_rol(rol: str, password: str):
    pwd_hash = hash_password(password)
    return lambda dsn: _Conn((pwd_hash, rol))


class _Resp:
    status_code = 200

    def json(self) -> dict:
        return {"id": 1, "categoria": 5}


class _Resp409:
    status_code = 409

    def json(self) -> dict:
        return {"detail": "El servicio no tiene cliente: sin cliente para heredar"}


def _fake_async_client(capturar: list, respuesta=None):
    class _AsyncClient:
        def __init__(self, timeout: float | None = None) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def patch(self, url: str, json: Optional[dict] = None, headers: Optional[dict] = None):
            capturar.append((url, json))
            return respuesta if respuesta is not None else _Resp()

    return _AsyncClient


def _login(client: TestClient, username: str, password: str) -> str:
    return client.post("/api/auth/login", json={"username": username, "password": password}).json()["csrf"]


def test_heredar_proxya_al_endpoint_interno(monkeypatch) -> None:
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_con_rol("admin", "admin"))
    llamadas: list = []
    monkeypatch.setattr(web_main.httpx, "AsyncClient", _fake_async_client(llamadas))
    client = TestClient(app)
    csrf = _login(client, "admin", "admin")

    res = client.patch("/api/servicios/7/categoria/heredar", json={"csrf_token": csrf})

    assert res.status_code == 200
    assert res.json()["categoria"] == 5
    assert len(llamadas) == 1
    assert llamadas[0][0].endswith("/servicios/7/categoria/heredar")


def test_heredar_pasa_el_409_sin_cliente_tal_cual(monkeypatch) -> None:
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_con_rol("admin", "admin"))
    llamadas: list = []
    monkeypatch.setattr(web_main.httpx, "AsyncClient", _fake_async_client(llamadas, _Resp409()))
    client = TestClient(app)
    csrf = _login(client, "admin", "admin")

    res = client.patch("/api/servicios/7/categoria/heredar", json={"csrf_token": csrf})

    assert res.status_code == 409
    assert "sin cliente para heredar" in res.json()["detail"]


def test_heredar_rechaza_csrf_invalido(monkeypatch) -> None:
    from web.app import main as web_main

    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_con_rol("admin", "admin"))
    llamadas: list = []
    monkeypatch.setattr(web_main.httpx, "AsyncClient", _fake_async_client(llamadas))
    client = TestClient(app)
    _login(client, "admin", "admin")

    res = client.patch("/api/servicios/7/categoria/heredar", json={"csrf_token": "invalido"})

    assert res.status_code == 403
    assert llamadas == []


def test_heredar_requiere_admin(monkeypatch) -> None:
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_con_rol("user", "userpass"))
    client = TestClient(app)
    csrf = _login(client, "user", "userpass")

    res = client.patch("/api/servicios/7/categoria/heredar", json={"csrf_token": csrf})

    assert res.status_code == 403
