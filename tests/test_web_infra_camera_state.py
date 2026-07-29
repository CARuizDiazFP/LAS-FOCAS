# Nombre de archivo: test_web_infra_camera_state.py
# Ubicación de archivo: tests/test_web_infra_camera_state.py
# Descripción: Pruebas del flujo web para consulta y edición manual del estado de cámaras

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from fastapi.testclient import TestClient

from core.password import hash_password
from core.services.camara_estado_service import (
    ActualizacionEstadoResultado,
    CamaraEstadoContexto,
    IncidenteActivoResumen,
)
from db.models.infra import CamaraEstado, CamaraOrigenDatos, RutaTipo


from web.app.main import _serialize_camara_response, app  # type: ignore  # noqa: E402


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


class _FakeQuery:
    def __init__(self, *, one: Any = None, many: Optional[list[Any]] = None):
        self._one = one
        self._many = many or []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def first(self):
        if self._one is not None:
            return self._one
        return self._many[0] if self._many else None

    def all(self):
        return list(self._many)


class _InfraDetailSession(_FakeSession):
    def __init__(self, camara: Any, aliases: list[Any], auditoria: list[Any], baneos: list[Any]):
        super().__init__()
        self._camara = camara
        self._aliases = aliases
        self._auditoria = auditoria
        self._baneos = baneos

    def query(self, *entities):
        entity_count = len(entities)
        if entity_count == 2:
            return _FakeQuery(one=SimpleNamespace(id=self._camara.id, nombre=self._camara.nombre))

        entity = entities[0]
        entity_name = getattr(entity, "__name__", "")
        if entity_name == "Camara":
            return _FakeQuery(one=self._camara)
        if entity_name == "CamaraAlias":
            return _FakeQuery(many=self._aliases)
        if entity_name == "CamaraEstadoAuditoria":
            return _FakeQuery(many=self._auditoria)
        if entity_name == "IncidenteBaneo":
            return _FakeQuery(many=self._baneos)
        return _FakeQuery()


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


def _build_fake_camara() -> Any:
    ruta = SimpleNamespace(
        id=33,
        servicio=SimpleNamespace(servicio_id="2001", alias_ids=["O1C1"]),
        nombre="Ruta Principal",
        tipo=RutaTipo.PRINCIPAL,
        empalmes=[SimpleNamespace(es_transito=False), SimpleNamespace(es_transito=True)],
        punta_a=SimpleNamespace(sitio="POP A"),
        punta_b=SimpleNamespace(sitio="POP B"),
    )
    empalme = SimpleNamespace(rutas=[ruta], servicios=[])
    return SimpleNamespace(
        id=7,
        nombre="Cámara Canon Norte",
        direccion="Av. Siempre Viva 742",
        fontine_id="CAM-007",
        estado=CamaraEstado.LIBRE,
        origen_datos=CamaraOrigenDatos.TRACKING,
        latitud=-34.6,
        longitud=-58.4,
        empalmes=[empalme],
    )


def _build_aliases() -> list[Any]:
    return [
        SimpleNamespace(
            id=1,
            alias_nombre="Canon Norte",
            created_at=datetime(2026, 5, 1, 15, 30, tzinfo=timezone.utc),
        )
    ]


def _build_auditoria() -> list[Any]:
    return [
        SimpleNamespace(
            id=19,
            usuario="admin",
            motivo="Corrección manual validada",
            estado_anterior=CamaraEstado.BANEADA,
            estado_nuevo=CamaraEstado.LIBRE,
            estado_sugerido=CamaraEstado.BANEADA,
            incidentes_activos=[11],
            created_at=datetime(2026, 5, 12, 9, 45, tzinfo=timezone.utc),
        )
    ]


def _build_baneos() -> list[Any]:
    return [
        SimpleNamespace(
            id=11,
            ticket_asociado="INC-11",
            servicio_afectado_id="1999",
            servicio_protegido_id="2001",
            ruta_protegida_id=33,
            motivo="Protección temporal",
            activo=True,
            fecha_inicio=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
            fecha_fin=None,
        )
    ]


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


def test_serialize_camara_response_incluye_id_en_payload_web() -> None:
    camara = _build_fake_camara()

    payload = _serialize_camara_response(
        camara=camara,
        rutas_info=[
            {
                "ruta_id": 33,
                "servicio_id": "2001",
                "ruta_nombre": "Ruta Principal",
                "ruta_tipo": "PRINCIPAL",
            }
        ],
        servicios_ids=["2001"],
        contexto=_build_contexto(),
        editable=True,
    )

    assert payload["id"] == 7
    assert payload["nombre"] == "Cámara Canon Norte"


def test_get_camara_detail_web_devuelve_resumen_operativo(monkeypatch):
    from core.services import camara_estado_service
    from db import session as db_session

    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    fake_session = _InfraDetailSession(_build_fake_camara(), _build_aliases(), _build_auditoria(), _build_baneos())
    monkeypatch.setattr(db_session, "SessionLocal", _SessionScope(fake_session))
    monkeypatch.setattr(camara_estado_service, "get_camara_estado_contexto", lambda session, camara_id: _build_contexto())

    response = client.get("/api/infra/camaras/7")

    assert response.status_code == 200
    payload = response.json()
    assert payload["camara"]["id"] == 7
    assert payload["camara"]["nombre"] == "Cámara Canon Norte"
    assert payload["camara"]["rutas"][0]["servicio_id"] == "2001"
    assert payload["camara"]["rutas"][0]["alias_ids"] == ["O1C1"]
    assert payload["camara"]["rutas"][0]["transitos_count"] == 1
    assert payload["camara"]["rutas"][0]["punta_a_sitio"] == "POP A"
    assert payload["camara"]["rutas"][0]["punta_b_sitio"] == "POP B"


def test_get_camara_aliases_web_devuelve_alias_registrados(monkeypatch):
    from db import session as db_session

    client = TestClient(app)
    _login(client, monkeypatch, role="user", password="userpass")

    fake_session = _InfraDetailSession(_build_fake_camara(), _build_aliases(), _build_auditoria(), _build_baneos())
    monkeypatch.setattr(db_session, "SessionLocal", _SessionScope(fake_session))

    response = client.get("/api/infra/camaras/7/aliases")

    assert response.status_code == 200
    payload = response.json()
    assert payload["camara_id"] == 7
    assert payload["total"] == 1
    assert payload["aliases"][0]["nombre"] == "Canon Norte"


def test_get_camara_registros_web_devuelve_auditoria_y_baneos(monkeypatch):
    from core.services import camara_estado_service
    from db import session as db_session

    client = TestClient(app)
    _login(client, monkeypatch, role="user", password="userpass")

    fake_session = _InfraDetailSession(_build_fake_camara(), _build_aliases(), _build_auditoria(), _build_baneos())
    monkeypatch.setattr(db_session, "SessionLocal", _SessionScope(fake_session))
    monkeypatch.setattr(camara_estado_service, "get_camara_estado_contexto", lambda session, camara_id: _build_contexto())

    response = client.get("/api/infra/camaras/7/registros")

    assert response.status_code == 200
    payload = response.json()
    assert payload["camara_id"] == 7
    assert payload["auditoria"][0]["motivo"] == "Corrección manual validada"
    assert payload["baneos"][0]["ticket_asociado"] == "INC-11"
    assert "ingresos" in payload["placeholders"]