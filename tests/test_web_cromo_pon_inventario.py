# Nombre de archivo: test_web_cromo_pon_inventario.py
# Ubicación de archivo: tests/test_web_cromo_pon_inventario.py
# Descripción: Pruebas del endpoint de inventario de la red de acceso PON, sin red ni DB real

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
    """Discrimina por `LIMIT :limit` y no por `count(*)`: la consulta de búsqueda trae un subselect
    `count(*)` para `cantidad_splitters` y matchearía las dos."""

    def __init__(self, total: int = 0, filas: Optional[list[tuple]] = None) -> None:
        self._total = total
        self._filas = filas or []
        self.params: list[dict] = []

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFake:
        self.params.append(params or {})
        if "LIMIT :limit" in str(stmt):
            return _ResultadoFake(filas=self._filas)
        return _ResultadoFake(escalar=self._total)


def _fake_async_session_local(sesion: _SesionFake):
    class _CM:
        async def __aenter__(self):
            return sesion

        async def __aexit__(self, *a):
            return False

    def factory():
        return _CM()

    return factory


_FILA = (
    6685166, 139, "IAAS PON ALBERDI, JUAN  AV.1642 RED", "Capital Federal",
    "ALBERDI, JUAN BAUTISTA AV.", "1642", "Metrotel", "Fast connect", 8, -34.6, -58.4, True, 3,
)


def test_requiere_autenticacion():
    client = TestClient(app)

    res = client.get("/api/infra/cromo/pon")

    assert res.status_code == 401


def test_devuelve_la_pagina_con_los_campos_de_la_caja_pon(monkeypatch):
    from web.app import main as web_main
    import db.session as db_session

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake(total=1, filas=[_FILA])
    monkeypatch.setattr(db_session, "AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/pon")

    assert res.status_code == 200
    cuerpo = res.json()
    assert cuerpo["total"] == 1
    elemento = cuerpo["elementos"][0]
    assert elemento["clase"] == 139
    assert elemento["capacidad_puertos"] == 8
    assert elemento["tipo_conector"] == "Fast connect"
    assert elemento["cantidad_splitters"] == 3


def test_clases_llega_como_lista_de_enteros(monkeypatch):
    """`?clases=84,137` es lo que distingue la vista de Cajas PON de la de Rosetas."""
    from web.app import main as web_main
    import db.session as db_session

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake()
    monkeypatch.setattr(db_session, "AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/pon?clases=84,137,140")

    assert res.status_code == 200
    assert sesion.params[0]["clases"] == [84, 137, 140]


def test_clases_con_basura_no_rompe_la_pantalla(monkeypatch):
    """Un filtro de listado mal tipeado no debería devolver 400: se ignora lo que no es número y
    el resto sigue siendo un filtro válido."""
    from web.app import main as web_main
    import db.session as db_session

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake()
    monkeypatch.setattr(db_session, "AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/pon?clases=84,ochenta%20y%20cuatro,137")

    assert res.status_code == 200
    assert sesion.params[0]["clases"] == [84, 137]


def test_limit_se_capa_en_200(monkeypatch):
    from web.app import main as web_main
    import db.session as db_session

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake()
    monkeypatch.setattr(db_session, "AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get("/api/infra/cromo/pon?limit=9999")

    assert res.status_code == 200
    assert res.json()["limit"] == 200
