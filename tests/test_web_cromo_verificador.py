# Nombre de archivo: test_web_cromo_verificador.py
# Ubicación de archivo: tests/test_web_cromo_verificador.py
# Descripción: Pruebas de los endpoints del verificador de servicios Cromo (auth, 404, resultados), sin red ni DB real

from __future__ import annotations

from typing import Any, Optional

from fastapi.testclient import TestClient  # type: ignore

from core.password import hash_password
from web.app.main import app


class _Cur:
    def __init__(self, row: Optional[tuple] = None) -> None:
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None) -> None:
        return None

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row: tuple) -> None:
        self.cur = _Cur(row)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cur

    def commit(self) -> None:
        return None


def _connect_user_ok(password: str = "userpass"):
    pwd_hash = hash_password(password)

    def _connect(dsn: str):
        return _Conn((pwd_hash, "user"))

    return _connect


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["csrf"]


class _ResultadoFilas:
    def __init__(self, filas: list[tuple]) -> None:
        self._filas = filas

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFake:
    """Matchea por substring de la consulta compilada, igual que en test_cromo_verificador.py."""

    def __init__(self, respuestas: Optional[dict[str, list[tuple]]] = None) -> None:
        self._respuestas = respuestas or {}

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFilas:
        texto = str(stmt)
        for clave, filas in self._respuestas.items():
            if clave in texto:
                return _ResultadoFilas(filas)
        return _ResultadoFilas([])


def _fake_async_session_local(sesion: _SesionFake):
    class _CM:
        async def __aenter__(self):
            return sesion

        async def __aexit__(self, *a):
            return False

    def factory():
        return _CM()

    return factory


_FILA_SERVICIO = (
    501,
    "SRV-001",
    "SRV-001",
    "Cliente Uno",
    "Cliente Uno SA",
    "ACTIVO",
    1,
    "CORPORATIVO",
    9001,
    "1234",
    "REGEX_EXACTO",
)


# ── GET /api/infra/cromo/cables/{n_id}/servicios ─────────────────────────────


def test_por_cable_requiere_autenticacion():
    client = TestClient(app)
    res = client.get("/api/infra/cromo/cables/51/servicios")
    assert res.status_code == 401


def test_por_cable_no_requiere_admin(monkeypatch):
    """A diferencia de la ingesta, el verificador es de sólo lectura: alcanza con estar autenticado."""
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake(respuestas={"FROM app.cromo_cables": [(51, "Cable Troncal", "72-BRUG", "A", "B")]})
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/51/servicios")
    assert res.status_code == 200
    assert res.json()["cable_n_id"] == 51


def test_por_cable_404_si_no_existe(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_SesionFake()))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/999/servicios")
    assert res.status_code == 404


def test_por_cable_happy_path_con_servicios(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_cables": [(51, "Cable Troncal", "72-BRUG", "Botella A", "Botella B")],
            "cromo_pelos p\n    JOIN app.cromo_servicio_match": [_FILA_SERVICIO],
        }
    )
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables/51/servicios")
    assert res.status_code == 200
    payload = res.json()
    assert payload["nombre"] == "Cable Troncal"
    assert len(payload["servicios"]) == 1
    assert payload["servicios"][0]["servicio_id_externo"] == "SRV-001"


# ── GET /api/infra/cromo/tubos/{n_id}/servicios ──────────────────────────────


def test_por_tubo_404_si_no_existe(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_SesionFake()))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/tubos/999/servicios")
    assert res.status_code == 404


def test_por_tubo_happy_path(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_tubos": [(129001, 51, 3, "AZUL")],
            "cromo_pelos p\n    JOIN app.cromo_servicio_match": [_FILA_SERVICIO],
        }
    )
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/tubos/129001/servicios")
    assert res.status_code == 200
    payload = res.json()
    assert payload["cable_n_id"] == 51
    assert len(payload["servicios"]) == 1


# ── GET /api/infra/cromo/botellas/{n_id}/servicios ───────────────────────────


def test_por_botella_404_si_no_existe(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_SesionFake()))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/botellas/999/servicios")
    assert res.status_code == 404


def test_por_botella_happy_path(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_botellas": [(68001, "ODF Central", 69, "CABA")],
            "FROM app.cromo_cables c": [_FILA_SERVICIO],
        }
    )
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/botellas/68001/servicios")
    assert res.status_code == 200
    payload = res.json()
    assert payload["clase"] == 69
    assert len(payload["servicios"]) == 1
