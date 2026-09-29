# Nombre de archivo: test_api_v1_botellas.py
# Ubicación de archivo: tests/test_api_v1_botellas.py
# Descripción: Tests HTTP de GET /api/v1/servicios/{servicio_id}/botellas (protección OAuth2 y contrato de respuesta)

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app import oauth
from api.app.main import app
from core.services.servicio_botellas import ResultadoBotellas, ServicioResuelto
from db.session import get_async_db
from tests.soporte_oauth import SesionFalsa, hacer_cliente, override_con, secreto_firma  # noqa: F401

client = TestClient(app)
MODULO = "api.app.routes.v1.servicios"


def _servicio(pk: int = 737, servicio_id: str = "120393") -> MagicMock:
    svc = MagicMock()
    svc.id = pk
    svc.servicio_id = servicio_id
    return svc


BOTELLAS = ResultadoBotellas(
    nombres=["Cra San Martin 201 Bot 2 CF", "Botella 1", "Cra Urquiza 649 y TBA Bot 4 VICENTE LOPEZ"],
    orden_fuente="traza_cromo",
)


@pytest.fixture
def sesion():
    s = SesionFalsa(
        hacer_cliente(),
        hacer_cliente("lf_sin_scope", scopes=()),
        hacer_cliente("lf_revocado", activo=False),
    )
    app.dependency_overrides[get_async_db] = override_con(s)
    try:
        yield s
    finally:
        app.dependency_overrides.pop(get_async_db, None)


def _auth(client_id: str = "lf_noc", scopes=("servicios:botellas:read",), **kw) -> dict:
    token, _ = oauth.emitir_token(client_id, scopes, **kw)
    return {"Authorization": f"Bearer {token}"}


def _get(ident: str, headers: dict | None = None, *, resuelto=None, botellas=BOTELLAS):
    with patch(f"{MODULO}.resolver_servicio_por_identificador", AsyncMock(return_value=resuelto)) as res, patch(
        f"{MODULO}.botellas_de_servicio", AsyncMock(return_value=botellas)
    ) as bot:
        return client.get(f"/api/v1/servicios/{ident}/botellas", headers=headers or {}), res, bot


def test_id_vigente(sesion: SesionFalsa) -> None:
    r, res, bot = _get("120393", _auth(), resuelto=ServicioResuelto(_servicio(), es_id_vigente=True))

    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "servicio_consultado": "120393",
        "servicio_id_vigente": "120393",
        "es_id_vigente": True,
        "total_botellas": 3,
        "botellas": BOTELLAS.nombres,
        "orden_fuente": "traza_cromo",
    }
    bot.assert_awaited_once()
    assert bot.await_args.args[1] == 737


def test_id_historico(sesion: SesionFalsa) -> None:
    r, _, _ = _get("112763", _auth(), resuelto=ServicioResuelto(_servicio(), es_id_vigente=False))

    assert r.status_code == 200
    body = r.json()
    assert body["servicio_consultado"] == "112763"
    assert body["servicio_id_vigente"] == "120393"
    assert body["es_id_vigente"] is False


def test_servicio_inexistente_404(sesion: SesionFalsa) -> None:
    r, _, bot = _get("999999", _auth(), resuelto=None)

    assert r.status_code == 404
    bot.assert_not_awaited()


def test_servicio_sin_botellas_200_con_cero(sesion: SesionFalsa) -> None:
    r, _, _ = _get(
        "120393",
        _auth(),
        resuelto=ServicioResuelto(_servicio(), es_id_vigente=True),
        botellas=ResultadoBotellas(nombres=[], orden_fuente="sin_datos"),
    )

    assert r.status_code == 200
    assert r.json()["total_botellas"] == 0
    assert r.json()["orden_fuente"] == "sin_datos"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer abc.def.ghi"},
        {"Authorization": "Bearer no-es-un-jwt"},
        {"Authorization": "Basic bGZfbm9jOng="},
        # La API key interna NO sirve en /api/v1 (es la que fija tests/conftest.py).
        {"Authorization": "Bearer test-api-key"},
        {"X-API-Key": "test-api-key"},
    ],
    ids=["sin_header", "bearer_vacio", "jwt_basura", "no_jwt", "basic", "api_key_bearer", "api_key_header"],
)
def test_sin_token_valido_401(sesion: SesionFalsa, headers: dict) -> None:
    r, res, _ = _get("120393", headers, resuelto=ServicioResuelto(_servicio(), es_id_vigente=True))

    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")
    res.assert_not_awaited()


def test_token_vencido_401(sesion: SesionFalsa) -> None:
    viejo = _auth(ahora=datetime.now(timezone.utc) - timedelta(days=8))
    r, res, _ = _get("120393", viejo, resuelto=ServicioResuelto(_servicio(), es_id_vigente=True))

    assert r.status_code == 401
    assert 'error="invalid_token"' in r.headers["www-authenticate"]
    res.assert_not_awaited()


def test_token_sin_scope_403(sesion: SesionFalsa) -> None:
    r, res, _ = _get("120393", _auth("lf_sin_scope", scopes=()), resuelto=ServicioResuelto(_servicio(), True))

    assert r.status_code == 403
    assert 'error="insufficient_scope"' in r.headers["www-authenticate"]
    res.assert_not_awaited()


def test_scope_quitado_al_cliente_despues_de_emitir_403(sesion: SesionFalsa) -> None:
    """El token dice tener el scope, pero el cliente ya no lo tiene en la base: gana la base."""

    headers = _auth("lf_sin_scope", scopes=("servicios:botellas:read",))
    r, _, _ = _get("120393", headers, resuelto=ServicioResuelto(_servicio(), True))

    assert r.status_code == 403


def test_cliente_desactivado_con_token_vigente_401(sesion: SesionFalsa) -> None:
    r, res, _ = _get("120393", _auth("lf_revocado"), resuelto=ServicioResuelto(_servicio(), True))

    assert r.status_code == 401
    res.assert_not_awaited()


def test_cliente_borrado_con_token_vigente_401(sesion: SesionFalsa) -> None:
    r, _, _ = _get("120393", _auth("lf_ya_no_existe"), resuelto=ServicioResuelto(_servicio(), True))
    assert r.status_code == 401


def test_secreto_de_firma_ausente_503(sesion: SesionFalsa, monkeypatch: pytest.MonkeyPatch) -> None:
    headers = _auth()
    monkeypatch.setenv("OAUTH_JWT_SECRET", "")
    r, _, _ = _get("120393", headers, resuelto=ServicioResuelto(_servicio(), True))
    assert r.status_code == 503


def test_identificador_con_caracteres_invalidos_422(sesion: SesionFalsa) -> None:
    r, res, _ = _get("12%20OR%201=1", _auth(), resuelto=None)
    assert r.status_code == 422
    res.assert_not_awaited()


def test_jwt_no_sirve_en_rutas_internas(sesion: SesionFalsa) -> None:
    """Separación en la otra dirección: el token M2M no abre la API interna."""

    r = client.get("/servicios/search", params={"q": "1"}, headers=_auth())
    assert r.status_code == 403
