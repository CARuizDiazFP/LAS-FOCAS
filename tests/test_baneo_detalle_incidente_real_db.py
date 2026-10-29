# Nombre de archivo: test_baneo_detalle_incidente_real_db.py
# Ubicación de archivo: tests/test_baneo_detalle_incidente_real_db.py
# Descripción: GET /api/infra/ban/{id} en la API y en el panel contra focas_dev, sólo lectura (P24)

"""El detalle del incidente (con la plantilla guardada del aviso) existía sólo en la API; desde P24 el
panel lo sirve con la misma función de `core/services/baneo_aviso.py`. Estos tests fijan que las dos
apps devuelven el mismo cuerpo, el 404 de un id inexistente y que la ruta del panel no le gana a
`/ban/active`. Sólo hacen SELECT."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.app.main import app as app_api
from core.services.baneo_aviso import detalle_incidente_baneo
from db.session import SessionLocal
from tests.soporte_postgres_real import requiere_postgres_real
from web.app.main import app as app_web

pytestmark = requiere_postgres_real

ID_INEXISTENTE = 999999999
CLAVES = {
    "id", "ticket", "servicio_afectado", "servicio_protegido", "email_subject", "email_body",
    "cantidad_camaras",
}


@pytest.fixture
def web(con_sesion) -> TestClient:
    con_sesion("admin")
    return TestClient(app_web)


@pytest.fixture
def api() -> TestClient:
    return TestClient(app_api, headers={"Authorization": "Bearer test-api-key"})


@pytest.fixture(scope="module")
def incidente_id() -> int:
    """Id real de focas_dev, con plantilla guardada si hay alguno; salteado si no hay incidentes."""
    with SessionLocal() as session:
        fila = session.execute(text(
            "SELECT id FROM app.incidentes_baneo ORDER BY (email_subject IS NULL), id LIMIT 1"
        )).first()
    if fila is None:
        pytest.skip("focas_dev sin incidentes de baneo")
    return fila[0]


def test_servicio_devuelve_el_detalle(incidente_id):
    with SessionLocal() as session:
        detalle = detalle_incidente_baneo(session, incidente_id)
        fila = session.execute(
            text("SELECT ticket_asociado, email_subject, email_body FROM app.incidentes_baneo WHERE id = :id"),
            {"id": incidente_id},
        ).one()
    assert detalle is not None
    assert set(detalle) == CLAVES
    assert detalle["id"] == incidente_id
    assert (detalle["ticket"], detalle["email_subject"], detalle["email_body"]) == tuple(fila)
    assert isinstance(detalle["cantidad_camaras"], int)


def test_servicio_none_si_no_existe():
    with SessionLocal() as session:
        assert detalle_incidente_baneo(session, ID_INEXISTENTE) is None


def test_web_y_api_devuelven_el_mismo_detalle(web, api, incidente_id):
    res_web = web.get(f"/api/infra/ban/{incidente_id}")
    res_api = api.get(f"/api/infra/ban/{incidente_id}")
    assert res_web.status_code == res_api.status_code == 200
    assert set(res_web.json()) == CLAVES
    assert res_web.json() == res_api.json()


def test_web_404_si_no_existe(web):
    res = web.get(f"/api/infra/ban/{ID_INEXISTENTE}")
    assert res.status_code == 404
    assert "no encontrado" in res.json()["error"]


def test_api_404_si_no_existe(api):
    assert api.get(f"/api/infra/ban/{ID_INEXISTENTE}").status_code == 404


def test_web_ban_active_no_lo_captura_el_detalle(web):
    res = web.get("/api/infra/ban/active")
    assert res.status_code == 200
    assert "incidentes" in res.json()


def test_web_detalle_exige_sesion(con_sesion):
    con_sesion(None)
    assert TestClient(app_web).get("/api/infra/ban/1").status_code == 401
