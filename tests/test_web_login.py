# Nombre de archivo: test_web_login.py
# Ubicación de archivo: tests/test_web_login.py
# Descripción: Pruebas de login (éxito, falla, redirect) y sesión/CSRF

from pathlib import Path
import sys
from typing import Any, Optional


from fastapi.testclient import TestClient  # type: ignore
from core.password import hash_password
from web.app.main import app  # type: ignore


class _Cur:
    def __init__(self, user_row: Optional[tuple[str, str]]):
        self._user_row = user_row
        self._last_sql = ""
        self._last_params: tuple[Any, ...] = ()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: tuple[Any, ...] | None = None):
        self._last_sql = sql
        self._last_params = params or ()

    def fetchone(self):
        return self._user_row


class _Conn:
    def __init__(self, user_row: Optional[tuple[str, str]]):
        self._user_row = user_row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _Cur(self._user_row)

    def commit(self):
        pass


def _mock_connect_ok(username: str, password: str, role: str = "admin"):
    pwd_hash = hash_password(password)

    def _connect(dsn: str):  # type: ignore
        # Devuelve fila si username coincide
        return _Conn((pwd_hash, role))

    return _connect


def _mock_connect_fail():
    def _connect(dsn: str):  # type: ignore
        return _Conn(None)

    return _connect


def test_login_success_and_csrf_injected(monkeypatch):
    from web.app import main as web_main

    # Mock DB para devolver usuario admin con contraseña "admin"
    monkeypatch.setattr(web_main.psycopg, "connect", _mock_connect_ok("admin", "admin", role="admin"))

    client = TestClient(app)
    res = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True

    csrf = data["csrf"]
    assert len(csrf) >= 16


def test_login_invalid_credentials(monkeypatch):
    from web.app import main as web_main
    # Mock DB sin usuario
    monkeypatch.setattr(web_main.psycopg, "connect", _mock_connect_fail())
    client = TestClient(app)
    res = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert res.status_code == 401


def test_session_endpoint_devuelve_rol_autenticado(monkeypatch):
    """GET /api/auth/session es la fuente de rol/csrf que usa el SPA (reemplaza window.USER_ROLE)."""
    from web.app import main as web_main
    monkeypatch.setattr(web_main.psycopg, "connect", _mock_connect_ok("admin", "admin", role="admin"))
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    res = client.get("/api/auth/session")
    assert res.status_code == 200
    data = res.json()
    assert data["authenticated"] is True
    assert data["username"] == "admin"
    assert data["role"] == "admin"
    assert data["csrf"]


def test_session_endpoint_sin_sesion():
    client = TestClient(app)
    res = client.get("/api/auth/session")
    assert res.status_code == 200
    data = res.json()
    assert data["authenticated"] is False
    assert data["role"] is None
