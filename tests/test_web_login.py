# Nombre de archivo: test_web_login.py
# Ubicación de archivo: tests/test_web_login.py
# Descripción: Pruebas de login (éxito, falla, redirect) y sesión/CSRF

from pathlib import Path
import sys
import re
from typing import Any, Optional

sys.path.append(str(Path(__file__).resolve().parents[1] / "web"))

from fastapi.testclient import TestClient  # type: ignore
from passlib.hash import bcrypt  # type: ignore
from app.main import app  # type: ignore


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
    pwd_hash = bcrypt.hash(password)

    def _connect(dsn: str):  # type: ignore
        # Devuelve fila si username coincide
        return _Conn((pwd_hash, role))

    return _connect


def _mock_connect_fail():
    def _connect(dsn: str):  # type: ignore
        return _Conn(None)

    return _connect


def test_login_success_and_csrf_injected(monkeypatch):
    from app import main as web_main

    # Mock DB para devolver usuario admin con contraseña "admin"
    monkeypatch.setattr(web_main.psycopg, "connect", _mock_connect_ok("admin", "admin", role="admin"))

    client = TestClient(app)
    res = client.post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"].endswith("/")

    # Accedemos al panel para obtener el CSRF inyectado en la plantilla
    res2 = client.get("/")
    assert res2.status_code == 200
    html = res2.text
    m = re.search(r"window.CSRF_TOKEN = \"([\w-]+)\";", html)
    assert m, "No se encontró CSRF en la plantilla"
    csrf = m.group(1)
    assert len(csrf) >= 16


def test_login_invalid_credentials(monkeypatch):
    from app import main as web_main
    # Mock DB sin usuario
    monkeypatch.setattr(web_main.psycopg, "connect", _mock_connect_fail())
    client = TestClient(app)
    res = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert res.status_code in (400, 500)


def test_login_redirect_when_already_logged(monkeypatch):
    from app import main as web_main
    monkeypatch.setattr(web_main.psycopg, "connect", _mock_connect_ok("admin", "admin", role="user"))
    client = TestClient(app)
    # Primer login
    client.post("/login", data={"username": "admin", "password": "admin"})
    # Acceso a /login debe redirigir al panel
    res = client.get("/login", follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"].endswith("/")
