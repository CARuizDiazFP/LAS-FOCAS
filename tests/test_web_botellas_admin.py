# Nombre de archivo: test_web_botellas_admin.py
# Ubicación de archivo: tests/test_web_botellas_admin.py
# Descripción: Pruebas de wiring (auth/CSRF) de los endpoints admin de consolidación y export de inconsistencias de Botellas — sin DB real

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

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


class _FakeSyncSessionCtx:
    """Contexto `with SessionLocal() as session:` fake — para tests que mockean el servicio de
    dominio invocado dentro del bloque y no necesitan una sesión SQLAlchemy real (evita depender de
    una DB real disponible en el entorno de test)."""

    def __init__(self, session: MagicMock) -> None:
        self._session = session

    def __enter__(self) -> MagicMock:
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _fake_session_local(session: MagicMock):
    def _factory():
        return _FakeSyncSessionCtx(session)

    return _factory


# ── GET /api/admin/infra/botellas/viewer/duplicados ──────────────────────────


def test_viewer_duplicados_usa_cache_si_hay_hit(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())

    grupo_cacheado = []  # lista vacía es un hit válido — distinto de None

    async def _fake_leer_cache():
        return grupo_cacheado

    llamado = {"detectar": False}

    def _fake_detectar(session):
        llamado["detectar"] = True
        return []

    monkeypatch.setattr(web_main, "leer_cache_duplicados", _fake_leer_cache)
    monkeypatch.setattr(
        "core.services.botella_duplicados_service.detectar_grupos_duplicados_botellas", _fake_detectar
    )

    client = TestClient(app)
    _login(client, "admin", "adminpass")
    res = client.get("/api/admin/infra/botellas/viewer/duplicados")
    assert res.status_code == 200
    assert res.json()["grupos"] == []
    assert llamado["detectar"] is False, "no debió recalcular con un cache hit"


def test_viewer_duplicados_cache_miss_cae_a_computo_sincrono(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())

    async def _fake_leer_cache():
        return None

    guardado = {"grupos": "no_llamado"}

    async def _fake_guardar_cache(grupos):
        guardado["grupos"] = grupos

    llamado = {"detectar": False}

    def _fake_detectar(session):
        llamado["detectar"] = True
        return []

    monkeypatch.setattr(web_main, "leer_cache_duplicados", _fake_leer_cache)
    monkeypatch.setattr(web_main, "guardar_cache_duplicados", _fake_guardar_cache)
    monkeypatch.setattr(
        "core.services.botella_duplicados_service.detectar_grupos_duplicados_botellas", _fake_detectar
    )

    client = TestClient(app)
    _login(client, "admin", "adminpass")
    res = client.get("/api/admin/infra/botellas/viewer/duplicados")
    assert res.status_code == 200
    assert res.json()["grupos"] == []
    assert llamado["detectar"] is True, "un cache miss debe caer al cómputo síncrono"
    assert guardado["grupos"] == [], "el resultado fresco debe poblar la caché tras un miss"


def test_viewer_duplicados_refrescar_ignora_la_cache(monkeypatch):
    """`?refrescar=true` es la escotilla manual: ni siquiera intenta leer la caché, recalcula y
    repuebla. Cubre los escritores que NO invalidan (ingesta Cromo, baneos, merge de Cámaras,
    backfill) — ver docs/decisiones.md, entrada 2026-08-21 (cont.)."""
    from web.app import main as web_main

    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())

    llamado = {"leer_cache": False, "detectar": False}

    async def _fake_leer_cache():
        llamado["leer_cache"] = True
        return []  # un hit válido: si se leyera, se saltearía el cómputo

    guardado = {"grupos": "no_llamado"}

    async def _fake_guardar_cache(grupos):
        guardado["grupos"] = grupos

    def _fake_detectar(session):
        llamado["detectar"] = True
        return []

    monkeypatch.setattr(web_main, "leer_cache_duplicados", _fake_leer_cache)
    monkeypatch.setattr(web_main, "guardar_cache_duplicados", _fake_guardar_cache)
    monkeypatch.setattr(
        "core.services.botella_duplicados_service.detectar_grupos_duplicados_botellas", _fake_detectar
    )

    client = TestClient(app)
    _login(client, "admin", "adminpass")
    res = client.get("/api/admin/infra/botellas/viewer/duplicados?refrescar=true")
    assert res.status_code == 200
    assert res.json()["grupos"] == []
    assert llamado["leer_cache"] is False, "refrescar=true no debe ni intentar leer la caché"
    assert llamado["detectar"] is True, "refrescar=true debe forzar el cómputo síncrono"
    assert guardado["grupos"] == [], "el resultado fresco debe repoblar la caché"


def test_viewer_duplicados_refrescar_false_sigue_usando_la_cache(monkeypatch):
    """El default (y `?refrescar=false` explícito) no cambia: la caché manda."""
    from web.app import main as web_main

    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())

    llamado = {"leer_cache": False, "detectar": False}

    async def _fake_leer_cache():
        llamado["leer_cache"] = True
        return []

    def _fake_detectar(session):
        llamado["detectar"] = True
        return []

    monkeypatch.setattr(web_main, "leer_cache_duplicados", _fake_leer_cache)
    monkeypatch.setattr(
        "core.services.botella_duplicados_service.detectar_grupos_duplicados_botellas", _fake_detectar
    )

    client = TestClient(app)
    _login(client, "admin", "adminpass")
    res = client.get("/api/admin/infra/botellas/viewer/duplicados?refrescar=false")
    assert res.status_code == 200
    assert llamado["leer_cache"] is True
    assert llamado["detectar"] is False, "sin refrescar, un cache hit evita el cómputo"


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


def test_consolidar_exitoso_encola_recalculo_duplicados(monkeypatch):
    """Camino feliz completo: `consolidar_grupo_botellas` (mockeado) devuelve un resultado válido,
    la transacción se confirma y el endpoint encola exactamente un job de recálculo con un motivo
    no vacío antes de responder 200. `SessionLocal` se mockea para no depender de una DB real — la
    lógica de negocio de `consolidar_grupo_botellas` ya está cubierta a fondo en
    test_cromo_consolidacion_service.py, acá se verifica el wiring del endpoint."""
    from web.app import main as web_main
    from core.services.cromo.consolidacion_service import ResultadoConsolidacion

    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(MagicMock()))

    resultado = ResultadoConsolidacion(id_destino_cromo=999)
    monkeypatch.setattr(
        "core.services.cromo.consolidacion_service.consolidar_grupo_botellas",
        lambda session, **kwargs: resultado,
    )

    llamadas: list[str] = []

    async def _fake_encolar(motivo: str) -> None:
        llamadas.append(motivo)

    monkeypatch.setattr(web_main, "encolar_recalculo_duplicados_botellas", _fake_encolar)

    client = TestClient(app)
    _login(client, "admin", "adminpass")
    res = client.post(
        "/api/infra/botellas/consolidar",
        json={"id_destino_cromo": 999, "ids_origen_cromo": [100], "csrf_token": "cualquiera"},
    )
    assert res.status_code == 200
    assert len(llamadas) == 1
    assert llamadas[0], "el motivo no debe quedar vacío"
    assert "consolidar" in llamadas[0]


def test_consolidar_fallido_no_encola_recalculo_duplicados(monkeypatch):
    """Si `consolidar_grupo_botellas` lanza su excepción de validación (400), la sesión hace
    rollback y el endpoint NUNCA debe encolar un recálculo — no hubo mutación confirmada."""
    from web.app import main as web_main
    from core.services.cromo.consolidacion_service import ConsolidacionBotellaError

    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(MagicMock()))

    def _fake_consolidar(session, **kwargs):
        raise ConsolidacionBotellaError("No existe una Botella Cromo con n_id=999.")

    monkeypatch.setattr(
        "core.services.cromo.consolidacion_service.consolidar_grupo_botellas", _fake_consolidar
    )

    llamadas: list[str] = []

    async def _fake_encolar(motivo: str) -> None:
        llamadas.append(motivo)

    monkeypatch.setattr(web_main, "encolar_recalculo_duplicados_botellas", _fake_encolar)

    client = TestClient(app)
    _login(client, "admin", "adminpass")
    res = client.post(
        "/api/infra/botellas/consolidar",
        json={"id_destino_cromo": 999, "ids_origen_cromo": [100], "csrf_token": "cualquiera"},
    )
    assert res.status_code == 400
    assert llamadas == []


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


def test_eliminar_botella_exitoso_encola_recalculo_duplicados(monkeypatch):
    """Camino feliz: `eliminar_botella` (mockeado) devuelve un resultado válido, se confirma la
    transacción y el endpoint encola exactamente un job de recálculo con motivo no vacío antes de
    responder 200."""
    from web.app import main as web_main
    from core.services.camara_botella_delete_service import ResultadoEliminacionBotella

    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(MagicMock()))

    resultado = ResultadoEliminacionBotella(
        origen="cromo", id=100, camara_padre_eliminada=None, alias_registrado=True
    )
    monkeypatch.setattr(
        "core.services.camara_botella_delete_service.eliminar_botella",
        lambda session, **kwargs: resultado,
    )

    llamadas: list[str] = []

    async def _fake_encolar(motivo: str) -> None:
        llamadas.append(motivo)

    monkeypatch.setattr(web_main, "encolar_recalculo_duplicados_botellas", _fake_encolar)

    client = TestClient(app)
    _login(client, "admin", "adminpass")
    res = client.post(
        "/api/infra/botellas/eliminar",
        json={"origen": "cromo", "id": 100, "csrf_token": "cualquiera"},
    )
    assert res.status_code == 200
    assert len(llamadas) == 1
    assert llamadas[0], "el motivo no debe quedar vacío"
    assert "eliminar" in llamadas[0]


def test_eliminar_botella_fallido_no_encola_recalculo_duplicados(monkeypatch):
    """Si `eliminar_botella` lanza `EliminacionBloqueadaError` (400, hay datos reales asociados),
    la sesión hace rollback y el endpoint NUNCA debe encolar un recálculo."""
    from web.app import main as web_main
    from core.services.camara_botella_delete_service import EliminacionBloqueadaError

    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setattr(web_main.psycopg, "connect", _connect_admin_ok())
    monkeypatch.setattr("db.session.SessionLocal", _fake_session_local(MagicMock()))

    def _fake_eliminar(session, **kwargs):
        raise EliminacionBloqueadaError("Tiene Cables asociados", [])

    monkeypatch.setattr(
        "core.services.camara_botella_delete_service.eliminar_botella", _fake_eliminar
    )

    llamadas: list[str] = []

    async def _fake_encolar(motivo: str) -> None:
        llamadas.append(motivo)

    monkeypatch.setattr(web_main, "encolar_recalculo_duplicados_botellas", _fake_encolar)

    client = TestClient(app)
    _login(client, "admin", "adminpass")
    res = client.post(
        "/api/infra/botellas/eliminar",
        json={"origen": "cromo", "id": 100, "csrf_token": "cualquiera"},
    )
    assert res.status_code == 400
    assert llamadas == []


# ── POST /api/infra/camaras/eliminar ─────────────────────────────────────────


def test_eliminar_camara_requiere_autenticacion():
    client = TestClient(app)
    res = client.post("/api/infra/camaras/eliminar", json={"camara_id": 1})
    assert res.status_code == 401
