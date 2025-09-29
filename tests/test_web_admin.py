# Nombre de archivo: test_web_admin.py
# Ubicación de archivo: tests/test_web_admin.py
# Descripción: Pruebas de endpoints admin y cambio de contraseña

from pathlib import Path
import sys
import re
from typing import Any, Optional

sys.path.append(str(Path(__file__).resolve().parents[1] / "web"))

from fastapi.testclient import TestClient  # type: ignore
from passlib.hash import bcrypt  # type: ignore
from web_app.main import app  # type: ignore


class _Cur:
    def __init__(self, row: Optional[tuple[Any, ...]] = None):
        self._row = row
        self.last_sql = ""
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: tuple[Any, ...] | None = None):
        self.last_sql = sql
        self.calls.append((sql, params))

    def fetchone(self):
        # Si es la consulta de existencia de usuario nuevo → simular que no existe
        if "SELECT 1 FROM app.web_users WHERE username" in self.last_sql:
            return None
        # Si es la consulta de login → devolver fila con (password_hash, role)
        if "SELECT password_hash, role FROM app.web_users" in self.last_sql:
            return self._row
        return self._row


class _Conn:
    def __init__(self, rows: dict[str, tuple[Any, ...]]):
        self._rows = rows
        self.cur = _Cur(self._rows.get("default"))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cur

    def commit(self):
        pass


def _connect_admin_ok(password: str = "admin"):
    pwd_hash = bcrypt.hash(password)

    def _connect(dsn: str):  # type: ignore
        # Devuelve fila de admin al consultar web_users
        return _Conn({"default": (pwd_hash, "admin")})

    return _connect


def _connect_user_ok(password: str = "userpass"):
    pwd_hash = bcrypt.hash(password)

    def _connect(dsn: str):  # type: ignore
        return _Conn({"default": (pwd_hash, "user")})

    return _connect


def test_admin_create_user(monkeypatch):
    from web_app import main as web_main
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok("admin"))
    client = TestClient(app)
    # Login admin
    client.post("/login", data={"username": "admin", "password": "admin"})
    # Obtener CSRF
    html = client.get("/").text
    csrf = re.search(r"window.CSRF_TOKEN = \"([\w-]+)\";", html).group(1)
    # Crear usuario
    res = client.post("/api/admin/users", data={"username": "nuevo", "password": "x", "role": "ownergroup", "csrf_token": csrf})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_admin_create_user_forbidden_for_non_admin(monkeypatch):
    from web_app import main as web_main
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok("userpass"))
    client = TestClient(app)
    # Login user normal
    client.post("/login", data={"username": "user", "password": "userpass"})
    html = client.get("/").text
    csrf = re.search(r"window.CSRF_TOKEN = \"([\w-]+)\";", html).group(1)
    res = client.post("/api/admin/users", data={"username": "nuevo", "password": "x", "csrf_token": csrf})
    assert res.status_code == 403


def test_change_password_happy_path(monkeypatch):
    from web_app import main as web_main
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok("oldpass"))
    client = TestClient(app)
    # Login con oldpass
    client.post("/login", data={"username": "user", "password": "oldpass"})
    html = client.get("/").text
    csrf = re.search(r"window.CSRF_TOKEN = \"([\w-]+)\";", html).group(1)
    res = client.post(
        "/api/users/change-password",
        data={"current_password": "oldpass", "new_password": "newpass", "csrf_token": csrf},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_admin_create_user_invalid_role(monkeypatch):
    from web_app import main as web_main
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok("admin"))
    client = TestClient(app)
    client.post("/login", data={"username": "admin", "password": "admin"})
    csrf = re.search(r"window.CSRF_TOKEN = \"([\w-]+)\";", client.get("/").text).group(1)
    res = client.post("/api/admin/users", data={"username": "bad", "password": "x", "role": "nope", "csrf_token": csrf})
    assert res.status_code == 400


def test_admin_create_user_guest_role(monkeypatch):
    from web_app import main as web_main
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok("admin"))
    client = TestClient(app)
    client.post("/login", data={"username": "admin", "password": "admin"})
    csrf = re.search(r"window.CSRF_TOKEN = \"([\w-]+)\";", client.get("/").text).group(1)
    res = client.post("/api/admin/users", data={"username": "guest", "password": "x", "role": "Invitado", "csrf_token": csrf})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
