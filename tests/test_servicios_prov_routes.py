# Nombre de archivo: test_servicios_prov_routes.py
# Ubicación de archivo: tests/test_servicios_prov_routes.py
# Descripción: Tests de integración del endpoint de refresco on-demand desde PROV y de la extensión de GET /servicios/detail con historial_ids/equipos_ultima_milla

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import api.app.routes.servicios as servicios_routes
from api.app.main import app
from core.services.prov.client import ProvServicioNoEncontradoError
from db.session import SessionLocal

API_HEADERS = {"Authorization": "Bearer test-api-key"}

pytestmark = pytest.mark.skipif(
    os.getenv("CI") == "true",
    reason="requiere Postgres real alcanzable; el workflow de CI no tiene ese servicio configurado",
)

_NUMEROS_DE_TEST = ("900101", "900102", "900103")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _limpiar_servicios_de_test():
    yield
    with SessionLocal() as session:
        session.execute(
            text("DELETE FROM app.servicios WHERE numero_primer_servicio = ANY(:numeros ::varchar[])"),
            {"numeros": list(_NUMEROS_DE_TEST)},
        )
        session.commit()


def _crear_servicio(numero: str) -> None:
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO app.servicios "
                "(servicio_id, numero_primer_servicio, numero_linea, estado_servicio, tipo_servicio, origen_datos) "
                "VALUES (:numero, :numero, :numero, 'DESCONOCIDO', 'EWS', 'MANUAL'::app.servicio_origen_datos)"
            ),
            {"numero": numero},
        )
        session.commit()


class _ClientePROVFalso:
    def __init__(self, contexto: dict | None = None, error: Exception | None = None) -> None:
        self._contexto = contexto
        self._error = error

    async def obtener_contexto_servicio(self, nro_servicio: str) -> dict:
        if self._error:
            raise self._error
        return self._contexto


def test_refrescar_persiste_historial_y_equipos_de_una_cadena_de_upgrades(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _crear_servicio("900101")

    contexto = {
        "nro_servicio": "900101",
        "nro_servicio_original": "900101",
        "id_servicio": "EWS",
        "Descripcion": "CLIENTE DE PRUEBA SA",
        "estado_comercial": "INSTALADO",
        "Nodo1": "NODO-TEST",
        "Equipo1": "SW-TEST",
        "Port1": "1",
        "Direccion1": "CALLE FALSA 123",
        "Provincia1": "Buenos Aires",
        "cadena_upgrade": [
            {
                "nro_servicio": "900101",
                "estado_comercial": "INSTALADO",
                "fecha_instalacion": "2020-01-01",
                "fecha_baja": None,
                "motivo_baja": "",
                "es_vigente": True,
            }
        ],
    }
    monkeypatch.setattr(servicios_routes, "get_prov_client", lambda: _ClientePROVFalso(contexto=contexto))

    response = client.post("/servicios/prov/refrescar", params={"id": "900101"}, headers=API_HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["servicio"]["estado_servicio"] == "Activo"
    assert body["servicio"]["nombre_cliente"] == "CLIENTE DE PRUEBA SA"
    assert len(body["historial_ids"]) == 1
    assert body["historial_ids"][0]["numero_id"] == "900101"
    assert body["historial_ids"][0]["estado_comercial"] == "INSTALADO"
    assert len(body["equipos_ultima_milla"]) == 1
    assert body["equipos_ultima_milla"][0]["nodo"] == "NODO-TEST"

    detail = client.get("/servicios/detail", params={"id": "900101"}, headers=API_HEADERS)
    assert len(detail.json()["historial_ids"]) == 1


def test_refrescar_devuelve_404_logico_cuando_prov_no_tiene_contexto(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _crear_servicio("900102")
    monkeypatch.setattr(
        servicios_routes,
        "get_prov_client",
        lambda: _ClientePROVFalso(
            error=ProvServicioNoEncontradoError("900102", "No hay contexto para el número de servicio ingresado")
        ),
    )

    response = client.post("/servicios/prov/refrescar", params={"id": "900102"}, headers=API_HEADERS)
    assert response.status_code == 404
    assert "900102" in response.json()["detail"]


def test_refrescar_404_si_el_servicio_no_existe_en_la_db(client: TestClient) -> None:
    response = client.post("/servicios/prov/refrescar", params={"id": "900103-inexistente"}, headers=API_HEADERS)
    assert response.status_code == 404


def test_detail_incluye_listas_vacias_cuando_no_hay_historial_ni_equipos(client: TestClient) -> None:
    _crear_servicio("900103")
    detail = client.get("/servicios/detail", params={"id": "900103"}, headers=API_HEADERS)
    assert detail.status_code == 200
    body = detail.json()
    assert body["historial_ids"] == []
    assert body["equipos_ultima_milla"] == []
