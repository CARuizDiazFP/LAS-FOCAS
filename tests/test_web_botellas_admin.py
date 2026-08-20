# Nombre de archivo: test_web_botellas_admin.py
# Ubicación de archivo: tests/test_web_botellas_admin.py
# Descripción: Pruebas de wiring (auth/CSRF) de los endpoints admin de consolidación y export de inconsistencias de Botellas — sin DB real

from __future__ import annotations

from typing import Optional

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


def _connect_admin_ok(password: str = "adminpass"):
    pwd_hash = hash_password(password)

    def _connect(dsn: str):
        return _Conn((pwd_hash, "admin"))

    return _connect


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    return res.json()["csrf"]


# ── POST /api/infra/botellas/consolidar ──────────────────────────────────────


def test_consolidar_requiere_autenticacion():
    client = TestClient(app)
    res = client.post("/api/infra/botellas/consolidar", json={"id_destino_cromo": 999})
    assert res.status_code == 401


def test_consolidar_rechaza_csrf_invalido(monkeypatch):
    from web.app import main as web_main

    # Algunos módulos de test (test_slack_cable_info.py, test_slack_ingreso_listener.py) hacen
    # `os.environ.setdefault("TESTING", "true")` a nivel de módulo, sin revertirlo — si ya corrieron
    # antes en el mismo proceso de pytest, "TESTING" queda en "true" y el chequeo de CSRF se saltea
    # silenciosamente. Mismo workaround explícito ya usado en test_web_sla_flow.py/
    # test_web_infra_camera_state.py para este caso exacto.
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    client = TestClient(app)
    _login(client, "admin", "adminpass")

    res = client.post(
        "/api/infra/botellas/consolidar",
        json={"id_destino_cromo": 999, "ids_origen_cromo": [100], "csrf_token": "invalido"},
    )
    assert res.status_code == 403


# ── POST /api/admin/infra/botellas/operatividad ──────────────────────────────


def test_operatividad_requiere_autenticacion():
    client = TestClient(app)
    res = client.post("/api/admin/infra/botellas/operatividad", json={"n_ids": [1, 2]})
    assert res.status_code == 401


# ── GET /api/admin/infra/botellas/inconsistencias/exportar ───────────────────


def test_exportar_inconsistencias_requiere_autenticacion():
    client = TestClient(app)
    res = client.get("/api/admin/infra/botellas/inconsistencias/exportar")
    assert res.status_code == 401


# ── POST /api/infra/botellas/eliminar ────────────────────────────────────────


def test_eliminar_botella_requiere_autenticacion():
    client = TestClient(app)
    res = client.post("/api/infra/botellas/eliminar", json={"origen": "cromo", "id": 100})
    assert res.status_code == 401


def test_eliminar_botella_rechaza_csrf_invalido(monkeypatch):
    from web.app import main as web_main

    # Ver nota en test_consolidar_rechaza_csrf_invalido: algunos tests de Slack dejan
    # TESTING=true seteado a nivel de módulo sin revertirlo.
    monkeypatch.setenv("TESTING", "false")
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    client = TestClient(app)
    _login(client, "admin", "adminpass")

    res = client.post(
        "/api/infra/botellas/eliminar",
        json={"origen": "cromo", "id": 100, "csrf_token": "invalido"},
    )
    assert res.status_code == 403


# ── POST /api/infra/camaras/eliminar ─────────────────────────────────────────


def test_eliminar_camara_requiere_autenticacion():
    client = TestClient(app)
    res = client.post("/api/infra/camaras/eliminar", json={"camara_id": 1})
    assert res.status_code == 401
