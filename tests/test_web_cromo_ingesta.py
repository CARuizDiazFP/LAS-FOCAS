# Nombre de archivo: test_web_cromo_ingesta.py
# Ubicación de archivo: tests/test_web_cromo_ingesta.py
# Descripción: Pruebas de los endpoints admin de ingesta Cromo (auth, CSRF, orquestación), sin red ni DB real

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi.testclient import TestClient  # type: ignore

from core.password import hash_password
from web.app.main import app


class _Cur:
    def __init__(self, row: Optional[tuple] = None) -> None:
        self._row = row
        self.last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None) -> None:
        self.last_sql = sql

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


def _connect_admin_ok(password: str = "admin"):
    pwd_hash = hash_password(password)

    def _connect(dsn: str):
        return _Conn((pwd_hash, "admin"))

    return _connect


def _connect_user_ok(password: str = "userpass"):
    pwd_hash = hash_password(password)

    def _connect(dsn: str):
        return _Conn((pwd_hash, "user"))

    return _connect


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["csrf"]


class _CromoConfigFake:
    psize_default = 5


class _FakeCorrida:
    def __init__(self, **kwargs: Any) -> None:
        self.id = kwargs.get("id", 1)
        self.usuario = kwargs.get("usuario", "admin")
        self.estado = kwargs.get("estado", "EN_CURSO")
        self.params = kwargs.get("params", {})
        self.total_objetivo = kwargs.get("total_objetivo", 100)
        self.leidas = kwargs.get("leidas", 0)
        self.creadas = kwargs.get("creadas", 0)
        self.actualizadas = kwargs.get("actualizadas", 0)
        self.sin_cambios = kwargs.get("sin_cambios", 0)
        self.errores = kwargs.get("errores", 0)
        self.refs_colgadas = kwargs.get("refs_colgadas", 0)
        self.iniciada_at = kwargs.get("iniciada_at", datetime.now(timezone.utc))
        self.finalizada_at = kwargs.get("finalizada_at")


class _ResultadoFake:
    def __init__(self, filas=None, escalar=None) -> None:
        self._filas = filas or []
        self._escalar = escalar

    def scalar_one(self):
        return self._escalar

    def scalars(self):
        return self

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None


class _AsyncSesionFake:
    def __init__(self, corrida: Optional[_FakeCorrida] = None, filas_execute=None, escalar=0) -> None:
        self._corrida = corrida
        self._filas_execute = filas_execute or []
        self._escalar = escalar
        self.commits = 0

    async def get(self, modelo_cls, pk):
        return self._corrida if self._corrida and self._corrida.id == pk else None

    async def execute(self, stmt, params=None):
        return _ResultadoFake(filas=self._filas_execute, escalar=self._escalar)

    async def commit(self):
        self.commits += 1


def _fake_async_session_local(sesion: _AsyncSesionFake):
    class _CM:
        async def __aenter__(self):
            return sesion

        async def __aexit__(self, *a):
            return False

    def factory():
        return _CM()

    return factory


async def _background_noop(*args, **kwargs) -> None:
    return None


# ── POST /api/admin/ingesta/cromo ────────────────────────────────────────────


def test_iniciar_requiere_admin(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    client = TestClient(app)
    csrf = _login(client, "user", "userpass")

    res = client.post("/api/admin/ingesta/cromo", json={"csrf_token": csrf})
    assert res.status_code == 403


def test_iniciar_rechaza_csrf_invalido(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    client = TestClient(app)
    _login(client, "admin", "admin")

    res = client.post("/api/admin/ingesta/cromo", json={"csrf_token": "invalido"})
    assert res.status_code == 403


def test_iniciar_rechaza_psize_invalido(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    client = TestClient(app)
    csrf = _login(client, "admin", "admin")

    res = client.post("/api/admin/ingesta/cromo", json={"csrf_token": csrf, "psize": 7})
    assert res.status_code == 400


def test_iniciar_503_si_cromo_no_configurado(monkeypatch):
    from web.app import main as web_main
    from core.services.cromo import config as cromo_config
    from core.services.cromo.config import CromoConfigError

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())

    def _config_rota():
        raise CromoConfigError("falta CROMO_BASE_URL")

    monkeypatch.setattr(cromo_config, "get_cromo_config", _config_rota)
    client = TestClient(app)
    csrf = _login(client, "admin", "admin")

    res = client.post("/api/admin/ingesta/cromo", json={"csrf_token": csrf})
    assert res.status_code == 503


def test_iniciar_happy_path_dispara_background_y_devuelve_corrida_id(monkeypatch):
    from web.app import main as web_main
    from core.services.cromo import config as cromo_config
    from core.services.cromo import ingesta as cromo_ingesta

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr(cromo_config, "get_cromo_config", lambda: _CromoConfigFake())

    llamada_background = {}

    async def _iniciar_corrida_fake(sesion, *, usuario, psize, max_paginas, clases):
        return _FakeCorrida(id=99, usuario=usuario)

    async def _background_fake(corrida_id, *, psize, max_paginas, clases):
        llamada_background["corrida_id"] = corrida_id
        llamada_background["psize"] = psize

    monkeypatch.setattr(cromo_ingesta, "iniciar_corrida", _iniciar_corrida_fake)
    monkeypatch.setattr(web_main, "_correr_ingesta_cromo_en_background", _background_fake)

    client = TestClient(app)
    csrf = _login(client, "admin", "admin")

    res = client.post("/api/admin/ingesta/cromo", json={"csrf_token": csrf, "psize": 10})

    assert res.status_code == 202
    assert res.json()["corrida_id"] == 99


# ── POST cancelar ─────────────────────────────────────────────────────────────


def test_cancelar_404_si_no_existe(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    sesion = _AsyncSesionFake(corrida=None)
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    csrf = _login(client, "admin", "admin")

    res = client.post("/api/admin/ingesta/cromo/corridas/1/cancelar", json={"csrf_token": csrf})
    assert res.status_code == 404


def test_cancelar_409_si_no_esta_en_curso(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    sesion = _AsyncSesionFake(corrida=_FakeCorrida(id=1, estado="OK"))
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    csrf = _login(client, "admin", "admin")

    res = client.post("/api/admin/ingesta/cromo/corridas/1/cancelar", json={"csrf_token": csrf})
    assert res.status_code == 409


def test_cancelar_happy_path(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    corrida = _FakeCorrida(id=1, estado="EN_CURSO")
    sesion = _AsyncSesionFake(corrida=corrida)
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    csrf = _login(client, "admin", "admin")

    res = client.post("/api/admin/ingesta/cromo/corridas/1/cancelar", json={"csrf_token": csrf})
    assert res.status_code == 200
    assert corrida.estado == "CANCELADA"
    assert sesion.commits == 1


# ── GET detalle / histórico ──────────────────────────────────────────────────


def test_detalle_404_si_no_existe(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    sesion = _AsyncSesionFake(corrida=None)
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "admin", "admin")

    res = client.get("/api/admin/ingesta/cromo/corridas/1")
    assert res.status_code == 404


def test_detalle_happy_path(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    corrida = _FakeCorrida(id=1, estado="OK", leidas=10)
    eventos = [(5, 100, 68, "CREADA", None, datetime.now(timezone.utc))]
    sesion = _AsyncSesionFake(corrida=corrida, filas_execute=eventos)
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "admin", "admin")

    res = client.get("/api/admin/ingesta/cromo/corridas/1")
    assert res.status_code == 200
    body = res.json()
    assert body["corrida"]["id"] == 1
    assert body["corrida"]["leidas"] == 10
    assert len(body["eventos"]) == 1
    assert body["eventos"][0]["accion"] == "CREADA"


def test_historico_happy_path(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    corridas = [_FakeCorrida(id=2), _FakeCorrida(id=1)]
    sesion = _AsyncSesionFake(filas_execute=corridas, escalar=2)
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "admin", "admin")

    res = client.get("/api/admin/ingesta/cromo/corridas")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2
    assert [c["id"] for c in body["corridas"]] == [2, 1]


# ── GET stream (SSE) ─────────────────────────────────────────────────────────


def test_stream_requiere_auth():
    client = TestClient(app)
    res = client.get("/api/admin/ingesta/cromo/corridas/1/stream")
    assert res.status_code == 401


def test_stream_corta_apenas_la_corrida_no_esta_en_curso(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    # Sin eventos nuevos y estado != EN_CURSO: el generador debe terminar en la primera vuelta.
    sesion = _AsyncSesionFake(filas_execute=[], escalar=("OK",))

    async def execute_dispatch(stmt, params=None):
        texto = str(stmt)
        if "cromo_ingesta_corridas" in texto:
            return _ResultadoFake(filas=[("OK",)])
        return _ResultadoFake(filas=[])

    sesion.execute = execute_dispatch
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "admin", "admin")

    with client.stream("GET", "/api/admin/ingesta/cromo/corridas/1/stream") as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        contenido = b"".join(res.iter_bytes())
    assert contenido == b""
