# Nombre de archivo: test_web_admin.py
# Ubicación de archivo: tests/test_web_admin.py
# Descripción: Pruebas de endpoints admin y cambio de contraseña

from pathlib import Path
import sys
import re
from typing import Any, Optional

sys.path.append(str(Path(__file__).resolve().parents[1] / "web"))

from fastapi.testclient import TestClient  # type: ignore
from core.password import hash_password
from web_app.main import app  # type: ignore


class _Cur:
    def __init__(self, row: Optional[tuple[Any, ...]] = None):
        self._row = row
        self.last_sql = ""
        self.calls = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: tuple[Any, ...] | None = None):
        self.last_sql = sql
        self.calls.append((sql, params))
        if "UPDATE app.config_servicios" in sql or "INSERT INTO app.config_servicios" in sql:
            self.rowcount = 1
        else:
            self.rowcount = 0

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
    pwd_hash = hash_password(password)

    def _connect(dsn: str):  # type: ignore
        # Devuelve fila de admin al consultar web_users
        return _Conn({"default": (pwd_hash, "admin")})

    return _connect


def _connect_user_ok(password: str = "userpass"):
    pwd_hash = hash_password(password)

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


def test_servicios_baneos_update_recarga_worker(monkeypatch):
    from web_app import main as web_main

    recargas = []

    class _Resp:
        def raise_for_status(self):
            return None

    class _AsyncClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str):
            recargas.append(url)
            return _Resp()

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok("admin"))
    monkeypatch.setattr(web_main.httpx, "AsyncClient", _AsyncClient)

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "password": "admin"})
    csrf = re.search(r"window.CSRF_TOKEN = \"([\w-]+)\";", client.get("/").text).group(1)

    res = client.post(
        "/api/admin/servicios/baneos",
        data={
            "intervalo_horas": "24",
            "slack_channels": "C08UB8ML3LP,#baneo-de-camaras-prueba",
            "activo": "on",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["location"] == "/admin/Servicios/Baneos"
    assert recargas == [web_main._SLACK_WORKER_RELOAD_URL]


def test_servicios_baneos_update_rechaza_destino_invalido(monkeypatch):
    from web_app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok("admin"))
    client = TestClient(app)
    client.post("/login", data={"username": "admin", "password": "admin"})
    csrf = re.search(r"window.CSRF_TOKEN = \"([\w-]+)\";", client.get("/").text).group(1)

    res = client.post(
        "/api/admin/servicios/baneos",
        data={
            "intervalo_horas": "24",
            "slack_channels": "canal con espacios",
            "activo": "on",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    assert res.status_code == 400
    assert "ID de Slack" in res.json()["error"]


# ── Nuevas rutas SPA admin ──────────────────────────────────────────────────

def test_admin_me_ok(monkeypatch):
    """GET /api/admin/me con sesión admin devuelve 200 con username y role."""
    from web_app import main as web_main
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok("admin"))
    client = TestClient(app)
    client.post("/login", data={"username": "admin", "password": "admin"})
    res = client.get("/api/admin/me")
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "admin"
    assert data["role"] == "admin"


def test_admin_me_sin_sesion():
    """GET /api/admin/me sin sesión devuelve 401."""
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/admin/me")
    assert res.status_code in (401, 403)


def test_admin_me_no_admin(monkeypatch):
    """GET /api/admin/me con sesión no-admin devuelve 403."""
    from web_app import main as web_main
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok("userpass"))
    client = TestClient(app)
    client.post("/login", data={"username": "user", "password": "userpass"})
    res = client.get("/api/admin/me")
    assert res.status_code == 403


def test_admin_usuarios_accesible_admin(monkeypatch):
    """GET /admin/usuarios con sesión admin devuelve 200 con el shell SPA."""
    from web_app import main as web_main
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok("admin"))
    client = TestClient(app)
    client.post("/login", data={"username": "admin", "password": "admin"})
    res = client.get("/admin/usuarios")
    assert res.status_code == 200
    assert "admin-app" in res.text


def test_admin_usuarios_redirige_sin_sesion():
    """GET /admin/usuarios sin sesión redirige a /login."""
    client = TestClient(app, follow_redirects=False)
    res = client.get("/admin/usuarios")
    assert res.status_code == 302
    assert "/login" in res.headers["location"]


def test_admin_servicios_accesible_admin(monkeypatch):
    """GET /admin/servicios con sesión admin devuelve 200 con el shell SPA."""
    from web_app import main as web_main
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok("admin"))
    client = TestClient(app)
    client.post("/login", data={"username": "admin", "password": "admin"})
    res = client.get("/admin/servicios")
    assert res.status_code == 200
    assert "admin-app" in res.text


def test_admin_servicios_redirige_sin_sesion():
    """GET /admin/servicios sin sesión redirige a /login."""
    client = TestClient(app, follow_redirects=False)
    res = client.get("/admin/servicios")
    assert res.status_code == 302
    assert "/login" in res.headers["location"]


def test_admin_baneos_config_json(monkeypatch):
    """GET /api/admin/servicios/baneos/config con sesión admin devuelve JSON de configuración."""
    from web_app import main as web_main
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok("admin"))
    client = TestClient(app)
    client.post("/login", data={"username": "admin", "password": "admin"})
    res = client.get("/api/admin/servicios/baneos/config")
    assert res.status_code == 200
    data = res.json()
    assert "intervalo_horas" in data
    assert "slack_channels" in data
    assert "activo" in data


def test_admin_baneos_config_json_sin_sesion():
    """GET /api/admin/servicios/baneos/config sin sesión devuelve 401."""
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/admin/servicios/baneos/config")
    assert res.status_code in (401, 403)

