# Nombre de archivo: test_web_cromo_separar_padre.py
# Ubicación de archivo: tests/test_web_cromo_separar_padre.py
# Descripción: Pruebas de wiring (auth/admin/CSRF) del endpoint de separación de Botella Cromo de su Cámara padre — sin DB real

from __future__ import annotations


from fastapi.testclient import TestClient  # type: ignore

from tests.soporte_login import (
    connect_admin_ok,
    connect_user_ok,
    login,
)
from web.app.main import app

BOTELLA_N_ID = 9057909


def test_separar_padre_requiere_autenticacion():
    client = TestClient(app)
    res = client.post(
        f"/api/infra/botellas/{BOTELLA_N_ID}/separar-padre",
        json={"nombre": "Nuevo", "motivo": "test"},
    )
    assert res.status_code == 401


def test_separar_padre_rechaza_no_admin(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", connect_user_ok())
    client = TestClient(app)
    login(client, "user", "userpass")

    res = client.post(
        f"/api/infra/botellas/{BOTELLA_N_ID}/separar-padre",
        json={"nombre": "Nuevo", "motivo": "test"},
    )
    assert res.status_code == 403


def test_separar_padre_rechaza_csrf_invalido(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setenv("TESTING", "false")  # ver nota en test_web_botellas_admin.py
    monkeypatch.setattr(web_main.psycopg, "connect", connect_admin_ok())
    client = TestClient(app)
    login(client, "admin", "adminpass")

    res = client.post(
        f"/api/infra/botellas/{BOTELLA_N_ID}/separar-padre",
        json={"nombre": "Nuevo", "motivo": "test", "csrf_token": "invalido"},
    )
    assert res.status_code == 403


def test_separar_padre_404_si_no_existe(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", connect_admin_ok())

    class _SessionLocalFake:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def rollback(self):
            return None

        def commit(self):
            return None

    monkeypatch.setattr("db.session.SessionLocal", lambda: _SessionLocalFake())
    client = TestClient(app)
    csrf = login(client, "admin", "adminpass")

    import core.services.cromo.separacion_service as separacion_service

    def _rompe(*args, **kwargs):
        raise separacion_service.BotellaNoEncontradaError(f"No existe una Botella Cromo con n_id={BOTELLA_N_ID}.")

    monkeypatch.setattr(web_main, "separar_botella_de_padre", _rompe, raising=False)
    monkeypatch.setattr(separacion_service, "separar_botella_de_padre", _rompe)

    res = client.post(
        f"/api/infra/botellas/{BOTELLA_N_ID}/separar-padre",
        json={"nombre": "Nuevo", "motivo": "test", "csrf_token": csrf},
    )
    assert res.status_code == 404


def test_separar_padre_400_si_colisiona(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", connect_admin_ok())

    class _SessionLocalFake:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def rollback(self):
            return None

        def commit(self):
            return None

    monkeypatch.setattr("db.session.SessionLocal", lambda: _SessionLocalFake())
    client = TestClient(app)
    csrf = login(client, "admin", "adminpass")

    import core.services.cromo.separacion_service as separacion_service

    def _rompe(*args, **kwargs):
        raise separacion_service.SeparacionBotellaError('El nombre "Nuevo" ya lo usa otra Cámara.')

    monkeypatch.setattr(separacion_service, "separar_botella_de_padre", _rompe)

    res = client.post(
        f"/api/infra/botellas/{BOTELLA_N_ID}/separar-padre",
        json={"nombre": "Nuevo", "motivo": "test", "csrf_token": csrf},
    )
    assert res.status_code == 400


def test_separar_padre_happy_path(monkeypatch):
    from web.app import main as web_main

    monkeypatch.setattr(web_main.psycopg, "connect", connect_admin_ok())

    class _SessionLocalFake:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def rollback(self):
            return None

        def commit(self):
            return None

    monkeypatch.setattr("db.session.SessionLocal", lambda: _SessionLocalFake())
    client = TestClient(app)
    csrf = login(client, "admin", "adminpass")

    import core.services.cromo.separacion_service as separacion_service

    def _resultado_fake(session, *, botella_n_id, nombre, motivo, usuario):
        return separacion_service.ResultadoSeparacion(
            botella_n_id=botella_n_id, camara_anterior_id=31967, camara_nueva_id=99999, camara_nueva_nombre=nombre
        )

    monkeypatch.setattr(separacion_service, "separar_botella_de_padre", _resultado_fake)

    res = client.post(
        f"/api/infra/botellas/{BOTELLA_N_ID}/separar-padre",
        json={"nombre": "B2-FO-CAR (separada)", "motivo": "agrupada por error de nombre", "csrf_token": csrf},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    assert payload["botella_n_id"] == BOTELLA_N_ID
    assert payload["camara_anterior_id"] == 31967
    assert payload["camara_nueva_id"] == 99999
    assert payload["camara_nueva_nombre"] == "B2-FO-CAR (separada)"
