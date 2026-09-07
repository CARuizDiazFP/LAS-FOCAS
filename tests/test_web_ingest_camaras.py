# Nombre de archivo: test_web_ingest_camaras.py
# Ubicación de archivo: tests/test_web_ingest_camaras.py
# Descripción: Pruebas de la Tarea 3 (rutas backend de ingesta de cámaras): nueva forma de respuesta
# de POST /ingest/camaras, endpoints de asociación manual sin-match→Cámara y marcado masivo de
# revisado, y filtro `origen` en el listado de IngresoSinMatch

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
from fastapi.testclient import TestClient

from core.password import hash_password


API_HEADERS = {"Authorization": "Bearer test-api-key"}


# ── Helpers compartidos de login/sesión (mismo patrón que test_web_infra_camera_state.py y
# test_web_botellas_admin.py: mock de psycopg.connect para no depender de una DB real) ──────────


class _Cur:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        return None

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self.cur = _Cur(row)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cur

    def commit(self) -> None:
        return None


def _connect_ok(role: str, password: str):
    pwd_hash = hash_password(password)

    def _connect(dsn: str):  # type: ignore
        return _Conn((pwd_hash, role))

    return _connect


def _login(client: TestClient, monkeypatch, *, role: str, password: str = "secret") -> str:
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", _connect_ok(role, password))
    response = client.post("/api/auth/login", json={"username": role, "password": password})
    assert response.status_code == 200
    return response.json()["csrf"]


class _FakeSyncSessionCtx:
    """Contexto `with SessionLocal() as session:` fake — mismo patrón que test_web_botellas_admin.py."""

    def __init__(self, session: Any) -> None:
        self._session = session

    def __enter__(self) -> Any:
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _fake_session_local(session: Any):
    def _factory():
        return _FakeSyncSessionCtx(session)

    return _factory


# ── 1. POST /ingest/camaras (api/app/routes/ingest.py) — nueva forma de respuesta ───────────────


def test_ingest_camaras_devuelve_nueva_forma_de_respuesta(monkeypatch):
    """La Tarea 2 reemplazó creadas/preexistentes/baneadas por
    total_leidos/grupos_baneados/grupos_ya_baneados/sin_match/errores — discriminante de que la ruta
    HTTP quedó conectada a la forma nueva de `CamaraIngestaResultado`, no a la vieja. También verifica
    que `file.filename` se pasa como `archivo_origen` a `procesar_ingesta_camaras`."""
    from api.app.main import create_app
    from api.app.routes import ingest as ingest_route
    from core.services.camara_ingest_service import CamaraIngestaResultado, NombreSinMatch

    llamadas: list[dict[str, Any]] = []

    def _fake_procesar(aliases, motivo_baneo, usuario, *, archivo_origen=None):
        llamadas.append(
            {
                "aliases": aliases,
                "motivo_baneo": motivo_baneo,
                "usuario": usuario,
                "archivo_origen": archivo_origen,
            }
        )
        return CamaraIngestaResultado(
            total_leidos=3,
            grupos_baneados=1,
            grupos_ya_baneados=1,
            sin_match=[NombreSinMatch(caso_id=42, nombre="Camara Fantasma")],
            errores=["alias-x: error simulado"],
        )

    monkeypatch.setattr(ingest_route, "procesar_ingesta_camaras", _fake_procesar)

    df = pd.DataFrame([["ignorada1", "Camara A"], ["ignorada2", "Camara B"]])
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, header=False)
    buffer.seek(0)

    client = TestClient(create_app())
    files = {
        "file": (
            "camaras.xlsx",
            buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    data = {"motivo_baneo": "Corte programado", "usuario": "admin"}

    response = client.post("/ingest/camaras", data=data, files=files, headers=API_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_leidos"] == 3
    assert payload["grupos_baneados"] == 1
    assert payload["grupos_ya_baneados"] == 1
    assert payload["sin_match"] == [{"caso_id": 42, "nombre": "Camara Fantasma"}]
    assert payload["errores"] == ["alias-x: error simulado"]
    for campo_legado in ("creadas", "preexistentes", "baneadas"):
        assert campo_legado not in payload

    assert len(llamadas) == 1
    assert llamadas[0]["archivo_origen"] == "camaras.xlsx"


# ── 2. POST /api/admin/ingesta/camaras/asociar (web/app/main.py) ────────────────────────────────


def test_asociar_camaras_sin_admin_devuelve_403(monkeypatch):
    from web.app.main import app

    client = TestClient(app)
    _login(client, monkeypatch, role="user", password="userpass")

    response = client.post(
        "/api/admin/ingesta/camaras/asociar",
        json={"caso_ids": [1], "camara_id": 10},
    )

    assert response.status_code == 403


def test_asociar_camaras_csrf_invalido_devuelve_403(monkeypatch):
    from web.app.main import app

    # Workaround explícito ya usado en test_web_infra_camera_state.py/test_web_botellas_admin.py:
    # otro módulo de test puede haber dejado TESTING=true en el proceso, lo que saltearía el chequeo.
    monkeypatch.setenv("TESTING", "false")
    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    response = client.post(
        "/api/admin/ingesta/camaras/asociar",
        json={"caso_ids": [1], "camara_id": 10, "csrf_token": "invalido"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "CSRF inválido"


def test_asociar_camaras_caso_ids_vacio_devuelve_400(monkeypatch):
    from web.app.main import app

    monkeypatch.setenv("TESTING", "true")
    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    response = client.post(
        "/api/admin/ingesta/camaras/asociar",
        json={"caso_ids": [], "camara_id": 10, "csrf_token": "cualquiera"},
    )

    assert response.status_code == 400
    assert "caso" in response.json()["error"].lower()


def test_asociar_camaras_camara_no_encontrada_devuelve_404(monkeypatch):
    from web.app import main as web_main
    from core.services.camara_ingest_service import AsociacionManualResultado

    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(MagicMock()))

    resultado = AsociacionManualResultado(
        ok=False,
        camara_id=999,
        camara_nombre="",
        estado_final="",
        baneo_aplicado=False,
        alias_creados=0,
        alias_preexistentes=0,
        casos_marcados=0,
        error="Cámara no encontrada",
    )
    monkeypatch.setattr(
        "core.services.camara_ingest_service.asociar_nombres_a_camara",
        lambda session, **kwargs: resultado,
    )

    client = TestClient(web_main.app)
    _login(client, monkeypatch, role="admin", password="admin")

    response = client.post(
        "/api/admin/ingesta/camaras/asociar",
        json={"caso_ids": [1, 2], "camara_id": 999, "csrf_token": "cualquiera"},
    )

    assert response.status_code == 404
    assert response.json()["error"] == "Cámara no encontrada"


def test_asociar_camaras_motivo_vacio_usa_default(monkeypatch):
    """Ruling registrado en el ledger del plan: motivo vacío/omitido usa el default en vez de
    rechazar el request, porque `asociar_nombres_a_camara` exige `motivo` no vacío."""
    from web.app import main as web_main
    from core.services.camara_ingest_service import AsociacionManualResultado

    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(MagicMock()))

    resultado = AsociacionManualResultado(
        ok=True,
        camara_id=10,
        camara_nombre="Camara Test",
        estado_final="BANEADA",
        baneo_aplicado=True,
        alias_creados=2,
        alias_preexistentes=0,
        casos_marcados=2,
    )

    llamadas: list[dict[str, Any]] = []

    def _fake_asociar(session, **kwargs):
        llamadas.append(kwargs)
        return resultado

    monkeypatch.setattr("core.services.camara_ingest_service.asociar_nombres_a_camara", _fake_asociar)

    client = TestClient(web_main.app)
    _login(client, monkeypatch, role="admin", password="admin")

    response = client.post(
        "/api/admin/ingesta/camaras/asociar",
        json={"caso_ids": [1, 2], "camara_id": 10, "motivo": "   ", "csrf_token": "cualquiera"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["camara_id"] == 10
    assert payload["alias_creados"] == 2
    assert payload["conflictos"] == []

    assert len(llamadas) == 1
    assert llamadas[0]["motivo"] == "Baneo por ingesta Excel (asociación manual)"


# ── 3. POST /api/admin/infra/ingresos-sin-match/marcar-revisado-masivo ──────────────────────────


def test_marcar_revisado_masivo_sin_admin_devuelve_403(monkeypatch):
    from web.app.main import app

    client = TestClient(app)
    _login(client, monkeypatch, role="user", password="userpass")

    response = client.post(
        "/api/admin/infra/ingresos-sin-match/marcar-revisado-masivo",
        json={"ids": [1, 2]},
    )

    assert response.status_code == 403


def test_marcar_revisado_masivo_ids_vacio_devuelve_400(monkeypatch):
    from web.app.main import app

    monkeypatch.setenv("TESTING", "true")
    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    response = client.post(
        "/api/admin/infra/ingresos-sin-match/marcar-revisado-masivo",
        json={"ids": [], "csrf_token": "cualquiera"},
    )

    assert response.status_code == 400


def test_marcar_revisado_masivo_devuelve_conteo_de_actualizados(monkeypatch):
    from web.app.main import app

    monkeypatch.setenv("TESTING", "true")

    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value.update.return_value = 3
    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(fake_session))

    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    response = client.post(
        "/api/admin/infra/ingresos-sin-match/marcar-revisado-masivo",
        json={"ids": [1, 2, 3], "csrf_token": "cualquiera"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["actualizados"] == 3
    fake_session.commit.assert_called_once()


# ── 4. GET /api/admin/infra/ingresos-sin-match — filtro `origen` ────────────────────────────────


class _FakeIngresosQuery:
    def __init__(self, casos: list[Any]) -> None:
        self._casos = casos
        self.filtros: list[Any] = []

    def filter(self, *args: Any):
        self.filtros.extend(args)
        return self

    def order_by(self, *args: Any, **kwargs: Any):
        return self

    def limit(self, *args: Any, **kwargs: Any):
        return self

    def all(self) -> list[Any]:
        return list(self._casos)


class _FakeIngresosSession:
    def __init__(self, casos: list[Any] | None = None) -> None:
        self.query_obj = _FakeIngresosQuery(casos or [])

    def query(self, *entities: Any):
        return self.query_obj


def test_ingresos_sin_match_filtra_por_origen_coma_separado(monkeypatch):
    from web.app.main import app

    fake_session = _FakeIngresosSession()
    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(fake_session))

    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    response = client.get("/api/admin/infra/ingresos-sin-match?origen=excel_camaras,slack")

    assert response.status_code == 200
    assert len(fake_session.query_obj.filtros) == 1
    compiled = str(fake_session.query_obj.filtros[0].compile(compile_kwargs={"literal_binds": True}))
    assert "excel_camaras" in compiled
    assert "slack" in compiled
    assert "IN" in compiled.upper()


def test_ingresos_sin_match_sin_origen_no_filtra(monkeypatch):
    from web.app.main import app

    fake_session = _FakeIngresosSession()
    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(fake_session))

    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    response = client.get("/api/admin/infra/ingresos-sin-match")

    assert response.status_code == 200
    assert fake_session.query_obj.filtros == []
