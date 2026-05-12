# Nombre de archivo: test_web_baneos.py
# Ubicación de archivo: tests/test_web_baneos.py
# Descripción: Pruebas del flujo web same-origin para crear y levantar baneos con notificación Slack.

from __future__ import annotations

import re
from types import SimpleNamespace

from fastapi.testclient import TestClient

from core.password import hash_password
from web.app.main import app


class _Cur:
    def __init__(self, row: tuple[str, str]):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        return None

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row: tuple[str, str]):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _Cur(self._row)


def _connect_admin_ok(password: str = "admin"):
    pwd_hash = hash_password(password)

    def _connect(dsn: str):  # type: ignore[unused-argument]
        return _Conn((pwd_hash, "admin"))

    return _connect


class _FakeSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _login_admin(client: TestClient, monkeypatch) -> None:
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok("admin"))
    client.post("/login", data={"username": "admin", "password": "admin"})
    html = client.get("/").text
    assert re.search(r'window.CSRF_TOKEN = "([\w-]+)";', html)


def test_create_ban_web_notifica_slack(monkeypatch):
    from core.services import protection_service
    from core import config as core_config
    from db import session as db_session
    from modules.slack_baneo_notifier import eventos

    client = TestClient(app)
    _login_admin(client, monkeypatch)

    fake_session = _FakeSession()
    llamadas: list[tuple[str, dict[str, object], str]] = []

    monkeypatch.setattr(db_session, "SessionLocal", lambda: fake_session)
    monkeypatch.setattr(
        protection_service,
        "create_ban",
        lambda *args, **kwargs: SimpleNamespace(
            success=True,
            camaras_baneadas=3,
            to_dict=lambda: {"success": True, "incidente_id": 77, "camaras_baneadas": 3},
        ),
    )
    monkeypatch.setattr(core_config, "get_settings", lambda: SimpleNamespace(slack=SimpleNamespace(bot_token="token")))
    monkeypatch.setattr(
        eventos,
        "notificar_evento_baneo",
        lambda session, tipo, datos, token: llamadas.append((tipo, datos, token)),
    )

    res = client.post(
        "/api/infra/ban/create",
        json={
            "ticket_asociado": "INC-1",
            "servicio_afectado_id": "93152",
            "servicio_protegido_id": "93150",
            "motivo": "Corte",
        },
    )

    assert res.status_code == 200
    assert res.json()["success"] is True
    assert fake_session.committed is True
    assert llamadas and llamadas[0][0] == "create"
    assert llamadas[0][1]["servicio_afectado_id"] == "93152"
    assert llamadas[0][1]["servicio_protegido_id"] == "93150"
    assert llamadas[0][1]["usuario_ejecutor"] == "admin"


def test_lift_ban_web_notifica_slack(monkeypatch):
    from core.services import protection_service
    from core import config as core_config
    from db import session as db_session
    from modules.slack_baneo_notifier import eventos

    client = TestClient(app)
    _login_admin(client, monkeypatch)

    fake_session = _FakeSession()
    llamadas: list[tuple[str, dict[str, object], str]] = []

    monkeypatch.setattr(db_session, "SessionLocal", lambda: fake_session)
    monkeypatch.setattr(
        protection_service,
        "lift_ban",
        lambda *args, **kwargs: SimpleNamespace(
            success=True,
            camaras_restauradas=4,
            to_dict=lambda: {"success": True, "incidente_id": 77, "camaras_restauradas": 4},
        ),
    )
    monkeypatch.setattr(core_config, "get_settings", lambda: SimpleNamespace(slack=SimpleNamespace(bot_token="token")))
    monkeypatch.setattr(
        eventos,
        "notificar_evento_baneo",
        lambda session, tipo, datos, token: llamadas.append((tipo, datos, token)),
    )

    res = client.post(
        "/api/infra/ban/lift",
        json={
            "incidente_id": 77,
            "motivo_cierre": "Reparado",
        },
    )

    assert res.status_code == 200
    assert res.json()["success"] is True
    assert fake_session.committed is True
    assert llamadas and llamadas[0][0] == "lift"
    assert llamadas[0][1]["usuario_ejecutor"] == "admin"
    assert llamadas[0][1]["motivo_cierre"] == "Reparado"