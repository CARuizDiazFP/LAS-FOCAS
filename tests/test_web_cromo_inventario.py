# Nombre de archivo: test_web_cromo_inventario.py
# Ubicación de archivo: tests/test_web_cromo_inventario.py
# Descripción: Pruebas del endpoint de inventario de cables Cromo (auth, búsqueda, paginación), sin red ni DB real

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


class _ResultadoFake:
    def __init__(self, escalar: Any = None, filas: Optional[list[tuple]] = None) -> None:
        self._escalar = escalar
        self._filas = filas or []

    def scalar_one(self):
        return self._escalar

    def all(self):
        return self._filas


class _SesionFake:
    def __init__(self, total: int = 0, filas: Optional[list[tuple]] = None) -> None:
        self._total = total
        self._filas = filas or []

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFake:
        if "SELECT count(*)" in str(stmt):
            return _ResultadoFake(escalar=self._total)
        return _ResultadoFake(filas=self._filas)


def _fake_async_session_local(sesion: _SesionFake):
    class _CM:
        async def __aenter__(self):
            return sesion

        async def __aexit__(self, *a):
            return False

    def factory():
        return _CM()

    return factory


_FILA_CABLE = (
    51, "Cable Troncal 1", "72-BRUG", 72, "Troncal", "SBASE", "Botella A", "Botella B", True, 3,
)


def test_inventario_cables_requiere_autenticacion():
    client = TestClient(app)
    res = client.get("/api/infra/cromo/cables")
    assert res.status_code == 401


def test_inventario_cables_no_requiere_admin(monkeypatch):
    """Consulta de sólo lectura, mismo criterio que el verificador — alcanza con estar autenticado."""
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake(total=1, filas=[_FILA_CABLE])
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert len(body["cables"]) == 1
    assert body["cables"][0]["nombre"] == "Cable Troncal 1"
    assert body["cables"][0]["cantidad_servicios"] == 3


def test_inventario_cables_sin_resultados(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_SesionFake(total=0, filas=[])))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables?q=no-existe")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["cables"] == []


def test_inventario_cables_limit_acotado_a_200(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake(total=0, filas=[])
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/cables?limit=9999")
    assert res.status_code == 200
    assert res.json()["limit"] == 200


def test_inventario_cables_query_params_pasan_a_buscar_cables(monkeypatch):
    from web.app import main as web_main
    from core.services.cromo import inventario as cromo_inventario

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_SesionFake()))

    llamada = {}

    async def _buscar_cables_fake(sesion, **kwargs):
        llamada.update(kwargs)
        return cromo_inventario.ResultadoBusquedaCables(total=0, limit=kwargs["limit"], offset=kwargs["offset"], cables=[])

    monkeypatch.setattr(cromo_inventario, "buscar_cables", _buscar_cables_fake)

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get(
        "/api/infra/cromo/cables"
        "?q=troncal&jerarquia=Troncal&propietario=SBASE&vigente=true"
        "&n_id=51&botella=Botella&servicio=1234&limit=10&offset=5"
    )

    assert res.status_code == 200
    assert llamada == {
        "q": "troncal", "jerarquia": "Troncal", "propietario": "SBASE", "vigente": True,
        "n_id": 51, "botella": "Botella", "servicio": "1234", "limit": 10, "offset": 5,
    }
