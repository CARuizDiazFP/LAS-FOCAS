# Nombre de archivo: test_servicios_prov_routes.py
# Ubicación de archivo: tests/test_servicios_prov_routes.py
# Descripción: Tests de integración del endpoint de refresco on-demand desde PROV y de la extensión de GET /servicios/detail con historial_ids/equipos_ultima_milla

from __future__ import annotations

import logging
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

# Namespace de IDs reservado para estos tests. Se eligió el rango de 6 dígitos 9001xx tras
# confirmar contra la DB de dev que no existe ninguna fila con `servicio_id`/`numero_linea`/
# `numero_primer_servicio` ahí (las únicas 9001* reales son de 5 dígitos: 90011/90014/90016/90018),
# para que la cadena de upgrades de los tests no choque por accidente con un servicio real.
_NUMEROS_DE_TEST = ("900101", "900102", "900103", "900104", "900105", "900107", "900108")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _limpiar_servicios_de_test():
    yield
    with SessionLocal() as session:
        # También por `servicio_id`: el refresco desde PROV puede avanzar el `servicio_id` de una
        # fila de test a otro ID del namespace (una cadena de upgrades), y esa fila hay que
        # borrarla igual para no dejar el ID ocupado para el test siguiente.
        session.execute(
            text(
                "DELETE FROM app.servicios "
                "WHERE numero_primer_servicio = ANY(:numeros ::varchar[]) "
                "   OR servicio_id = ANY(:numeros ::varchar[])"
            ),
            {"numeros": list(_NUMEROS_DE_TEST)},
        )
        session.commit()


def _crear_servicio(numero: str, servicio_id: str | None = None) -> None:
    """Crea un Servicio de test. `servicio_id` distinto de `numero` sirve para armar una fila que
    ya ocupe un ID que otra fila va a querer reclamar (test de colisión)."""
    with SessionLocal() as session:
        session.execute(
            text(
                "INSERT INTO app.servicios "
                "(servicio_id, numero_primer_servicio, numero_linea, estado_servicio, tipo_servicio, origen_datos) "
                "VALUES (:servicio_id, :numero, :numero, 'DESCONOCIDO', 'EWS', 'MANUAL'::app.servicio_origen_datos)"
            ),
            {"numero": numero, "servicio_id": servicio_id or numero},
        )
        session.commit()


def _leer_identidad(numero_primer_servicio: str) -> tuple[str, str | None, list[str]]:
    """Lee `(servicio_id, numero_linea, alias_ids)` reales de la DB — `ServicioItemResponse` no
    expone `servicio_id`, así que la aserción sobre el campo con índice UNIQUE tiene que ir a la
    tabla."""
    with SessionLocal() as session:
        fila = session.execute(
            text(
                "SELECT servicio_id, numero_linea, alias_ids FROM app.servicios "
                "WHERE numero_primer_servicio = :numero"
            ),
            {"numero": numero_primer_servicio},
        ).one()
        return fila[0], fila[1], list(fila[2] or [])


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


def _contexto_con_cadena(*, vigente: str, intermedio: str, original: str) -> dict:
    """Payload con la MISMA forma que el caso real verificado en el diseño (`nro_servicio=15872` →
    vigente `63871`, intermedio `46215`), con IDs del namespace de test."""
    return {
        "id_servicio": "EWS",
        "nro_servicio": vigente,
        "nro_servicio_original": original,
        "nro_servicio_consultado": original,
        "nro_servicio_vigente": vigente,
        "fue_upgradeado": True,
        "estado_comercial": "INSTALADO",
        "Descripcion": "CLIENTE CON CADENA SA",
        "Direccion1": "AYACUCHO 652",
        "Provincia1": "Capital Federal",
        "Nodo1": "NODO-CADENA",
        "Equipo1": "SW-CADENA",
        "Port1": "6",
        "cadena_upgrade": [
            {
                "nro_servicio": vigente,
                "estado_comercial": "INSTALADO",
                "fecha_instalacion": "2019-11-01",
                "fecha_baja": None,
                "motivo_baja": "",
                "es_vigente": True,
            },
            {
                "nro_servicio": intermedio,
                "estado_comercial": "DADO BAJA",
                "fecha_instalacion": "2017-11-23",
                "fecha_baja": "2019-11-01",
                "motivo_baja": "UPGRADE",
                "es_vigente": False,
            },
            {
                "nro_servicio": original,
                "estado_comercial": "DADO BAJA",
                "fecha_instalacion": "2012-04-23",
                "fecha_baja": "2017-11-23",
                "motivo_baja": "UPGRADE",
                "es_vigente": False,
            },
        ],
    }


def test_refrescar_avanza_la_identidad_cuando_la_cadena_trae_un_id_vigente_mas_alto(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ejercita de punta a punta la consolidación de identidad con una cadena de 3 eslabones: el
    `servicio_id` de la fila TIENE que avanzar al vigente y los otros dos IDs quedar como alias."""
    _crear_servicio("900101")
    contexto = _contexto_con_cadena(vigente="900107", intermedio="900104", original="900101")
    monkeypatch.setattr(servicios_routes, "get_prov_client", lambda: _ClientePROVFalso(contexto=contexto))

    response = client.post("/servicios/prov/refrescar", params={"id": "900101"}, headers=API_HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["servicio"]["numero_linea"] == "900107"
    assert sorted(body["servicio"]["alias_ids"]) == ["900101", "900104"]
    assert [item["numero_id"] for item in body["historial_ids"]] == ["900107", "900104", "900101"]
    assert body["historial_ids"][0]["es_vigente"] is True
    assert body["historial_ids"][0]["fecha_instalacion"] == "2019-11-01"
    assert body["historial_ids"][2]["fecha_baja"] == "2017-11-23"

    servicio_id, numero_linea, alias_ids = _leer_identidad("900101")
    assert servicio_id == "900107"
    assert numero_linea == "900107"
    assert sorted(alias_ids) == ["900101", "900104"]


def test_refrescar_no_pisa_un_servicio_id_que_ya_ocupa_otra_fila(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`app.servicios.servicio_id` tiene índice UNIQUE: si otra fila ya ocupa el ID vigente que
    PROV reporta, el refresco se degrada (conserva su `servicio_id`, baja el rechazado a alias) en
    vez de reventar con `IntegrityError`/500. Nunca se fusionan dos filas reales sin confirmación
    humana."""
    _crear_servicio("900108", servicio_id="900107")  # esta fila ya ocupa el ID vigente de PROV
    _crear_servicio("900104")
    contexto = _contexto_con_cadena(vigente="900107", intermedio="900105", original="900104")
    monkeypatch.setattr(servicios_routes, "get_prov_client", lambda: _ClientePROVFalso(contexto=contexto))

    with caplog.at_level(logging.WARNING, logger="core.services.prov.ingesta"):
        response = client.post("/servicios/prov/refrescar", params={"id": "900104"}, headers=API_HEADERS)

    assert response.status_code == 200, response.text
    assert "servicio_id_colision_no_fusionable" in caplog.text

    body = response.json()
    assert body["servicio"]["numero_linea"] == "900107"
    assert sorted(body["servicio"]["alias_ids"]) == ["900105", "900107"]
    # El historial y los equipos se escriben igual: la degradación es sólo de identidad.
    assert [item["numero_id"] for item in body["historial_ids"]] == ["900107", "900105", "900104"]

    servicio_id, numero_linea, alias_ids = _leer_identidad("900104")
    assert servicio_id == "900104", "no debe robarle el servicio_id a la otra fila"
    assert numero_linea == "900107", "numero_linea no tiene UNIQUE: sí avanza al vigente"
    assert "900107" in alias_ids, "el ID rechazado tiene que quedar como alias"
    assert "900104" not in alias_ids, "el ID conservado no figura como su propio alias"

    servicio_id_ocupante, _, _ = _leer_identidad("900108")
    assert servicio_id_ocupante == "900107", "la fila que ya ocupaba el ID queda intacta"


def test_detail_incluye_listas_vacias_cuando_no_hay_historial_ni_equipos(client: TestClient) -> None:
    _crear_servicio("900103")
    detail = client.get("/servicios/detail", params={"id": "900103"}, headers=API_HEADERS)
    assert detail.status_code == 200
    body = detail.json()
    assert body["historial_ids"] == []
    assert body["equipos_ultima_milla"] == []
