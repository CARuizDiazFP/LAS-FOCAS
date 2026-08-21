# Nombre de archivo: test_web_cromo_repoblar_cables.py
# Ubicación de archivo: tests/test_web_cromo_repoblar_cables.py
# Descripción: Pruebas de wiring (auth/admin/CSRF) de los endpoints de detección/repoblación de cables y edición de nombre del Verificador Cromo — sin red ni DB real

from __future__ import annotations

from typing import Any, Optional

from fastapi.testclient import TestClient  # type: ignore

from core.password import hash_password
from db.models.cromo import CromoBotella, CromoCable
from web.app.main import app

BOTELLA_N_ID = 9057909
CABLE_N_ID = 9062238

BOTELLA_VIGENTE = {
    "id": 9057952,
    "n_id": BOTELLA_N_ID,
    "class": 68,
    "hist": [{"id": BOTELLA_N_ID, "next_id": 9057952}, {"id": 9057952, "next_id": 0}],
    "tp": [{"type": 0, "nfrom": 0, "id_to": CABLE_N_ID, "class": 51}],
}
CABLE_COMPLETO = {
    "id": 9203453,
    "n_id": CABLE_N_ID,
    "class": 51,
    "vmax": 100,
    "hist": [{"id": 9203453, "next_id": 0}],
    "tp": [
        {"type": 0, "nfrom": 0, "id_to": 111111, "class": 125},
        {"type": 0, "nfrom": 1, "id_to": BOTELLA_N_ID, "class": 68},
    ],
    "inner": [],
    "at": [],
}


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


def _connect_ok(password: str, role: str):
    pwd_hash = hash_password(password)

    def _connect(dsn: str):
        return _Conn((pwd_hash, role))

    return _connect


def _connect_user_ok(password: str = "userpass"):
    return _connect_ok(password, "user")


def _connect_admin_ok(password: str = "adminpass"):
    return _connect_ok(password, "admin")


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["csrf"]


class _NestedCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Escalares:
    def __init__(self, valores: list[Any]) -> None:
        self._valores = valores

    def all(self):
        return self._valores


class _ResultadoVacio:
    def scalars(self):
        return _Escalares([])


class _SesionFake:
    def __init__(self, existentes: Optional[dict[tuple[type, Any], Any]] = None) -> None:
        self._existentes = existentes or {}
        self.agregados: list[Any] = []

    async def get(self, modelo_cls: type, pk: Any) -> Any:
        return self._existentes.get((modelo_cls, pk))

    def add(self, obj: Any) -> None:
        self.agregados.append(obj)
        n_id = getattr(obj, "n_id", None)
        if n_id is not None:
            self._existentes[(type(obj), n_id)] = obj

    def begin_nested(self) -> _NestedCM:
        return _NestedCM()

    async def execute(self, stmt: Any) -> _ResultadoVacio:
        return _ResultadoVacio()

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = 1


def _fake_async_session_local(sesion: _SesionFake):
    class _CM:
        async def __aenter__(self):
            return sesion

        async def __aexit__(self, *a):
            return False

    def factory():
        return _CM()

    return factory


def _cliente_cromo_fake(respuestas: Optional[dict[int, dict]] = None, error: Optional[Exception] = None):
    """Fábrica de un `CromoClient` fake usable como `async with CromoClient(...) as cliente:`,
    para `get_objeto_con_topologia` (envuelve como Cromo real: `{"st":0,"response":...}`)."""

    class _ClienteFake:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a: Any) -> bool:
            return False

        async def get_objeto_con_topologia(self, n_id: int) -> dict:
            if error is not None:
                raise error
            return {"st": 0, "response": (respuestas or {})[n_id]}

    return _ClienteFake


def _sin_validar_config_cromo():
    return None


def _botella_local() -> CromoBotella:
    return CromoBotella(n_id=BOTELLA_N_ID, version_id=1, vmax=168149, nombre="B2-FO-CAR", clase=68, payload_raw={})


def _parchear_cromo(monkeypatch, cliente_fake) -> None:
    import core.services.cromo.client as cromo_client_module
    import core.services.cromo.config as cromo_config_module

    monkeypatch.setattr(cromo_config_module, "get_cromo_config", _sin_validar_config_cromo)
    monkeypatch.setattr(cromo_client_module, "CromoClient", cliente_fake)


# ── GET /api/infra/cromo/botellas/{n_id}/cables-detectados ──────────────────


def test_cables_detectados_requiere_autenticacion():
    client = TestClient(app)
    res = client.get(f"/api/infra/cromo/botellas/{BOTELLA_N_ID}/cables-detectados")
    assert res.status_code == 401


def test_cables_detectados_no_requiere_admin(monkeypatch):
    from web.app import main as web_main
    from core.services.cromo.client import CromoClientError

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake({(CromoBotella, BOTELLA_N_ID): _botella_local()})
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))
    _parchear_cromo(
        monkeypatch,
        _cliente_cromo_fake({BOTELLA_N_ID: BOTELLA_VIGENTE, CABLE_N_ID: CABLE_COMPLETO}),
    )

    client = TestClient(app)
    _login(client, "user", "userpass")  # rol "user", no admin

    res = client.get(f"/api/infra/cromo/botellas/{BOTELLA_N_ID}/cables-detectados")
    assert res.status_code == 200
    payload = res.json()
    assert payload["botella_n_id"] == BOTELLA_N_ID
    assert len(payload["cables"]) == 1
    assert payload["cables"][0]["n_id"] == CABLE_N_ID
    assert payload["cables"][0]["estado_local"] == "FALTA"


def test_cables_detectados_404_si_botella_no_existe_local(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_SesionFake()))
    _parchear_cromo(monkeypatch, _cliente_cromo_fake({}))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get(f"/api/infra/cromo/botellas/{BOTELLA_N_ID}/cables-detectados")
    assert res.status_code == 404


def test_cables_detectados_502_si_cromo_no_responde(monkeypatch):
    from web.app import main as web_main
    from core.services.cromo.client import CromoClientError

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    sesion = _SesionFake({(CromoBotella, BOTELLA_N_ID): _botella_local()})
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))
    _parchear_cromo(monkeypatch, _cliente_cromo_fake(error=CromoClientError("caído", status_code=503)))

    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.get(f"/api/infra/cromo/botellas/{BOTELLA_N_ID}/cables-detectados")
    assert res.status_code == 502


# ── POST /api/infra/botellas/{n_id}/repoblar-cables ──────────────────────────


def test_repoblar_cables_requiere_autenticacion():
    client = TestClient(app)
    res = client.post(f"/api/infra/botellas/{BOTELLA_N_ID}/repoblar-cables", json={})
    assert res.status_code == 401


def test_repoblar_cables_rechaza_no_admin(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.post(f"/api/infra/botellas/{BOTELLA_N_ID}/repoblar-cables", json={})
    assert res.status_code == 403


def test_repoblar_cables_rechaza_csrf_invalido(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setenv("TESTING", "false")  # ver nota en test_web_botellas_admin.py
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    client = TestClient(app)
    _login(client, "admin", "adminpass")

    res = client.post(
        f"/api/infra/botellas/{BOTELLA_N_ID}/repoblar-cables", json={"csrf_token": "invalido"}
    )
    assert res.status_code == 403


def test_repoblar_cables_happy_path_crea_cable_faltante(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    sesion = _SesionFake({(CromoBotella, BOTELLA_N_ID): _botella_local()})
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))
    _parchear_cromo(
        monkeypatch,
        _cliente_cromo_fake({BOTELLA_N_ID: BOTELLA_VIGENTE, CABLE_N_ID: CABLE_COMPLETO}),
    )

    client = TestClient(app)
    csrf = _login(client, "admin", "adminpass")

    res = client.post(
        f"/api/infra/botellas/{BOTELLA_N_ID}/repoblar-cables", json={"csrf_token": csrf}
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    assert payload["creados"] == 1
    assert payload["errores"] == 0
    cables_creados = [o for o in sesion.agregados if isinstance(o, CromoCable)]
    assert len(cables_creados) == 1
    assert cables_creados[0].n_id == CABLE_N_ID
    assert BOTELLA_N_ID in (cables_creados[0].extremo_a_n_id, cables_creados[0].extremo_b_n_id)


# ── PATCH /api/infra/botellas/{n_id}/nombre ──────────────────────────────────


def test_actualizar_nombre_requiere_autenticacion():
    client = TestClient(app)
    res = client.patch(f"/api/infra/botellas/{BOTELLA_N_ID}/nombre", json={"nombre": "Nuevo"})
    assert res.status_code == 401


def test_actualizar_nombre_rechaza_no_admin(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_user_ok())
    client = TestClient(app)
    _login(client, "user", "userpass")

    res = client.patch(f"/api/infra/botellas/{BOTELLA_N_ID}/nombre", json={"nombre": "Nuevo"})
    assert res.status_code == 403


def test_actualizar_nombre_rechaza_csrf_invalido(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    client = TestClient(app)
    _login(client, "admin", "adminpass")

    res = client.patch(
        f"/api/infra/botellas/{BOTELLA_N_ID}/nombre",
        json={"nombre": "Nuevo", "csrf_token": "invalido"},
    )
    assert res.status_code == 403


def test_actualizar_nombre_rechaza_vacio(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    sesion = _SesionFake({(CromoBotella, BOTELLA_N_ID): _botella_local()})
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))
    client = TestClient(app)
    csrf = _login(client, "admin", "adminpass")

    res = client.patch(
        f"/api/infra/botellas/{BOTELLA_N_ID}/nombre", json={"nombre": "   ", "csrf_token": csrf}
    )
    assert res.status_code == 422 or res.status_code == 400  # min_length=1 puede rechazarlo antes


def test_actualizar_nombre_404_si_no_existe(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(_SesionFake()))
    client = TestClient(app)
    csrf = _login(client, "admin", "adminpass")

    res = client.patch(
        f"/api/infra/botellas/{BOTELLA_N_ID}/nombre", json={"nombre": "Nuevo nombre", "csrf_token": csrf}
    )
    assert res.status_code == 404


def test_actualizar_nombre_happy_path_marca_editado_manual(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    botella = _botella_local()
    sesion = _SesionFake({(CromoBotella, BOTELLA_N_ID): botella})
    monkeypatch.setattr("db.session.AsyncSessionLocal", _fake_async_session_local(sesion))
    client = TestClient(app)
    csrf = _login(client, "admin", "adminpass")

    res = client.patch(
        f"/api/infra/botellas/{BOTELLA_N_ID}/nombre",
        json={"nombre": "  B2-FO-CAR (corregido)  ", "csrf_token": csrf},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload == {"ok": True, "n_id": BOTELLA_N_ID, "nombre": "B2-FO-CAR (corregido)"}
    assert botella.nombre == "B2-FO-CAR (corregido)"
    assert botella.nombre_editado_manual is True
