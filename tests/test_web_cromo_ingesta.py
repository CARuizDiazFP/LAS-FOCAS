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
        self.agregados: list = []

    async def get(self, modelo_cls, pk):
        return self._corrida if self._corrida and self._corrida.id == pk else None

    async def execute(self, stmt, params=None):
        return _ResultadoFake(filas=self._filas_execute, escalar=self._escalar)

    async def commit(self):
        self.commits += 1

    def add(self, obj) -> None:
        self.agregados.append(obj)


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


class _RespHttpx:
    def __init__(self, status_code: int = 200, payload: Optional[dict] = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx as _httpx

            raise _httpx.HTTPStatusError("error", request=None, response=self)  # type: ignore[arg-type]

    def json(self) -> dict:
        return self._payload


def _fake_httpx_async_client(respuesta: Optional[_RespHttpx] = None, capturar: Optional[list] = None, excepcion=None):
    """Reemplaza `httpx.AsyncClient` — mismo patrón que `tests/test_web_admin.py`."""

    class _AsyncClient:
        def __init__(self, timeout: float | None = None) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: Optional[dict] = None):
            if capturar is not None:
                capturar.append((url, json))
            if excepcion is not None:
                raise excepcion
            return respuesta if respuesta is not None else _RespHttpx()

        async def get(self, url: str):
            if capturar is not None:
                capturar.append((url, None))
            if excepcion is not None:
                raise excepcion
            return respuesta if respuesta is not None else _RespHttpx()

    return _AsyncClient


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


def test_iniciar_happy_path_delega_al_worker_y_devuelve_corrida_id(monkeypatch):
    """Etapa 7: la corrida se crea acá (para responder de inmediato) y se delega al worker por HTTP."""
    from web.app import main as web_main
    from core.services.cromo import config as cromo_config
    from core.services.cromo import ingesta as cromo_ingesta

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr(cromo_config, "get_cromo_config", lambda: _CromoConfigFake())

    async def _iniciar_corrida_fake(sesion, *, usuario, psize, max_paginas, clases):
        return _FakeCorrida(id=99, usuario=usuario)

    monkeypatch.setattr(cromo_ingesta, "iniciar_corrida", _iniciar_corrida_fake)

    llamadas: list = []
    monkeypatch.setattr(web_main.httpx, "AsyncClient", _fake_httpx_async_client(capturar=llamadas))

    client = TestClient(app)
    csrf = _login(client, "admin", "admin")

    res = client.post("/api/admin/ingesta/cromo", json={"csrf_token": csrf, "psize": 10})

    assert res.status_code == 202
    assert res.json()["corrida_id"] == 99
    assert llamadas == [(web_main._CROMO_WORKER_RUN_URL, {"corrida_id": 99, "usuario": "admin"})]


def test_iniciar_503_y_marca_fallida_si_worker_no_responde(monkeypatch):
    """Si el worker está caído, la corrida (ya EN_CURSO) no debe quedar huérfana: se marca FALLIDA."""
    from web.app import main as web_main
    from core.services.cromo import config as cromo_config
    from core.services.cromo import ingesta as cromo_ingesta

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr(cromo_config, "get_cromo_config", lambda: _CromoConfigFake())

    async def _iniciar_corrida_fake(sesion, *, usuario, psize, max_paginas, clases):
        return _FakeCorrida(id=77, usuario=usuario)

    monkeypatch.setattr(cromo_ingesta, "iniciar_corrida", _iniciar_corrida_fake)
    monkeypatch.setattr(
        web_main.httpx, "AsyncClient", _fake_httpx_async_client(excepcion=ConnectionError("worker caído"))
    )

    corrida = _FakeCorrida(id=77, estado="EN_CURSO")
    sesion = _AsyncSesionFake(corrida=corrida)
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    csrf = _login(client, "admin", "admin")

    res = client.post("/api/admin/ingesta/cromo", json={"csrf_token": csrf})

    assert res.status_code == 503
    assert corrida.estado == "FALLIDA"
    assert corrida.finalizada_at is not None
    assert sesion.commits == 1


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


# ── GET/POST /api/admin/ingesta/cromo/config (Etapa 7) ───────────────────────


class _FakeCromoConfigRow:
    def __init__(self, **kwargs: Any) -> None:
        self.id = 1
        self.habilitado = kwargs.get("habilitado", False)
        self.intervalo_horas = kwargs.get("intervalo_horas", 24)
        self.hora_inicio = kwargs.get("hora_inicio")
        self.psize = kwargs.get("psize", 5)
        self.max_paginas = kwargs.get("max_paginas")
        self.clases = kwargs.get("clases", [68, 121, 122, 123, 125])
        self.ultima_ejecucion = kwargs.get("ultima_ejecucion")
        self.ultimo_error = kwargs.get("ultimo_error")


def test_config_obtener_404_si_no_existe(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    sesion = _AsyncSesionFake(corrida=None)
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))

    client = TestClient(app)
    _login(client, "admin", "admin")
    res = client.get("/api/admin/ingesta/cromo/config")
    assert res.status_code == 404


def test_config_obtener_happy_path(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())

    class _Sesion(_AsyncSesionFake):
        async def get(self, modelo_cls, pk):
            return _FakeCromoConfigRow(habilitado=True, intervalo_horas=12)

    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_Sesion()))

    client = TestClient(app)
    _login(client, "admin", "admin")
    res = client.get("/api/admin/ingesta/cromo/config")

    assert res.status_code == 200
    body = res.json()
    assert body["habilitado"] is True
    assert body["intervalo_horas"] == 12


def test_config_guardar_requiere_admin(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    client = TestClient(app)
    csrf = _login(client, "user", "userpass")

    res = client.post(
        "/api/admin/ingesta/cromo/config",
        json={"csrf_token": csrf, "habilitado": True, "intervalo_horas": 24, "psize": 5, "clases": [68]},
    )
    assert res.status_code == 403


def test_config_guardar_rechaza_psize_invalido(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    client = TestClient(app)
    csrf = _login(client, "admin", "admin")

    res = client.post(
        "/api/admin/ingesta/cromo/config",
        json={"csrf_token": csrf, "habilitado": True, "intervalo_horas": 24, "psize": 7, "clases": [68]},
    )
    assert res.status_code == 400


def test_config_guardar_rechaza_clases_vacias(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    client = TestClient(app)
    csrf = _login(client, "admin", "admin")

    res = client.post(
        "/api/admin/ingesta/cromo/config",
        json={"csrf_token": csrf, "habilitado": True, "intervalo_horas": 24, "psize": 5, "clases": []},
    )
    assert res.status_code == 400


def test_config_guardar_happy_path_actualiza_y_pide_reload(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    fila = _FakeCromoConfigRow()

    class _Sesion(_AsyncSesionFake):
        async def get(self, modelo_cls, pk):
            return fila

    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_Sesion()))
    llamadas: list = []
    monkeypatch.setattr(web_main.httpx, "AsyncClient", _fake_httpx_async_client(capturar=llamadas))

    client = TestClient(app)
    csrf = _login(client, "admin", "admin")

    res = client.post(
        "/api/admin/ingesta/cromo/config",
        json={
            "csrf_token": csrf, "habilitado": True, "intervalo_horas": 6,
            "hora_inicio": 3, "psize": 10, "max_paginas": None, "clases": [68, 121],
        },
    )

    assert res.status_code == 200
    assert fila.habilitado is True
    assert fila.intervalo_horas == 6
    assert fila.clases == [68, 121]
    assert llamadas == [(web_main._CROMO_WORKER_RELOAD_URL, None)]


def test_config_health_offline_si_worker_no_responde(monkeypatch):
    from web.app import main as web_main
    import httpx as httpx_module

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr(
        web_main.httpx, "AsyncClient", _fake_httpx_async_client(excepcion=httpx_module.ConnectError("caído"))
    )

    client = TestClient(app)
    _login(client, "admin", "admin")
    res = client.get("/api/admin/ingesta/cromo/config/health")

    assert res.status_code == 503
    assert res.json()["status"] == "offline"


def test_config_trigger_proxea_al_worker(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr(
        web_main.httpx,
        "AsyncClient",
        _fake_httpx_async_client(respuesta=_RespHttpx(status_code=202, payload={"ok": True, "corrida_id": 5})),
    )

    client = TestClient(app)
    csrf = _login(client, "admin", "admin")
    res = client.post("/api/admin/ingesta/cromo/config/trigger", json={"csrf_token": csrf})

    assert res.status_code == 202
    assert res.json() == {"ok": True, "corrida_id": 5}
