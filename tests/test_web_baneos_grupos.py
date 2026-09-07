# Nombre de archivo: test_web_baneos_grupos.py
# Ubicación de archivo: tests/test_web_baneos_grupos.py
# Descripción: Pruebas de ruta HTTP para los endpoints GET /api/admin/baneos/grupos y
# POST /api/admin/baneos/grupos/liberar (hallazgo Important de la revisión final del plan de
# refactor de baneos: sólo 2 de los 4 endpoints nuevos tenían cobertura de 403/400 — faltaban estos 2)

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from core.password import hash_password


# ── Helpers compartidos de login/sesión (mismo patrón que test_web_ingest_camaras.py,
# test_web_infra_camera_state.py y test_web_botellas_admin.py: mock de psycopg.connect para no
# depender de una DB real) ────────────────────────────────────────────────────────────────────────


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


# ── GET /api/admin/baneos/grupos ────────────────────────────────────────────────────────────────


def test_baneos_grupos_listar_sin_admin_devuelve_403(monkeypatch):
    from web.app.main import app

    client = TestClient(app)
    _login(client, monkeypatch, role="user", password="userpass")

    response = client.get("/api/admin/baneos/grupos")

    assert response.status_code == 403


# ── POST /api/admin/baneos/grupos/liberar ───────────────────────────────────────────────────────


def test_baneos_grupos_liberar_sin_admin_devuelve_403(monkeypatch):
    from web.app.main import app

    client = TestClient(app)
    _login(client, monkeypatch, role="user", password="userpass")

    response = client.post(
        "/api/admin/baneos/grupos/liberar",
        json={"camara_ids": [1], "motivo": "prueba"},
    )

    assert response.status_code == 403


def test_baneos_grupos_liberar_csrf_invalido_devuelve_403(monkeypatch):
    from web.app.main import app

    # Workaround explícito ya usado en test_web_ingest_camaras.py/test_web_infra_camera_state.py:
    # otro módulo de test puede haber dejado TESTING=true en el proceso, lo que saltearía el chequeo.
    monkeypatch.setenv("TESTING", "false")
    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    response = client.post(
        "/api/admin/baneos/grupos/liberar",
        json={"camara_ids": [1], "motivo": "prueba", "csrf_token": "invalido"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "CSRF inválido"


def test_baneos_grupos_liberar_camara_ids_vacio_devuelve_400(monkeypatch):
    from web.app.main import app

    monkeypatch.setenv("TESTING", "true")
    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    response = client.post(
        "/api/admin/baneos/grupos/liberar",
        json={"camara_ids": [], "motivo": "prueba", "csrf_token": "cualquiera"},
    )

    assert response.status_code == 400


def test_baneos_grupos_liberar_motivo_vacio_devuelve_400(monkeypatch):
    from web.app.main import app

    monkeypatch.setenv("TESTING", "true")
    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    response = client.post(
        "/api/admin/baneos/grupos/liberar",
        json={"camara_ids": [1], "motivo": "   ", "csrf_token": "cualquiera"},
    )

    assert response.status_code == 400


def test_baneos_grupos_liberar_motivo_ausente_devuelve_400(monkeypatch):
    """`motivo` es obligatorio en el schema (sin default) — omitirlo devuelve 422 de validación de
    Pydantic, no el 400 de negocio. Cubre el caso explícito de "vacío/sólo espacios" (400 de negocio)
    y documenta, aparte, que la ausencia total del campo es un error distinto (422)."""
    from web.app.main import app

    monkeypatch.setenv("TESTING", "true")
    client = TestClient(app)
    _login(client, monkeypatch, role="admin", password="admin")

    response = client.post(
        "/api/admin/baneos/grupos/liberar",
        json={"camara_ids": [1], "csrf_token": "cualquiera"},
    )

    assert response.status_code == 422
