# Nombre de archivo: test_slack_refresco_prov.py
# Ubicación de archivo: tests/test_slack_refresco_prov.py
# Descripción: Tests del refresco asíncrono contra PROV disparado por "Servicios <cable>"/"Servicios <cable> B<N>" de Slack (Task 9): tope de 25, deadline, candado por cable, fallo puntual, persistencia del intento fallido y bypass de reintentos

"""Task 9 del plan "Corrección de ingresos/servicios" (2026-09-23).

Dos patrones de cliente PROV, a propósito (mismo criterio que pide el brief):

1. `_ClientePROVFalso` — duck-typed, inyectado por `monkeypatch` sobre
   `modules.slack_baneo_notifier.refresco_prov.get_prov_client` (patrón de
   `tests/test_servicios_prov_routes.py:105`). Cubre la orquestación del lote (tope, deadline,
   candado, fallo puntual) sin depender de la implementación real de reintentos/backoff de
   `ProvClient` — más rápido y determinista para simular demoras/errores puntuales.
2. `httpx.MockTransport` contra un `ProvClient` real (patrón de `tests/test_prov_client.py:20-40`)
   — un único test (`test_timeout_sin_reintentos_se_clasifica_como_timeout`) que ejercita el
   cliente de verdad para confirmar que `max_reintentos=0` (Step 2 del brief: mismo criterio que
   `_PROV_REFRESCAR_MAX_REINTENTOS=1` de `api/app/routes/servicios.py`, pero sin ningún reintento)
   realmente corta en el primer intento, y que el motivo queda clasificado como "timeout" en el
   mensaje de seguimiento.

La mayoría de los servicios de estos tests usan un `servicio_id` (PK) NEGATIVO a propósito: los PKs
reales de `app.servicios.id` son siempre positivos (columna `SERIAL`), así que un PK negativo no
puede colisionar jamás con una fila real y no hace falta crear una fila en `app.servicios` para los
tests que sólo verifican orquestación (tope/deadline/candado/fallo puntual) — cuando el camino de
éxito busca el `Servicio` por ese PK y no lo encuentra, lo trata como "se borró entre medio" (no
escribe nada, cuenta como éxito de todas formas, ver `_refrescar_un_servicio`). Sólo los dos tests
que verifican el contenido real de `app.servicios_sync_prov` (`test_fallo_persiste_ultimo_intento_y_error`,
`test_timeout_sin_reintentos_se_clasifica_como_timeout`) necesitan una fila real — ahí sí se crea con
`_crear_servicio`, en el namespace reservado `9003xx` (confirmado libre el 2026-09-24 contra
`lasfocasdev-postgres`, mismo criterio que `tests/test_prov_frescura.py`).

`test_prov_no_configurado_no_encola_nada` es el único caso sin `@requiere_postgres_real` ni
`@pytest.mark.asyncio`: ejercita `IngresoListener._disparar_refresco_prov`, que es síncrono y corta
ANTES de tocar la DB o el loop (Step 3 del brief) — mismo criterio que la Parte 1 de
`test_prov_frescura.py` para lo que no necesita Postgres.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import MagicMock

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import modules.slack_baneo_notifier.listener as listener_module
import modules.slack_baneo_notifier.refresco_prov as refresco_prov
from core.services.cromo.verificador import ServicioUnico
from core.services.prov.client import ProvClient, ProvClientError, ProvServicioNoEncontradoError
from core.services.prov.config import ProvConfig, ProvConfigError
from db.session import SessionLocal, async_engine
from tests.soporte_postgres_real import requiere_postgres_real

_NUMEROS_DE_TEST = ("900310", "900311")

# Motivo (mismo que `tests/test_prov_frescura.py`/`tests/test_prov_ingesta.py`): `pytest-asyncio`
# crea un event loop NUEVO por cada test async, pero `refresco_prov.AsyncSessionLocal` es el
# sessionmaker pooleado de proceso (`db.session.AsyncSessionLocal`) — reusar entre tests una
# conexión de ese pool creada bajo un loop ya cerrado revienta con "Future attached to a different
# loop". Un engine dedicado con `NullPool` nunca cachea una conexión entre llamadas, así que no hay
# nada que reusar entre loops distintos.
_engine_test = create_async_engine(async_engine.url.render_as_string(hide_password=False), poolclass=NullPool)
_AsyncSessionLocalTest = async_sessionmaker(_engine_test, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _usar_engine_de_test_sin_pool(monkeypatch):
    """Autouse: todos los tests de este archivo pasan por `refrescar_servicios_vencidos`, que abre
    sus sesiones async vía el nombre de módulo `refresco_prov.AsyncSessionLocal` — se reemplaza acá
    por el sessionmaker con `NullPool` de arriba. Inocuo para los dos tests que no tocan DB
    (`test_prov_no_configurado_no_encola_nada`, `test_sin_loop_no_encola_y_sin_nota`): sólo
    reemplaza un atributo de módulo que esos tests ni siquiera ejercitan."""
    monkeypatch.setattr(refresco_prov, "AsyncSessionLocal", _AsyncSessionLocalTest)


@pytest.fixture
def _limpiar_servicios_de_test():
    yield
    with SessionLocal() as session:
        # El `ON DELETE CASCADE` de `servicios_sync_prov.servicio_id` se encarga de esa tabla solo.
        session.execute(
            text("DELETE FROM app.servicios WHERE numero_primer_servicio = ANY(:numeros ::varchar[])"),
            {"numeros": list(_NUMEROS_DE_TEST)},
        )
        session.commit()


def _crear_servicio(numero: str) -> int:
    """Crea un Servicio de test mínimo y devuelve su PK entero — mismo helper que
    `tests/test_prov_frescura.py::_crear_servicio`."""
    with SessionLocal() as session:
        pk = session.execute(
            text(
                "INSERT INTO app.servicios "
                "(servicio_id, numero_primer_servicio, numero_linea, estado_servicio, tipo_servicio, origen_datos) "
                "VALUES (:numero, :numero, :numero, 'DESCONOCIDO', 'EWS', 'MANUAL'::app.servicio_origen_datos) "
                "RETURNING id"
            ),
            {"numero": numero},
        ).scalar_one()
        session.commit()
        return int(pk)


def _servicio_unico(servicio_id: int, servicio_id_externo: str) -> ServicioUnico:
    """Mismo criterio que `tests/test_slack_cable_info.py::_servicio_unico`:
    `numero_primer_servicio=servicio_id_externo` para que el "numero_prov" que le llega al cliente
    PROV falso sea previsible."""
    return ServicioUnico(
        servicio_id=servicio_id,
        servicio_id_externo=servicio_id_externo,
        numero_primer_servicio=servicio_id_externo,
        nombre_cliente="Cliente Real",
        cliente=None,
        estado_servicio="ACTIVO",
        tipo_servicio="FO",
        pelos_n_ids=[1],
        cantidad_pelos=1,
        numeros_en_pelo=[],
        metodos=["EXACTO"],
    )


class _ClientePROVFalso:
    """Duck-typed, mismo contrato que `ProvClient.obtener_contexto_servicio` — patrón de
    `tests/test_servicios_prov_routes.py:105`."""

    def __init__(
        self,
        *,
        respuestas: Optional[dict[str, Any]] = None,
        errores: Optional[dict[str, Exception]] = None,
        demoras: Optional[dict[str, float]] = None,
    ) -> None:
        self._respuestas = respuestas or {}
        self._errores = errores or {}
        self._demoras = demoras or {}
        self.llamadas: list[str] = []

    async def obtener_contexto_servicio(self, nro_servicio: str, *, max_reintentos: int | None = None) -> dict[str, Any]:
        self.llamadas.append(nro_servicio)
        if nro_servicio in self._demoras:
            await asyncio.sleep(self._demoras[nro_servicio])
        if nro_servicio in self._errores:
            raise self._errores[nro_servicio]
        return self._respuestas.get(nro_servicio, {"nro_servicio": nro_servicio, "estado_comercial": "INSTALADO"})


# ── Caso obligatorio: tope de 25 respetado ───────────────────────────────────


@requiere_postgres_real
@pytest.mark.asyncio
async def test_tope_de_25_respetado(monkeypatch):
    servicios = [_servicio_unico(-(900_000 + i), f"CAP{i:03d}") for i in range(30)]
    cliente_falso = _ClientePROVFalso()
    monkeypatch.setattr(refresco_prov, "get_prov_client", lambda: cliente_falso)

    client_mock = MagicMock()
    await refresco_prov.refrescar_servicios_vencidos(
        cable_n_id=-5_900_001,
        servicios=servicios,
        client=client_mock,
        channel="C1",
        thread_ts="1.1",
    )

    assert len(cliente_falso.llamadas) == 25
    client_mock.chat_postMessage.assert_called_once()


# ── Caso obligatorio: el deadline corta el lote ──────────────────────────────


@requiere_postgres_real
@pytest.mark.asyncio
async def test_deadline_corta_el_lote(monkeypatch):
    rapido = _servicio_unico(-900_101, "RAPIDO")
    lento = _servicio_unico(-900_102, "LENTO")
    cliente_falso = _ClientePROVFalso(demoras={"LENTO": 3.0})
    monkeypatch.setattr(refresco_prov, "get_prov_client", lambda: cliente_falso)

    client_mock = MagicMock()
    await refresco_prov.refrescar_servicios_vencidos(
        cable_n_id=-5_900_002,
        servicios=[rapido, lento],
        client=client_mock,
        channel="C1",
        thread_ts="1.1",
        deadline_segundos=0.3,
    )

    texto = client_mock.chat_postMessage.call_args.kwargs["text"]
    assert "RAPIDO" in texto
    assert "LENTO" in texto
    assert "se agotó el tiempo del lote" in texto


# ── Caso obligatorio: un fallo puntual no aborta el resto ────────────────────


@requiere_postgres_real
@pytest.mark.asyncio
async def test_fallo_puntual_no_aborta_el_resto(monkeypatch):
    ok1 = _servicio_unico(-900_111, "OK1")
    falla = _servicio_unico(-900_112, "FALLA")
    ok2 = _servicio_unico(-900_113, "OK2")
    cliente_falso = _ClientePROVFalso(
        errores={"FALLA": ProvServicioNoEncontradoError("FALLA", "sin contexto de test")}
    )
    monkeypatch.setattr(refresco_prov, "get_prov_client", lambda: cliente_falso)

    client_mock = MagicMock()
    await refresco_prov.refrescar_servicios_vencidos(
        cable_n_id=-5_900_003,
        servicios=[ok1, falla, ok2],
        client=client_mock,
        channel="C1",
        thread_ts="1.1",
    )

    assert sorted(cliente_falso.llamadas) == ["FALLA", "OK1", "OK2"]
    texto = client_mock.chat_postMessage.call_args.kwargs["text"]
    assert "OK1" in texto
    assert "OK2" in texto
    assert "FALLA" in texto
    assert "no encontrado en PROV" in texto


# ── Caso obligatorio: PROV no configurado no encola nada ─────────────────────


def test_prov_no_configurado_no_encola_nada(monkeypatch):
    """`IngresoListener._disparar_refresco_prov` corta ANTES de encolar (Step 3 del brief) — no
    toca DB ni loop real, por eso no lleva `@requiere_postgres_real` ni `@pytest.mark.asyncio`
    (mismo criterio que la Parte 1 de `tests/test_prov_frescura.py`)."""
    listener = listener_module.IngresoListener(bot_token="xoxb-test", app_token="xapp-test", loop=MagicMock())

    def _romper() -> Any:
        raise ProvConfigError("faltan secrets de PROV en este entorno de test")

    monkeypatch.setattr(listener_module, "get_prov_client", _romper)
    espia_encolar = MagicMock()
    monkeypatch.setattr(listener_module.asyncio, "run_coroutine_threadsafe", espia_encolar)

    servicios = [_servicio_unico(-1, "X")]
    refrescando, nota = listener._disparar_refresco_prov(123, servicios, MagicMock(), "C1", "1.1")

    assert refrescando is False
    assert nota == "⚠️ PROV no está configurado en este entorno — no se pudo refrescar automáticamente."
    espia_encolar.assert_not_called()


def test_sin_loop_no_encola_y_sin_nota(monkeypatch):
    """Complementa el caso anterior: sin loop (tests, uso standalone — constructor sin `loop=`,
    igual que las Tasks 4/6/8), el refresco se saltea en silencio, sin ninguna nota — no hay nada
    accionable que decirle al técnico sobre un detalle interno del proceso (ver docstring de
    `_disparar_refresco_prov`)."""
    listener = listener_module.IngresoListener(bot_token="xoxb-test", app_token="xapp-test")
    espia_encolar = MagicMock()
    monkeypatch.setattr(listener_module.asyncio, "run_coroutine_threadsafe", espia_encolar)

    servicios = [_servicio_unico(-1, "X")]
    refrescando, nota = listener._disparar_refresco_prov(123, servicios, MagicMock(), "C1", "1.1")

    assert refrescando is False
    assert nota is None
    espia_encolar.assert_not_called()


# ── Caso obligatorio: el candado por cable evita el refresco duplicado ───────


@requiere_postgres_real
@pytest.mark.asyncio
async def test_candado_por_cable_evita_refresco_duplicado(monkeypatch):
    cable_n_id = -5_900_005
    servicios = [_servicio_unico(-900_121, "CANDADO1"), _servicio_unico(-900_122, "CANDADO2")]
    cliente_falso = _ClientePROVFalso()
    monkeypatch.setattr(refresco_prov, "get_prov_client", lambda: cliente_falso)

    client_mock_1 = MagicMock()
    client_mock_2 = MagicMock()

    await asyncio.gather(
        refresco_prov.refrescar_servicios_vencidos(
            cable_n_id=cable_n_id, servicios=servicios, client=client_mock_1, channel="C1", thread_ts="1.1"
        ),
        refresco_prov.refrescar_servicios_vencidos(
            cable_n_id=cable_n_id, servicios=servicios, client=client_mock_2, channel="C1", thread_ts="1.2"
        ),
    )

    # Sólo UN lote se ejecutó de verdad — la segunda invocación concurrente para el mismo cable se
    # saltea entera (ni llamadas a PROV ni un segundo mensaje redundante).
    assert len(cliente_falso.llamadas) == 2
    total_mensajes = client_mock_1.chat_postMessage.call_count + client_mock_2.chat_postMessage.call_count
    assert total_mensajes == 1


# ── Caso obligatorio: el fallo persiste ultimo_intento/ultimo_error ──────────


@requiere_postgres_real
@pytest.mark.asyncio
async def test_fallo_persiste_ultimo_intento_y_error(monkeypatch, _limpiar_servicios_de_test):
    numero = "900310"
    pk = _crear_servicio(numero)
    servicio = _servicio_unico(pk, numero)

    error = ProvClientError("PROV respondió 404 para la consulta", status_code=404)
    cliente_falso = _ClientePROVFalso(errores={numero: error})
    monkeypatch.setattr(refresco_prov, "get_prov_client", lambda: cliente_falso)

    antes = datetime.now(timezone.utc)
    client_mock = MagicMock()
    await refresco_prov.refrescar_servicios_vencidos(
        cable_n_id=-5_900_006,
        servicios=[servicio],
        client=client_mock,
        channel="C1",
        thread_ts="1.1",
    )
    despues = datetime.now(timezone.utc)

    with SessionLocal() as session:
        fila = session.execute(
            text(
                "SELECT ultima_sincronizacion_ok, ultimo_intento, ultimo_error, nro_servicio_consultado "
                "FROM app.servicios_sync_prov WHERE servicio_id = :pk"
            ),
            {"pk": pk},
        ).one()

    ultima_ok, ultimo_intento, ultimo_error, nro_consultado = fila
    # Centinela de "nunca sincronizado con éxito" (ver docstring de refresco_prov.py) — NO es un
    # éxito real, pero satisface el NOT NULL de la columna y deja al servicio vencido para siempre
    # hasta que un éxito real la actualice.
    assert ultima_ok == refresco_prov._EPOCA_NUNCA_SINCRONIZADO
    assert antes <= ultimo_intento <= despues
    assert ultimo_error is not None and "PROV respondió 404" in ultimo_error
    assert nro_consultado == numero

    texto = client_mock.chat_postMessage.call_args.kwargs["text"]
    assert numero in texto
    assert "PROV respondió 404" in texto


# ── Bonus: cliente PROV real (httpx.MockTransport) — max_reintentos=0 y motivo "timeout" ─────


async def _sin_espera(*_args: Any, **_kwargs: Any) -> None:
    return None


@requiere_postgres_real
@pytest.mark.asyncio
async def test_timeout_sin_reintentos_se_clasifica_como_timeout(monkeypatch, _limpiar_servicios_de_test):
    """Ejercita el `ProvClient` real (no el duck-typed) para confirmar dos cosas a la vez: que
    `max_reintentos=0` corta en el primer intento pese a un error transitorio (ni un solo
    reintento/backoff), y que ese motivo queda clasificado y persistido como "timeout" (no como
    "no encontrado"/4xx) en el mensaje de seguimiento."""
    numero = "900311"
    pk = _crear_servicio(numero)
    servicio = _servicio_unico(pk, numero)

    llamadas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas.append(request.url.params["nro_servicio"])
        raise httpx.ReadTimeout("timeout simulado", request=request)

    cliente_http = httpx.AsyncClient(
        base_url="http://prov.invalido.test", transport=httpx.MockTransport(handler)
    )
    config = ProvConfig(
        base_url="http://prov.invalido.test", user="u", password="p", timeout=1.0, rate_limit_per_second=1000.0
    )
    cliente_real = ProvClient(config=config, cliente_http=cliente_http)

    monkeypatch.setattr("core.services.prov.client.asyncio.sleep", _sin_espera)
    monkeypatch.setattr(refresco_prov, "get_prov_client", lambda: cliente_real)

    client_mock = MagicMock()
    try:
        await refresco_prov.refrescar_servicios_vencidos(
            cable_n_id=-5_900_007,
            servicios=[servicio],
            client=client_mock,
            channel="C1",
            thread_ts="1.1",
        )
    finally:
        await cliente_http.aclose()

    assert len(llamadas) == 1  # max_reintentos=0 -> un solo intento, pese al error transitorio

    texto = client_mock.chat_postMessage.call_args.kwargs["text"]
    assert numero in texto
    assert "timeout" in texto or "error de comunicación con PROV" in texto
