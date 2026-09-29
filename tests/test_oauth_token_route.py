# Nombre de archivo: test_oauth_token_route.py
# Ubicación de archivo: tests/test_oauth_token_route.py
# Descripción: Tests HTTP del token endpoint OAuth2 client_credentials (POST /api/v1/oauth/token)

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from api.app import oauth
from api.app.main import app
from db.session import get_async_db
from tests.soporte_oauth import CLIENT_SECRET, SesionFalsa, hacer_cliente, override_con, secreto_firma  # noqa: F401

client = TestClient(app)
URL = "/api/v1/oauth/token"


@pytest.fixture
def sesion():
    s = SesionFalsa(
        hacer_cliente(),
        hacer_cliente("lf_inactivo", activo=False),
    )
    app.dependency_overrides[get_async_db] = override_con(s)
    try:
        yield s
    finally:
        app.dependency_overrides.pop(get_async_db, None)


def _form(**extra) -> dict:
    datos = {"grant_type": "client_credentials", "client_id": "lf_noc", "client_secret": CLIENT_SECRET}
    datos.update(extra)
    return {k: v for k, v in datos.items() if v is not None}


def test_credenciales_por_form_emiten_token(sesion: SesionFalsa) -> None:
    r = client.post(URL, data=_form())

    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 7 * 24 * 3600
    assert body["scope"] == "servicios:botellas:read"
    assert oauth.decodificar_token(body["access_token"])["sub"] == "lf_noc"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["pragma"] == "no-cache"
    assert sesion.clientes["lf_noc"].ultimo_uso_at is not None
    assert sesion.commits == 1


def test_credenciales_por_basic_emiten_token(sesion: SesionFalsa) -> None:
    r = client.post(URL, data={"grant_type": "client_credentials"}, auth=("lf_noc", CLIENT_SECRET))

    assert r.status_code == 200
    assert oauth.decodificar_token(r.json()["access_token"])["sub"] == "lf_noc"


@pytest.mark.parametrize(
    "datos",
    [
        _form(client_secret="incorrecto"),
        _form(client_id="lf_inexistente"),
        _form(client_id="lf_inactivo"),
        _form(client_secret=None),
    ],
    ids=["secret_incorrecto", "cliente_inexistente", "cliente_inactivo", "sin_secret"],
)
def test_credenciales_invalidas_401_invalid_client(sesion: SesionFalsa, datos: dict) -> None:
    r = client.post(URL, data=datos)

    assert r.status_code == 401
    assert r.json()["error"] == "invalid_client"
    assert r.headers["www-authenticate"].startswith("Basic")
    assert "access_token" not in r.json()


def test_basic_con_secret_incorrecto_401(sesion: SesionFalsa) -> None:
    r = client.post(URL, data={"grant_type": "client_credentials"}, auth=("lf_noc", "otro"))
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_client"


def test_grant_type_no_soportado_400(sesion: SesionFalsa) -> None:
    r = client.post(URL, data=_form(grant_type="password"))
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"


def test_sin_grant_type_400_invalid_request(sesion: SesionFalsa) -> None:
    r = client.post(URL, data=_form(grant_type=None))
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


def test_scope_no_autorizado_400(sesion: SesionFalsa) -> None:
    r = client.post(URL, data=_form(scope="servicios:botellas:read admin:todo"))
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_scope"


def test_scope_pedido_subconjunto_se_respeta(sesion: SesionFalsa) -> None:
    r = client.post(URL, data=_form(scope="servicios:botellas:read"))
    assert r.status_code == 200
    assert r.json()["scope"] == "servicios:botellas:read"


def test_dos_metodos_de_autenticacion_a_la_vez_400(sesion: SesionFalsa) -> None:
    r = client.post(URL, data=_form(), auth=("lf_noc", CLIENT_SECRET))
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


def test_secreto_de_firma_ausente_503(sesion: SesionFalsa, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OAUTH_JWT_SECRET", "")
    r = client.post(URL, data=_form())
    assert r.status_code == 503
    assert "access_token" not in r.json()


def test_el_secret_nunca_aparece_en_logs(sesion: SesionFalsa, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    ok = client.post(URL, data=_form())
    client.post(URL, data=_form(client_secret="secreto-equivocado-XYZ"))

    assert ok.status_code == 200
    todo = "\n".join(r.getMessage() for r in caplog.records)
    assert CLIENT_SECRET not in todo
    assert "secreto-equivocado-XYZ" not in todo
    assert ok.json()["access_token"] not in todo
