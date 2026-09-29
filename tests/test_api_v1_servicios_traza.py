# Nombre de archivo: test_api_v1_servicios_traza.py
# Ubicación de archivo: tests/test_api_v1_servicios_traza.py
# Descripción: Tests HTTP de GET /api/v1/servicios/{servicio_id}/cables y /odfs (contrato, 404 y scopes)

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app import oauth
from api.app.main import app
from core.services.servicio_traza import OdfDelServicio, PosicionOdf, ResultadoTraza, ServicioResuelto
from db.session import get_async_db
from tests.soporte_oauth import SesionFalsa, hacer_cliente, override_con, secreto_firma  # noqa: F401

client = TestClient(app)
MODULO = "api.app.routes.v1.servicios"


@pytest.fixture
def sesion():
    s = SesionFalsa(hacer_cliente(), hacer_cliente("lf_cables", scopes=("cables:read",)))
    app.dependency_overrides[get_async_db] = override_con(s)
    try:
        yield s
    finally:
        app.dependency_overrides.pop(get_async_db, None)


def _auth(client_id: str = "lf_noc", scopes=("servicios:read",)) -> dict:
    return {"Authorization": f"Bearer {oauth.emitir_token(client_id, scopes)[0]}"}


def _resuelto(vigente: bool = False) -> ServicioResuelto:
    svc = MagicMock()
    svc.id, svc.servicio_id = 737, "120393"
    return ServicioResuelto(svc, es_id_vigente=vigente)


def test_cables_contrato(sesion) -> None:
    cables = ResultadoTraza(nombres=["F-MRT-001", "F-ATE-PANBB"], orden_fuente="traza_cromo")
    with patch(f"{MODULO}.resolver_servicio_por_identificador", AsyncMock(return_value=_resuelto())), patch(
        f"{MODULO}.cables_de_servicio", AsyncMock(return_value=cables)
    ):
        r = client.get("/api/v1/servicios/112763/cables", headers=_auth())

    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "servicio_consultado": "112763",
        "servicio_id_vigente": "120393",
        "es_id_vigente": False,
        "total_cables": 2,
        "cables": ["F-MRT-001", "F-ATE-PANBB"],
        "orden_fuente": "traza_cromo",
    }


def test_odfs_contrato(sesion) -> None:
    odfs = [
        OdfDelServicio(
            odf_n_id=6645370,
            nombre="ODF La Paz 1282 Rack 4",
            direccion="La Paz 1282",
            localidad="MARTINEZ",
            posiciones=[PosicionOdf("O-1261453-1", "3", "3"), PosicionOdf("O-1261453-1", "4", None)],
        )
    ]
    with patch(f"{MODULO}.resolver_servicio_por_identificador", AsyncMock(return_value=_resuelto(True))), patch(
        f"{MODULO}.odfs_de_servicio", AsyncMock(return_value=odfs)
    ):
        r = client.get("/api/v1/servicios/120393/odfs", headers=_auth())

    assert r.status_code == 200
    body = r.json()
    assert body["fuente"] == "cromo"
    assert body["es_id_vigente"] is True
    assert body["total_odfs"] == 1
    assert body["odfs"][0] == {
        "odf_id": 6645370,
        "nombre": "ODF La Paz 1282 Rack 4",
        "direccion": "La Paz 1282",
        "localidad": "MARTINEZ",
        "posiciones": [
            {"bandeja": "O-1261453-1", "conector": "3", "pelo": "3"},
            {"bandeja": "O-1261453-1", "conector": "4", "pelo": None},
        ],
    }


@pytest.mark.parametrize("recurso", ["botellas", "cables", "odfs"])
def test_servicio_inexistente_404(sesion, recurso: str) -> None:
    with patch(f"{MODULO}.resolver_servicio_por_identificador", AsyncMock(return_value=None)):
        r = client.get(f"/api/v1/servicios/999999/{recurso}", headers=_auth())
    assert r.status_code == 404
    assert r.json() == {"detail": "Servicio no encontrado"}


@pytest.mark.parametrize("recurso", ["botellas", "cables", "odfs"])
def test_scope_de_cables_no_abre_servicios(sesion, recurso: str) -> None:
    r = client.get(f"/api/v1/servicios/120393/{recurso}", headers=_auth("lf_cables", ("cables:read",)))
    assert r.status_code == 403


@pytest.mark.parametrize("recurso", ["cables", "odfs"])
def test_sin_token_401(sesion, recurso: str) -> None:
    assert client.get(f"/api/v1/servicios/120393/{recurso}").status_code == 401
