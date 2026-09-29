# Nombre de archivo: test_api_v1_cables.py
# Ubicación de archivo: tests/test_api_v1_cables.py
# Descripción: Tests HTTP de GET /api/v1/cables/servicios y /api/v1/cables/pelos (contrato, 404/409, validación y scopes)

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app import oauth
from api.app.main import app
from core.services.cable_consultas import BufferDeCable, CableIdentificado, PeloEnBuffer, ServicioEnCable
from db.session import get_async_db
from tests.soporte_oauth import SesionFalsa, hacer_cliente, override_con, secreto_firma  # noqa: F401

client = TestClient(app)
MODULO = "api.app.routes.v1.cables"
CABLE = CableIdentificado(6605471, "F-MRT-001", "144", "Nodo Atento - Rack 1", "Bot 1 Velez Sarfield 2551 MARTINEZ")


@pytest.fixture
def sesion():
    s = SesionFalsa(hacer_cliente("lf_cables", scopes=("cables:read",)), hacer_cliente())
    app.dependency_overrides[get_async_db] = override_con(s)
    try:
        yield s
    finally:
        app.dependency_overrides.pop(get_async_db, None)


def _auth(client_id: str = "lf_cables", scopes=("cables:read",)) -> dict:
    return {"Authorization": f"Bearer {oauth.emitir_token(client_id, scopes)[0]}"}


def _resolver(*candidatos):
    return patch(f"{MODULO}.resolver_cable", AsyncMock(return_value=list(candidatos)))


def test_servicios_contrato(sesion) -> None:
    servicios = [ServicioEnCable("54225", "TELEVISION FEDERAL S A", "Activo", "TLS", 2, [1])]
    with _resolver(CABLE), patch(f"{MODULO}.servicios_de_cable", AsyncMock(return_value=servicios)) as m:
        r = client.get("/api/v1/cables/servicios", params={"cable": "f-mrt-001"}, headers=_auth())

    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "cable": {
            "cable_id": 6605471,
            "nombre": "F-MRT-001",
            "capacidad": "144",
            "extremo_a": "Nodo Atento - Rack 1",
            "extremo_b": "Bot 1 Velez Sarfield 2551 MARTINEZ",
        },
        "total_servicios": 1,
        "servicios": [
            {
                "servicio_id": "54225",
                "cliente": "TELEVISION FEDERAL S A",
                "estado_servicio": "Activo",
                "tipo_servicio": "TLS",
                "cantidad_pelos": 2,
                "buffers": [1],
            }
        ],
    }
    assert m.await_args.args[1] == 6605471


def test_pelos_contrato_con_filtro_de_buffer(sesion) -> None:
    buffers = [
        BufferDeCable(
            numero=2,
            color="NR",
            pelos=[
                PeloEnBuffer("1", "AZ", "ocupado", "120393", "ESPN SUR SRL", "Activo", "DWDM La Paz 1282 - P1"),
                PeloEnBuffer("2", "NR", "libre", None, None, None, None),
            ],
        )
    ]
    with _resolver(CABLE), patch(f"{MODULO}.pelos_por_buffer", AsyncMock(return_value=buffers)) as m:
        r = client.get("/api/v1/cables/pelos", params={"cable": "F-MRT-001", "buffer": 2}, headers=_auth())

    assert r.status_code == 200
    body = r.json()
    assert body["total_buffers"] == 1
    assert body["buffers"][0]["numero"] == 2
    assert body["buffers"][0]["total_pelos"] == 2
    assert body["buffers"][0]["pelos_ocupados"] == 1
    assert body["buffers"][0]["pelos"][1] == {
        "numero": "2",
        "color": "NR",
        "estado": "libre",
        "servicio_id": None,
        "cliente": None,
        "estado_servicio": None,
        "descripcion": None,
    }
    assert m.await_args.kwargs == {"buffer": 2}


def test_nombre_con_espacios_y_parentesis_se_acepta(sesion) -> None:
    with _resolver(CABLE) as m, patch(f"{MODULO}.servicios_de_cable", AsyncMock(return_value=[])):
        r = client.get("/api/v1/cables/servicios", params={"cable": "F-VIN-JDG (a instalar)"}, headers=_auth())
    assert r.status_code == 200
    assert m.await_args.args[1] == "F-VIN-JDG (a instalar)"


@pytest.mark.parametrize("ruta", ["servicios", "pelos"])
def test_cable_inexistente_404(sesion, ruta: str) -> None:
    with _resolver():
        r = client.get(f"/api/v1/cables/{ruta}", params={"cable": "NOEXISTE"}, headers=_auth())
    assert r.status_code == 404
    assert r.json() == {"detail": "Cable no encontrado"}


@pytest.mark.parametrize("ruta", ["servicios", "pelos"])
def test_nombre_ambiguo_409_con_candidatos(sesion, ruta: str) -> None:
    otro = CableIdentificado(10260935, "F-LEM-11-A", None, "Cra Est. Lemos", None)
    uno = CableIdentificado(9498169, "F-LEM-11-A", None, "Cra. Est. Lemos Bot. 2", None)
    with _resolver(uno, otro):
        r = client.get(f"/api/v1/cables/{ruta}", params={"cable": "F-LEM-11-A"}, headers=_auth())
    assert r.status_code == 409
    assert [c["cable_id"] for c in r.json()["candidatos"]] == [9498169, 10260935]


def test_buffer_inexistente_404(sesion) -> None:
    with _resolver(CABLE), patch(f"{MODULO}.pelos_por_buffer", AsyncMock(return_value=[])):
        r = client.get("/api/v1/cables/pelos", params={"cable": "F-MRT-001", "buffer": 40}, headers=_auth())
    assert r.status_code == 404
    assert "buffer 40" in r.json()["detail"]


@pytest.mark.parametrize(
    "params",
    [{}, {"cable": ""}, {"cable": "x" * 129}, {"cable": "F-MRT\n001"}, {"cable": "F-MRT-001", "buffer": 0}],
    ids=["sin_cable", "vacio", "muy_largo", "control", "buffer_cero"],
)
def test_parametros_invalidos_422(sesion, params: dict) -> None:
    with _resolver(CABLE) as m:
        r = client.get("/api/v1/cables/pelos", params=params, headers=_auth())
    assert r.status_code == 422
    m.assert_not_awaited()


@pytest.mark.parametrize("ruta", ["servicios", "pelos"])
def test_scope_de_servicios_no_abre_cables(sesion, ruta: str) -> None:
    r = client.get(f"/api/v1/cables/{ruta}", params={"cable": "F-MRT-001"}, headers=_auth("lf_noc", ("servicios:read",)))
    assert r.status_code == 403


@pytest.mark.parametrize("ruta", ["servicios", "pelos"])
def test_sin_token_401(sesion, ruta: str) -> None:
    assert client.get(f"/api/v1/cables/{ruta}", params={"cable": "F-MRT-001"}).status_code == 401
