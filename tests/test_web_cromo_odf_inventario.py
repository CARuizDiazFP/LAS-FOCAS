# Nombre de archivo: test_web_cromo_odf_inventario.py
# Ubicación de archivo: tests/test_web_cromo_odf_inventario.py
# Descripción: Pruebas del endpoint de inventario de ODFs Cromo (auth, búsqueda, paginación), sin red ni DB real

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


_FILA_ODF = (
    901, "ODF Calle 9 Nro 593 PILAR", "ODF", "PILAR", "Calle 9", "593", "Metrotel", True, [111, 222], 2,
)


def test_inventario_odfs_requiere_autenticacion():
    client = TestClient(app)
    res = client.get("/api/infra/cromo/odfs")
    assert res.status_code == 401


def test_inventario_odfs_no_requiere_admin(monkeypatch):
    """Consulta de sólo lectura, mismo criterio que el resto de `/api/infra/cromo/*` — alcanza con
    estar autenticado."""
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake(total=1, filas=[_FILA_ODF])
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/odfs")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert len(body["odfs"]) == 1
    assert body["odfs"][0]["nombre"] == "ODF Calle 9 Nro 593 PILAR"
    assert body["odfs"][0]["tipo_elemento"] == "ODF"
    assert body["odfs"][0]["cantidad_cables_asociados"] == 2
    assert body["odfs"][0]["cantidad_servicios"] == 2


def test_inventario_odfs_sin_resultados(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_SesionFake(total=0, filas=[])))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/odfs?q=no-existe")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["odfs"] == []


def test_inventario_odfs_limit_acotado_a_200(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake(total=0, filas=[])
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/odfs?limit=9999")
    assert res.status_code == 200
    assert res.json()["limit"] == 200


def test_inventario_odfs_query_params_pasan_a_buscar_odfs(monkeypatch):
    """Mismo detalle que `test_inventario_cables_query_params_pasan_a_buscar_cables`: hay que
    parchear el símbolo importado localmente dentro de la función del endpoint (el objeto módulo
    `core.services.cromo.odf_inventario`, no el `web.app.main` que lo importa) — el `import` local
    del endpoint resuelve `buscar_odfs` recién en el momento de la request."""
    from web.app import main as web_main
    from core.services.cromo import odf_inventario as cromo_odf_inventario

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_SesionFake()))

    llamada = {}

    async def _buscar_odfs_fake(sesion, **kwargs):
        llamada.update(kwargs)
        return cromo_odf_inventario.ResultadoBusquedaOdfs(
            total=0, limit=kwargs["limit"], offset=kwargs["offset"], odfs=[]
        )

    monkeypatch.setattr(cromo_odf_inventario, "buscar_odfs", _buscar_odfs_fake)

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get(
        "/api/infra/cromo/odfs"
        "?q=odf&n_id=901&vigente=true&tipo_elemento=ODF&servicio=1234&limit=10&offset=5"
    )

    assert res.status_code == 200
    assert llamada == {
        "q": "odf", "n_id": 901, "vigente": True, "tipo_elemento": "ODF",
        "servicio": "1234", "limit": 10, "offset": 5,
    }
