# Nombre de archivo: test_prov_client.py
# Ubicación de archivo: tests/test_prov_client.py
# Descripción: Pruebas del cliente HTTP de PROV (Basic Auth + payload "sin contexto" + reintentos) con httpx mockeado, sin red real

from __future__ import annotations

import httpx
import pytest

from core.services.prov.client import (
    ProvClient,
    ProvClientError,
    ProvServicioNoEncontradoError,
    cerrar_prov_client,
    get_prov_client,
)
from core.services.prov.config import ProvConfig

BASE_URL = "http://prov.invalido.test/api/v1/ADMEQ"


def _config() -> ProvConfig:
    return ProvConfig(
        base_url=BASE_URL,
        user="user_test",
        password="pass_test",
        timeout=1.0,
        rate_limit_per_second=1000.0,  # alto en tests que no miden timing, para no frenarlos
    )


def _cliente_con_transport(transport: httpx.MockTransport) -> ProvClient:
    cliente_http = httpx.AsyncClient(base_url=BASE_URL, transport=transport)
    return ProvClient(config=_config(), cliente_http=cliente_http)


async def _sin_espera(*_args, **_kwargs) -> None:
    return None


@pytest.mark.asyncio
async def test_obtiene_contexto_servicio_con_basic_auth():
    capturado: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["auth"] = request.headers["Authorization"]
        capturado["nro_servicio"] = request.url.params["nro_servicio"]
        return httpx.Response(
            200,
            json={
                "Result": "Success",
                "Resultado:": {"nro_servicio": "122214", "estado_comercial": "INSTALADO"},
            },
        )

    cliente = _cliente_con_transport(httpx.MockTransport(handler))
    resultado = await cliente.obtener_contexto_servicio("122214")

    assert resultado == {"nro_servicio": "122214", "estado_comercial": "INSTALADO"}
    assert capturado["nro_servicio"] == "122214"
    assert capturado["auth"].startswith("Basic ")


@pytest.mark.asyncio
async def test_levanta_no_encontrado_cuando_resultado_es_un_string():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ProcessId": "srv-prov4-1",
                "DoneTime": "0.01",
                "Result": "Success",
                "Resultado:": "No hay contexto para el número de servicio ingresado",
            },
        )

    cliente = _cliente_con_transport(httpx.MockTransport(handler))

    with pytest.raises(ProvServicioNoEncontradoError) as exc_info:
        await cliente.obtener_contexto_servicio("000000")

    assert exc_info.value.nro_servicio == "000000"
    assert "No hay contexto" in exc_info.value.mensaje_prov


@pytest.mark.asyncio
async def test_reintenta_en_error_5xx_y_despues_tiene_exito(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.services.prov.client.asyncio.sleep", _sin_espera)
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        if llamadas["n"] < 3:
            return httpx.Response(503, text="temporalmente no disponible")
        return httpx.Response(200, json={"Result": "Success", "Resultado:": {"nro_servicio": "1"}})

    cliente = _cliente_con_transport(httpx.MockTransport(handler))
    resultado = await cliente.obtener_contexto_servicio("1")

    assert llamadas["n"] == 3
    assert resultado == {"nro_servicio": "1"}


@pytest.mark.asyncio
async def test_agota_reintentos_y_levanta_prov_client_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.services.prov.client.asyncio.sleep", _sin_espera)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="caído")

    cliente = _cliente_con_transport(httpx.MockTransport(handler))

    with pytest.raises(ProvClientError):
        await cliente.obtener_contexto_servicio("1")


@pytest.mark.asyncio
async def test_error_4xx_no_reintenta_y_levanta_prov_client_error():
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(400, text="parámetro inválido")

    cliente = _cliente_con_transport(httpx.MockTransport(handler))

    with pytest.raises(ProvClientError) as exc_info:
        await cliente.obtener_contexto_servicio("1")

    assert llamadas["n"] == 1
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_max_reintentos_acota_los_intentos_para_una_llamada_puntual(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.services.prov.client.asyncio.sleep", _sin_espera)
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(503, text="caído")

    cliente = _cliente_con_transport(httpx.MockTransport(handler))

    with pytest.raises(ProvClientError):
        await cliente.obtener_contexto_servicio("1", max_reintentos=1)

    # 1 intento inicial + 1 reintento = 2 llamadas totales, no los 4 del default (_REINTENTOS_MAX=3).
    assert llamadas["n"] == 2


@pytest.mark.asyncio
async def test_max_reintentos_none_usa_el_default_del_cliente(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.services.prov.client.asyncio.sleep", _sin_espera)
    llamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        return httpx.Response(503, text="caído")

    cliente = _cliente_con_transport(httpx.MockTransport(handler))

    with pytest.raises(ProvClientError):
        await cliente.obtener_contexto_servicio("1")

    assert llamadas["n"] == 4  # default: _REINTENTOS_MAX=3 reintentos + intento inicial


@pytest.mark.asyncio
async def test_cerrar_prov_client_es_no_op_si_el_singleton_nunca_se_instancio():
    get_prov_client.cache_clear()
    # No debe intentar construir un ProvClient real (que levantaría ProvConfigError sin secrets
    # configurados en este entorno de test) — el cache vacío alcanza para saber que no hay nada
    # que cerrar.
    await cerrar_prov_client()
    assert get_prov_client.cache_info().currsize == 0


@pytest.mark.asyncio
async def test_cerrar_prov_client_cierra_y_limpia_el_cache_si_esta_poblado(monkeypatch: pytest.MonkeyPatch):
    get_prov_client.cache_clear()
    cerrado = {"n": 0}

    class _ProvClientFake:
        async def cerrar(self) -> None:
            cerrado["n"] += 1

    monkeypatch.setattr("core.services.prov.client.ProvClient", _ProvClientFake)
    get_prov_client()  # instancia el singleton con la clase fake, sin tocar config real
    assert get_prov_client.cache_info().currsize == 1

    await cerrar_prov_client()

    assert cerrado["n"] == 1
    assert get_prov_client.cache_info().currsize == 0
