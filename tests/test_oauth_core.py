# Nombre de archivo: test_oauth_core.py
# Ubicación de archivo: tests/test_oauth_core.py
# Descripción: Tests unitarios del núcleo OAuth2 M2M: emisión y validación de JWT, autenticación de clientes

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from api.app import oauth
from tests.soporte_oauth import CLIENT_SECRET, SECRETO_TEST, SesionFalsa, hacer_cliente, secreto_firma  # noqa: F401


def _claims_validos(**extra) -> dict:
    ahora = datetime.now(timezone.utc)
    claims = {
        "iss": oauth.ISSUER,
        "aud": oauth.AUDIENCE,
        "sub": "lf_noc",
        "scope": "servicios:botellas:read",
        "iat": int(ahora.timestamp()),
        "exp": int((ahora + timedelta(hours=1)).timestamp()),
    }
    claims.update(extra)
    return claims


def test_emitir_token_se_decodifica_con_claims_esperados() -> None:
    token, expires_in = oauth.emitir_token("lf_noc", ["servicios:botellas:read"])

    claims = oauth.decodificar_token(token)

    assert expires_in == 7 * 24 * 3600
    assert claims["sub"] == "lf_noc"
    assert claims["scope"] == "servicios:botellas:read"
    assert claims["exp"] - claims["iat"] == 7 * 24 * 3600
    assert claims["iss"] == "las-focas" and claims["aud"] == "las-focas-api-v1"
    assert claims["jti"]


def test_ttl_configurable_por_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OAUTH_TOKEN_TTL_SECONDS", "60")
    assert oauth.ttl_token_segundos() == 60
    monkeypatch.setenv("OAUTH_TOKEN_TTL_SECONDS", "no-numero")
    assert oauth.ttl_token_segundos() == oauth.TTL_DEFAULT_SEGUNDOS
    monkeypatch.setenv("OAUTH_TOKEN_TTL_SECONDS", "-5")
    assert oauth.ttl_token_segundos() == oauth.TTL_DEFAULT_SEGUNDOS


def test_token_vencido_se_rechaza() -> None:
    hace_ocho_dias = datetime.now(timezone.utc) - timedelta(days=8)
    token, _ = oauth.emitir_token("lf_noc", ["servicios:botellas:read"], ahora=hace_ocho_dias)

    with pytest.raises(oauth.TokenInvalido, match="vencido"):
        oauth.decodificar_token(token)


@pytest.mark.parametrize("token", ["abc", "a.b", "a.b.c", "", "eyJhbGciOiJIUzI1NiJ9..firma"])
def test_token_malformado_se_rechaza(token: str) -> None:
    with pytest.raises(oauth.TokenInvalido):
        oauth.decodificar_token(token)


def test_firma_con_otro_secreto_se_rechaza() -> None:
    token = jwt.encode(_claims_validos(), "otro-secreto-cualquiera-de-mas-de-32-bytes!!", algorithm="HS256")

    with pytest.raises(oauth.TokenInvalido):
        oauth.decodificar_token(token)


def test_alg_none_se_rechaza() -> None:
    token = jwt.encode(_claims_validos(), key=None, algorithm="none")

    with pytest.raises(oauth.TokenInvalido):
        oauth.decodificar_token(token)


def test_otro_algoritmo_hmac_se_rechaza() -> None:
    token = jwt.encode(_claims_validos(), SECRETO_TEST, algorithm="HS512")

    with pytest.raises(oauth.TokenInvalido):
        oauth.decodificar_token(token)


@pytest.mark.parametrize("campo,valor", [("aud", "otra-api"), ("iss", "otro-emisor")])
def test_audiencia_o_emisor_incorrectos_se_rechazan(campo: str, valor: str) -> None:
    token = jwt.encode(_claims_validos(**{campo: valor}), SECRETO_TEST, algorithm="HS256")

    with pytest.raises(oauth.TokenInvalido):
        oauth.decodificar_token(token)


@pytest.mark.parametrize("faltante", ["exp", "iat", "sub", "aud", "iss"])
def test_claim_obligatorio_faltante_se_rechaza(faltante: str) -> None:
    claims = _claims_validos()
    del claims[faltante]
    token = jwt.encode(claims, SECRETO_TEST, algorithm="HS256")

    with pytest.raises(oauth.TokenInvalido):
        oauth.decodificar_token(token)


def test_scope_no_string_se_rechaza() -> None:
    token = jwt.encode(_claims_validos(scope=["servicios:botellas:read"]), SECRETO_TEST, algorithm="HS256")

    with pytest.raises(oauth.TokenInvalido):
        oauth.decodificar_token(token)


@pytest.mark.parametrize("secreto", ["", "corto"])
def test_secreto_ausente_o_corto_falla_cerrado(monkeypatch: pytest.MonkeyPatch, secreto: str) -> None:
    monkeypatch.setenv("OAUTH_JWT_SECRET", secreto)

    with pytest.raises(oauth.OAuthNoConfigurado):
        oauth.emitir_token("lf_noc", [])
    with pytest.raises(oauth.OAuthNoConfigurado):
        oauth.decodificar_token("a.b.c")


def test_autenticar_cliente_valido() -> None:
    cliente = hacer_cliente()
    resultado = asyncio.run(oauth.autenticar_cliente(SesionFalsa(cliente), "lf_noc", CLIENT_SECRET))
    assert resultado is cliente


@pytest.mark.parametrize(
    "client_id,secreto,activo",
    [("lf_noc", "secreto-incorrecto", True), ("lf_inexistente", CLIENT_SECRET, True), ("lf_noc", CLIENT_SECRET, False)],
)
def test_autenticar_cliente_rechaza(client_id: str, secreto: str, activo: bool) -> None:
    sesion = SesionFalsa(hacer_cliente(activo=activo))
    assert asyncio.run(oauth.autenticar_cliente(sesion, client_id, secreto)) is None


def test_cliente_inexistente_igual_paga_bcrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin el hash señuelo, un client_id inexistente respondería más rápido y quedaría enumerable."""

    llamadas: list[str] = []
    original = oauth.verify_password

    def _espia(password: str, hashed: str) -> bool:
        llamadas.append(hashed)
        return original(password, hashed)

    monkeypatch.setattr(oauth, "verify_password", _espia)
    asyncio.run(oauth.autenticar_cliente(SesionFalsa(), "lf_inexistente", "x"))

    assert len(llamadas) == 1
