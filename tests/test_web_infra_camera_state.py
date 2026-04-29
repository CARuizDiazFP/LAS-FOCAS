# Nombre de archivo: test_web_infra_camera_state.py
# Ubicación de archivo: tests/test_web_infra_camera_state.py
# Descripción: Pruebas del flujo web para consulta y edición manual del estado de cámaras

import re
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi.testclient import TestClient

from core.password import hash_password
from core.services.camara_estado_service import (
    ActualizacionEstadoResultado,
    CamaraEstadoContexto,
    IncidenteActivoResumen,
)
from db.models.infra import CamaraEstado


from web.app.main import app  # type: ignore  # noqa: E402


class _Cur:
    def __init__(self, row: Optional[tuple[Any, ...]] = None):
        self._row = row
        self.last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: tuple[Any, ...] | None = None):
        self.last_sql = sql

    def fetchone(self):
        if "SELECT password_hash, role FROM app.web_users" in self.last_sql:
            return self._row
        return self._row


class _Conn:
    def __init__(self, row: tuple[Any, ...]):
        self.cur = _Cur(row)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cur

    def commit(self):
        pass


def _connect_ok(role: str, password: str):
    pwd_hash = hash_password(password)

    def _connect(dsn: str):  # type: ignore
        return _Conn((pwd_hash, role))

    return _connect


class _SessionScope:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _login(client: TestClient, monkeypatch, *, role: str, password: str = "secret") -> str:
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_ok(role, password))
    response = client.post(
        "/login",
        data={"username": role, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 302
    html = client.get("/").text
    csrf = re.search(r'window.CSRF_TOKEN = "([\w-]+)";', html)
    assert csrf is not None
    return csrf.group(1)


def _build_contexto() -> CamaraEstadoContexto:
    return CamaraEstadoContexto(
        camara_id=7,
        estado_actual=CamaraEstado.LIBRE,
        estado_sugerido=CamaraEstado.BANEADA,
        tiene_baneo_activo=True,
        tiene_ingreso_activo=False,
        inconsistente=True,
        incidentes_activos=[
            IncidenteActivoResumen(
                id=11,
                ticket_asociado="INC-11",
                servicio_protegido_id="2001",
                ruta_protegida_id=33,
                fecha_inicio="2026-04-20T10:00:00+00:00",
                motivo="Protección temporal",
            )
        ],
        ticket_baneo="INC-11",
    )


def test_panel_inyecta_user_role(monkeypatch):
    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    html = client.get("/").text

    assert 'window.USER_ROLE = "admin";' in html


def test_get_camara_estado_forbidden_para_no_admin(monkeypatch):
    client = TestClient(app)
    _login(client, monkeypatch, role="user", password="userpass")

    response = client.get("/api/infra/camaras/7/estado")

    assert response.status_code == 403


def test_get_camara_estado_admin_devuelve_contexto(monkeypatch):
    from core.services import camara_estado_service
    from db import session as db_session

    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    fake_session = _FakeSession()
    monkeypatch.setattr(db_session, "SessionLocal", _SessionScope(fake_session))
    monkeypatch.setattr(camara_estado_service, "get_camara_estado_contexto", lambda session, camara_id: _build_contexto())

    response = client.get("/api/infra/camaras/7/estado")

    assert response.status_code == 200
    payload = response.json()
    assert payload["editable"] is True
    assert payload["contexto"]["estado_sugerido"] == "BANEADA"
    assert payload["contexto"]["incidentes_activos"][0]["ticket_asociado"] == "INC-11"


def test_update_camara_estado_rechaza_csrf_invalido(monkeypatch):
    monkeypatch.setenv("TESTING", "false")
    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    response = client.post(
        "/api/infra/camaras/7/estado",
        json={"estado": "LIBRE", "motivo": "Corrección manual validada"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "CSRF inválido"


def test_update_camara_estado_admin_audita_y_confirma(monkeypatch):
    from core.services import camara_estado_service
    from db import session as db_session

    client = TestClient(app)
    csrf = _login(client, monkeypatch, role="admin", password="admin")

    fake_session = _FakeSession()
    contexto = _build_contexto()

    monkeypatch.setattr(db_session, "SessionLocal", _SessionScope(fake_session))

    def _fake_override(session, camara_id, nuevo_estado, *, usuario, motivo):
        assert session is fake_session
        assert camara_id == 7
        assert nuevo_estado == CamaraEstado.LIBRE
        assert usuario == "admin"
        assert motivo == "Corrección manual validada"
        return ActualizacionEstadoResultado(
            success=True,
            camara_id=camara_id,
            changed=True,
            audit_id=19,
            contexto=contexto,
        )

    monkeypatch.setattr(camara_estado_service, "override_camara_estado_manual", _fake_override)

    response = client.post(
        "/api/infra/camaras/7/estado",
        json={
            "estado": "LIBRE",
            "motivo": "Corrección manual validada",
            "csrf_token": csrf,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["audit_id"] == 19
    assert fake_session.committed is True
    assert fake_session.rolled_back is False