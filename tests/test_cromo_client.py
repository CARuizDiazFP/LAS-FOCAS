# Nombre de archivo: test_cromo_client.py
# Ubicación de archivo: tests/test_cromo_client.py
# Descripción: Pruebas del cliente HTTP de Cromo Red (OAuth2 + paginación + reintentos) con httpx mockeado, sin red real

from __future__ import annotations

import httpx
import pytest

from core.services.cromo.client import CromoClient, CromoClientError
from core.services.cromo.config import CromoConfig, CromoConfigError, enmascarar, get_cromo_config

BASE_URL = "http://cromo.invalido.test/cromo-api/v1/server"
OAUTH_URL = "http://cromo.invalido.test:9999/oauth2/oauth/token"
TOKEN_DEFAULT = "token-de-prueba"


def _config() -> CromoConfig:
    return CromoConfig(
        base_url="http://cromo.invalido.test",
        user="user_test",
        password="pass_test",
        timeout=1.0,
        psize_default=10,
        oauth_url=OAUTH_URL,
        client_id="cid_test",
        client_secret="csecret_test",
    )


def _con_oauth(handler_get, token: str = TOKEN_DEFAULT, status_oauth: int = 200):
    """Envuelve un handler de GET agregando la respuesta del POST de token OAuth2."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and str(request.url) == OAUTH_URL:
            if status_oauth >= 400:
                return httpx.Response(status_oauth, text="credenciales inválidas")
            return httpx.Response(status_oauth, json={"access_token": token, "expires_in": 3600})
        return handler_get(request)

    return handler


def _cliente_con_transport(transport: httpx.MockTransport) -> CromoClient:
    cliente_http = httpx.AsyncClient(base_url=BASE_URL, transport=transport)
    return CromoClient(config=_config(), cliente_http=cliente_http)


async def _sin_espera(*_args, **_kwargs) -> None:
    return None


# ── Autenticación OAuth2 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_obtiene_token_antes_de_la_primera_llamada_y_lo_reusa():
    llamadas_oauth = {"n": 0}
    llamadas_get = {"n": 0}

    def handler_get(request: httpx.Request) -> httpx.Response:
        llamadas_get["n"] += 1
        assert request.headers["Authorization"] == f"Bearer {TOKEN_DEFAULT}"
        return httpx.Response(200, json={"ok": True})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and str(request.url) == OAUTH_URL:
            llamadas_oauth["n"] += 1
        return _con_oauth(handler_get)(request)

    cliente = _cliente_con_transport(httpx.MockTransport(handler))
    await cliente.get_objeto(1)
    await cliente.get_objeto(2)

    assert llamadas_get["n"] == 2
    assert llamadas_oauth["n"] == 1  # el token se reusa, no se pide de nuevo


@pytest.mark.asyncio
async def test_token_vencido_se_renueva_una_vez_y_reintenta():
    respuestas_get = iter([401, 200])

    def handler_get(request: httpx.Request) -> httpx.Response:
        status = next(respuestas_get)
        if status == 401:
            return httpx.Response(401)
        return httpx.Response(200, json={"ok": True})

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    resultado = await cliente.get_objeto(1)

    assert resultado == {"ok": True}


@pytest.mark.asyncio
async def test_401_persistente_no_reintenta_infinito(monkeypatch):
    monkeypatch.setattr("core.services.cromo.client.asyncio.sleep", _sin_espera)
    llamadas_get = {"n": 0}

    def handler_get(request: httpx.Request) -> httpx.Response:
        llamadas_get["n"] += 1
        return httpx.Response(401)

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    with pytest.raises(CromoClientError):
        await cliente.get_objeto(1)

    # 1 intento inicial + 1 reintento tras renovar token = 2, nunca más
    assert llamadas_get["n"] == 2


@pytest.mark.asyncio
async def test_credenciales_oauth_invalidas_falla_claro_sin_llamar_a_db():
    llamadas_get = {"n": 0}

    def handler_get(request: httpx.Request) -> httpx.Response:
        llamadas_get["n"] += 1
        return httpx.Response(200, json={"ok": True})

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get, status_oauth=401)))
    with pytest.raises(CromoClientError, match="token OAuth2"):
        await cliente.get_objeto(1)

    assert llamadas_get["n"] == 0


# ── Pseudo-JSON de la API v1 (claves sin comillas) ──────────────────────────


@pytest.mark.asyncio
async def test_tolera_respuesta_pseudo_json_sin_comillas_en_claves():
    # Comportamiento real y documentado de Cromo v1 (vía api-gateway): claves sin comillas.
    # docs/ingesta_cromo.md asumía "la respuesta HTTP real es JSON válido" — no lo es.
    cuerpo_pseudo_json = (
        '{st:0,next:0,stats:[{id:69,count:7955}],'
        'response:[{id:10193375,n_id:10193375,class:69,name:"ODF colectora este Panamericana",at:[]}]}'
    )

    def handler_get(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=cuerpo_pseudo_json, headers={"content-type": "application/json"})

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    resultado = await cliente.get_coleccion("69", psize=1)

    assert resultado["stats"] == [{"id": 69, "count": 7955}]
    assert resultado["response"][0]["name"] == "ODF colectora este Panamericana"


@pytest.mark.asyncio
async def test_respuesta_no_parseable_ni_como_json_ni_json5_falla_claro():
    def handler_get(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="esto no es json de ninguna forma {{{")

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    with pytest.raises(CromoClientError, match="no es JSON"):
        await cliente.get_objeto(1)


# ── Rutas y parámetros ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_objeto_construye_ruta_correcta():
    capturado = {}

    def handler_get(request: httpx.Request) -> httpx.Response:
        capturado["url"] = str(request.url)
        return httpx.Response(200, json={"n_id": 1, "class": 68})

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    resultado = await cliente.get_objeto(10178728)

    assert resultado == {"n_id": 1, "class": 68}
    assert capturado["url"] == f"{BASE_URL}/db/objects/10178728"


@pytest.mark.asyncio
async def test_get_objeto_con_topologia_manda_show_repetido_no_coma_separado():
    capturado = {}

    def handler_get(request: httpx.Request) -> httpx.Response:
        capturado["url"] = str(request.url)
        capturado["show_list"] = request.url.params.get_list("show")
        return httpx.Response(200, json={"st": 0, "response": {"n_id": 9057909}})

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    resultado = await cliente.get_objeto_con_topologia(9057909)

    assert resultado == {"st": 0, "response": {"n_id": 9057909}}
    assert capturado["url"] == f"{BASE_URL}/db/objects/9057909?show=TOPOLOGIES&show=REL_ATTRIBUTE"
    # Contrato explícito: repetido, NO coma-separado como get_coleccion (que pega a otro endpoint)
    # — blindaje contra un futuro copy-paste desde ahí.
    assert capturado["show_list"] == ["TOPOLOGIES", "REL_ATTRIBUTE"]


@pytest.mark.asyncio
async def test_get_inner_y_get_container_construyen_ruta_correcta():
    rutas = []

    def handler_get(request: httpx.Request) -> httpx.Response:
        rutas.append(str(request.url))
        return httpx.Response(200, json={"st": 0, "response": []})

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    await cliente.get_inner(50010)
    await cliente.get_container(50010)

    assert rutas == [
        f"{BASE_URL}/db/objects/50010/inner",
        f"{BASE_URL}/db/objects/50010/container",
    ]


@pytest.mark.asyncio
async def test_get_coleccion_arma_params_filter_psize_show_next():
    capturado = {}

    def handler_get(request: httpx.Request) -> httpx.Response:
        capturado["params"] = dict(request.url.params)
        return httpx.Response(200, json={"stats": [{"id": 68, "count": 1}], "next": 0, "data": []})

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    await cliente.get_coleccion("68,121", psize=5, show=["SHOW", "TIME"], next_cursor=123)

    assert capturado["params"] == {"filter": "68,121", "psize": "5", "show": "SHOW,TIME", "next": "123"}


# ── Reintentos: red y 5xx sí, 4xx nunca ─────────────────────────────────────


@pytest.mark.asyncio
async def test_reintenta_en_5xx_y_eventualmente_responde_ok(monkeypatch):
    monkeypatch.setattr("core.services.cromo.client.asyncio.sleep", _sin_espera)
    llamadas = {"n": 0}

    def handler_get(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        if llamadas["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    resultado = await cliente.get_objeto(1)

    assert resultado == {"ok": True}
    assert llamadas["n"] == 3


@pytest.mark.asyncio
async def test_reintenta_en_error_de_red_y_agota_reintentos(monkeypatch):
    monkeypatch.setattr("core.services.cromo.client.asyncio.sleep", _sin_espera)
    llamadas = {"n": 0}

    def handler_get(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        raise httpx.ConnectError("sin ruta a Cromo", request=request)

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    with pytest.raises(CromoClientError):
        await cliente.get_objeto(1)

    # 1 intento inicial + 3 reintentos = 4 llamadas antes de agotar
    assert llamadas["n"] == 4


@pytest.mark.asyncio
async def test_nunca_reintenta_4xx_no_relacionado_con_auth(monkeypatch):
    monkeypatch.setattr("core.services.cromo.client.asyncio.sleep", _sin_espera)
    llamadas = {"n": 0}

    def handler_get(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(404, text="no encontrado")

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    with pytest.raises(CromoClientError):
        await cliente.get_objeto(1)

    assert llamadas["n"] == 1


@pytest.mark.asyncio
async def test_error_4xx_expone_status_code_para_distinguir_404_de_otras_fallas(monkeypatch):
    monkeypatch.setattr("core.services.cromo.client.asyncio.sleep", _sin_espera)

    def handler_get(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="no encontrado")

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    with pytest.raises(CromoClientError) as excinfo:
        await cliente.get_objeto(999999)

    assert excinfo.value.status_code == 404


# ── Paginación ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_iterar_coleccion_corta_cuando_next_es_cero_y_no_antes():
    paginas_respondidas = [
        {"stats": [{"id": 68, "count": 2}], "next": 45, "data": [{"n_id": 1}]},
        {"stats": [{"id": 68, "count": 2}], "next": 0, "data": [{"n_id": 2}]},
    ]
    llamadas = {"n": 0}

    def handler_get(request: httpx.Request) -> httpx.Response:
        pagina = paginas_respondidas[llamadas["n"]]
        llamadas["n"] += 1
        return httpx.Response(200, json=pagina)

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    recibidas = [pagina async for pagina in cliente.iterar_coleccion("68", psize=1)]

    assert len(recibidas) == 2
    assert recibidas[-1]["next"] == 0
    assert llamadas["n"] == 2


@pytest.mark.asyncio
async def test_iterar_coleccion_respeta_max_paginas_aunque_next_siga_activo():
    def handler_get(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"stats": [], "next": 999, "data": []})

    cliente = _cliente_con_transport(httpx.MockTransport(_con_oauth(handler_get)))
    recibidas = [pagina async for pagina in cliente.iterar_coleccion("68", max_paginas=2)]

    assert len(recibidas) == 2


# ── Configuración: validación al arranque, nunca loguear el secreto completo ──


def test_config_completa_se_construye_ok(monkeypatch):
    monkeypatch.setenv("CROMO_BASE_URL", "http://cromo.invalido.test")
    monkeypatch.setenv("CROMO_USER", "user_test")
    monkeypatch.setenv("CROMO_PASSWORD", "pass_test")
    monkeypatch.delenv("CROMO_TIMEOUT", raising=False)
    monkeypatch.delenv("CROMO_PSIZE_DEFAULT", raising=False)
    monkeypatch.delenv("CROMO_OAUTH_URL", raising=False)
    monkeypatch.delenv("CROMO_CLIENT_ID", raising=False)
    monkeypatch.delenv("CROMO_CLIENT_SECRET", raising=False)
    get_cromo_config.cache_clear()

    config = get_cromo_config()

    assert config.base_url == "http://cromo.invalido.test"
    assert config.timeout == 30.0
    assert config.psize_default == 5
    assert config.url_servidor == "http://cromo.invalido.test/cromo-api/v1/server"
    # Sin CROMO_OAUTH_URL explícito, se deriva del host de base_url en el puerto 9999.
    assert config.oauth_url == "http://cromo.invalido.test:9999/oauth2/oauth/token"
    # Sin client_id/secret explícitos, caen en los valores de fábrica documentados en el manual.
    assert config.client_id == "clientId"
    assert config.client_secret == "secret"
    get_cromo_config.cache_clear()


def test_config_respeta_oauth_url_y_client_credentials_explicitos(monkeypatch):
    monkeypatch.setenv("CROMO_BASE_URL", "http://cromo.invalido.test")
    monkeypatch.setenv("CROMO_USER", "user_test")
    monkeypatch.setenv("CROMO_PASSWORD", "pass_test")
    monkeypatch.setenv("CROMO_OAUTH_URL", "http://otro-host.test:9999/oauth2/oauth/token")
    monkeypatch.setenv("CROMO_CLIENT_ID", "mi_client_id")
    monkeypatch.setenv("CROMO_CLIENT_SECRET", "mi_client_secret")
    get_cromo_config.cache_clear()

    config = get_cromo_config()

    assert config.oauth_url == "http://otro-host.test:9999/oauth2/oauth/token"
    assert config.client_id == "mi_client_id"
    assert config.client_secret == "mi_client_secret"
    get_cromo_config.cache_clear()


def test_config_rechaza_psize_fuera_del_conjunto_permitido(monkeypatch):
    # Decisión de producto: psize de producción = 5, sólo {1,5,10,20,50} son válidos.
    monkeypatch.setenv("CROMO_BASE_URL", "http://cromo.invalido.test")
    monkeypatch.setenv("CROMO_USER", "user_test")
    monkeypatch.setenv("CROMO_PASSWORD", "pass_test")
    monkeypatch.setenv("CROMO_PSIZE_DEFAULT", "7")
    get_cromo_config.cache_clear()

    with pytest.raises(CromoConfigError, match="CROMO_PSIZE_DEFAULT"):
        get_cromo_config()
    get_cromo_config.cache_clear()


def test_config_incompleta_falla_con_mensaje_claro(monkeypatch):
    monkeypatch.delenv("CROMO_BASE_URL", raising=False)
    monkeypatch.delenv("CROMO_USER", raising=False)
    monkeypatch.delenv("CROMO_PASSWORD", raising=False)
    get_cromo_config.cache_clear()

    with pytest.raises(CromoConfigError, match="CROMO_BASE_URL"):
        get_cromo_config()
    get_cromo_config.cache_clear()


def test_config_rechaza_variable_de_plantilla_sin_resolver(monkeypatch):
    # Bug real detectado al ejecutar la sonda: el `route` de un environment de Postman
    # es "http://{{baseip}}:8181" y Postman resuelve {{baseip}} al hacer el request;
    # copiado tal cual a CROMO_BASE_URL, el cliente intenta resolver "{{baseip}}" como host.
    monkeypatch.setenv("CROMO_BASE_URL", "http://{{baseip}}:8181")
    monkeypatch.setenv("CROMO_USER", "user_test")
    monkeypatch.setenv("CROMO_PASSWORD", "pass_test")
    get_cromo_config.cache_clear()

    with pytest.raises(CromoConfigError, match="plantilla"):
        get_cromo_config()
    get_cromo_config.cache_clear()


def test_enmascarar_solo_muestra_los_ultimos_caracteres():
    assert enmascarar("un-token-secreto-largo") == "*" * 18 + "argo"
    assert enmascarar("abc") == "***"
    assert enmascarar("") == ""


def test_enmascarar_acota_asteriscos_en_tokens_muy_largos():
    # Hallazgo real: un access_token JWT de Cromo puede tener miles de caracteres; sin tope,
    # una sola línea de log queda inutilizable.
    token_largo = "x" * 2000 + "tP-g"
    resultado = enmascarar(token_largo)
    assert resultado == "*" * 20 + "tP-g"
    assert len(resultado) == 24
