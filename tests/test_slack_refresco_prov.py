# Nombre de archivo: test_slack_refresco_prov.py
# Ubicación de archivo: tests/test_slack_refresco_prov.py
# Descripción: Tests del refresco asíncrono contra PROV disparado por "Servicios <cable>"/"Servicios <cable> B<N>" de Slack (Task 9): tope de 25, deadline, candado por cable + segundo mensaje, fallo puntual, persistencia del intento fallido (NULL, no centinela), camino feliz real, priorización por antigüedad y bypass de reintentos

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
escribe nada, cuenta como éxito de todas formas, ver `refrescar_un_servicio`). Los tests que
verifican contenido real de `app.servicios`/`app.servicios_sync_prov`
(`test_fallo_persiste_ultimo_intento_y_error`, `test_timeout_sin_reintentos_se_clasifica_como_timeout`,
`test_camino_feliz_refresca_de_verdad_y_persiste_el_exito`,
`test_priorizar_por_antiguedad_nulos_primero_y_ascendente` — agregados en el round de fix de la
revisión de calidad, Important 5: el camino feliz real y `priorizar_por_antiguedad` no tenían
ninguna cobertura antes) sí necesitan una o más filas reales — se crean con `_crear_servicio`, en el
namespace reservado `9003xx` (confirmado libre el 2026-09-24 contra `lasfocasdev-postgres`, mismo
criterio que `tests/test_prov_frescura.py`).

`test_prov_no_configurado_no_encola_nada`, `test_sin_loop_no_encola_y_sin_nota` y
`test_disparar_refresco_prov_camino_feliz_encola_de_verdad` (agregado en el round de fix, Important
5) son los únicos casos sin `@requiere_postgres_real` ni `@pytest.mark.asyncio`: los tres ejercitan
`IngresoListener._disparar_refresco_prov`, que es síncrono y no toca la DB — mismo criterio que la
Parte 1 de `test_prov_frescura.py` para lo que no necesita Postgres.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
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

_NUMEROS_DE_TEST = ("900310", "900311", "900312", "900313", "900314")

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
    # Fix final (Important D): la promesa del primer mensaje cuenta los 30 vencidos, pero el lote
    # sólo intenta el tope de 25 — los 5 restantes tienen que quedar explícitos en el mensaje de
    # seguimiento, nunca desaparecer sin figurar como éxito ni como fallo.
    texto = client_mock.chat_postMessage.call_args.kwargs["text"]
    assert "Quedan 5 pendiente(s) — volvé a pedir el comando." in texto


def test_construir_mensaje_seguimiento_agrega_pendientes_cuando_hay_tope() -> None:
    """Fix final (Important D) — unidad rápida y directa (sin Postgres) de
    `_construir_mensaje_seguimiento`: con el cable de control real (`FO-FL-1003`, 118/118
    vencidos) y el tope de 25 ya aplicado (25 intentados), el mensaje tiene que decir
    explícitamente que quedan 93 pendientes en vez de dejarlos sin mencionar."""
    exitosos = [
        refresco_prov.ResultadoServicioRefrescado(i, f"OK{i:03d}", True, None) for i in range(20)
    ]
    fallidos = [
        refresco_prov.ResultadoServicioRefrescado(100 + i, f"ERR{i:03d}", False, "timeout")
        for i in range(5)
    ]
    assert len(exitosos) + len(fallidos) == 25

    texto = refresco_prov._construir_mensaje_seguimiento(exitosos, fallidos, total_vencidos=118)

    assert "Quedan 93 pendiente(s) — volvé a pedir el comando." in texto


def test_construir_mensaje_seguimiento_sin_pendientes_no_agrega_la_linea() -> None:
    """Caso negativo — gemelo del positivo de arriba: si `total_vencidos` coincide con lo
    intentado (sin tope de por medio), no hay que prometer nada que no exista."""
    exitosos = [refresco_prov.ResultadoServicioRefrescado(1, "OK001", True, None)]

    texto = refresco_prov._construir_mensaje_seguimiento(exitosos, [], total_vencidos=1)

    assert "pendiente" not in texto


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


# ── Important 1 de la revisión de calidad: una excepción de nivel superior no puede desaparecer ─


@requiere_postgres_real
@pytest.mark.asyncio
async def test_error_no_manejado_del_lote_se_loguea_y_avisa(monkeypatch):
    """Antes de este fix, el `try` de `refrescar_servicios_vencidos` sólo tenía `finally` — una
    excepción de cualquier punto del lote (acá se simula en `priorizar_por_antiguedad`, el
    ejemplo real del hallazgo es Postgres caído/pool agotado) escapaba al
    `concurrent.futures.Future` que descarta `run_coroutine_threadsafe` en el listener: ni un
    segundo mensaje, ni una línea de log. Después del fix, se loguea `evento=error_no_manejado` Y
    se postea un segundo mensaje corto de error — nunca desaparece en silencio."""
    monkeypatch.setattr(refresco_prov, "get_prov_client", lambda: _ClientePROVFalso())

    async def _rompe(servicios: list[ServicioUnico]) -> list[ServicioUnico]:
        raise RuntimeError("Postgres caído (simulado)")

    monkeypatch.setattr(refresco_prov, "priorizar_por_antiguedad", _rompe)

    servicio = _servicio_unico(-900_151, "ERRINT")
    cable_n_id = -5_900_009
    client_mock = MagicMock()
    await refresco_prov.refrescar_servicios_vencidos(
        cable_n_id=cable_n_id,
        servicios=[servicio],
        client=client_mock,
        channel="C1",
        thread_ts="1.1",
    )

    client_mock.chat_postMessage.assert_called_once()
    texto = client_mock.chat_postMessage.call_args.kwargs["text"]
    assert "error interno inesperado" in texto
    # El candado se liberó igual (el `finally` externo sigue corriendo) — un segundo intento para
    # el mismo cable no queda bloqueado para siempre por este error.
    assert cable_n_id not in refresco_prov._cables_en_refresco


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


def test_disparar_refresco_prov_excepcion_generica_no_rompe_el_handler(monkeypatch):
    """Important 2 de la revisión de calidad: antes de este fix, `_disparar_refresco_prov` sólo
    blindaba `ProvConfigError` — cualquier otra excepción (acá se simula un `RuntimeError`
    genérico; el caso real del hallazgo es `httpx.InvalidURL` con `PROV_BASE_URL` malformado, o
    `RuntimeError: Event loop is closed` durante el shutdown del worker) subía sin blindar hasta el
    `except Exception` del handler (`_handle_servicios_cable`/`_handle_servicios_buffer`), que
    entonces no posteaba NI SIQUIERA el primer mensaje con el dato Cromo — justo lo que el brief
    pide evitar. Después del fix, cualquier excepción devuelve `(False, nota)` sin propagar."""
    listener = listener_module.IngresoListener(bot_token="xoxb-test", app_token="xapp-test", loop=MagicMock())

    def _romper_feo() -> Any:
        raise RuntimeError("Event loop is closed (simulado)")

    monkeypatch.setattr(listener_module, "get_prov_client", _romper_feo)
    espia_encolar = MagicMock()
    monkeypatch.setattr(listener_module.asyncio, "run_coroutine_threadsafe", espia_encolar)

    servicios = [_servicio_unico(-1, "X")]
    refrescando, nota = listener._disparar_refresco_prov(123, servicios, MagicMock(), "C1", "1.1")

    assert refrescando is False
    assert nota is not None and "ver logs" in nota
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

    # Sólo UN lote se ejecutó de verdad contra PROV — la segunda invocación concurrente para el
    # mismo cable se saltea el lote entero (ni una sola llamada a PROV extra, ni un segundo lote
    # redundante).
    assert len(cliente_falso.llamadas) == 2
    # Pero SÍ hay dos mensajes en total (Important 4 de la revisión de calidad): uno es el
    # resultado real del lote que sí corrió, el otro es el aviso corto al segundo hilo de que ya
    # hay un refresco en curso — sin este segundo mensaje, el segundo técnico se queda esperando
    # indefinidamente un resultado que se postea en el hilo del primero.
    mensajes_1 = [c.kwargs["text"] for c in client_mock_1.chat_postMessage.call_args_list]
    mensajes_2 = [c.kwargs["text"] for c in client_mock_2.chat_postMessage.call_args_list]
    todos_los_mensajes = mensajes_1 + mensajes_2
    assert len(todos_los_mensajes) == 2
    assert sum("refresco PROV en curso" in texto for texto in todos_los_mensajes) == 1
    assert sum("Refresco PROV completado" in texto for texto in todos_los_mensajes) == 1


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
    # NULL, no un centinela (Important 3 de la revisión de calidad — la columna es nullable desde
    # la migración `20260923_03`): "nunca sincronizado con éxito" es exactamente lo que espera la
    # consulta de frescura (`IS NULL OR ... < corte`), sin necesidad de un segundo encoding.
    assert ultima_ok is None
    assert antes <= ultimo_intento <= despues
    assert ultimo_error is not None and "PROV respondió 404" in ultimo_error
    assert nro_consultado == numero

    texto = client_mock.chat_postMessage.call_args.kwargs["text"]
    assert numero in texto
    assert "PROV respondió 404" in texto


# ── Important 5 de la revisión de calidad: el camino feliz tenía cobertura CERO ──────────────
#
# Los 6 tests de arriba que llegan a `refrescar_un_servicio` usan PKs negativos, así que
# `select(Servicio)` nunca encuentra fila y salen por el early-return de la línea ~239 ("se borró
# entre medio"), sin ejecutar nunca `ingerir_contexto_prov` ni el `commit` real. Los dos tests con
# fila real (`test_fallo_persiste_ultimo_intento_y_error`,
# `test_timeout_sin_reintentos_se_clasifica_como_timeout`) van ambos por el camino de FALLO. El
# test de acá abajo es el único que ejercita de punta a punta el propósito entero de la tarea:
# refrescar de verdad contra PROV y persistir el éxito.


@requiere_postgres_real
@pytest.mark.asyncio
async def test_camino_feliz_refresca_de_verdad_y_persiste_el_exito(monkeypatch, _limpiar_servicios_de_test):
    numero = "900312"
    pk = _crear_servicio(numero)
    servicio = _servicio_unico(pk, numero)

    # Mismo patrón de contexto mínimo que `tests/test_prov_ingesta.py::_contexto_minimo` — ya
    # probado ahí contra `ingerir_contexto_prov` real.
    contexto = {
        "id_servicio": "EWS",
        "nro_servicio": numero,
        "nro_servicio_original": numero,
        "estado_comercial": "INSTALADO",
        "Descripcion": "CLIENTE REFRESCO PROV FELIZ",
    }
    cliente_falso = _ClientePROVFalso(respuestas={numero: contexto})
    monkeypatch.setattr(refresco_prov, "get_prov_client", lambda: cliente_falso)

    antes = datetime.now(timezone.utc)
    client_mock = MagicMock()
    await refresco_prov.refrescar_servicios_vencidos(
        cable_n_id=-5_900_008,
        servicios=[servicio],
        client=client_mock,
        channel="C1",
        thread_ts="1.1",
    )
    despues = datetime.now(timezone.utc)

    # Se llamó de verdad a PROV (no el early-return de "se borró entre medio").
    assert cliente_falso.llamadas == [numero]

    with SessionLocal() as session:
        fila_servicio = session.execute(
            text("SELECT nombre_cliente, origen_datos FROM app.servicios WHERE id = :pk"),
            {"pk": pk},
        ).one()
        fila_sync = session.execute(
            text(
                "SELECT ultima_sincronizacion_ok, ultimo_error, nro_servicio_consultado "
                "FROM app.servicios_sync_prov WHERE servicio_id = :pk"
            ),
            {"pk": pk},
        ).one()

    # El Servicio quedó efectivamente actualizado con el contexto de PROV — no sólo "se reportó
    # como éxito", el `ingerir_contexto_prov` + `commit` reales corrieron.
    assert fila_servicio.nombre_cliente == "CLIENTE REFRESCO PROV FELIZ"
    assert fila_servicio.origen_datos == "INGEST_PROV"

    ultima_ok, ultimo_error, nro_consultado = fila_sync
    assert ultima_ok is not None
    assert antes <= ultima_ok <= despues  # sincronización real, nunca el NULL del camino de fallo
    assert ultimo_error is None
    assert nro_consultado == numero

    texto = client_mock.chat_postMessage.call_args.kwargs["text"]
    assert numero in texto
    assert "actualizado" in texto


@requiere_postgres_real
@pytest.mark.asyncio
async def test_priorizar_por_antiguedad_nulos_primero_y_ascendente(_limpiar_servicios_de_test):
    """`priorizar_por_antiguedad` no tenía ningún test propio — sólo se ejercitaba indirecto a
    través de `refrescar_servicios_vencidos` con servicios que nunca tenían fila previa (todos
    "nulls"). Este test verifica las dos mitades del orden: nulls (nunca intentado) primero, y
    entre los ya intentados, ascendente por `ultimo_intento` (el intentado hace más tiempo
    primero)."""
    numero_viejo = "900313"  # último intento hace 10h -> más prioridad que el reciente
    numero_reciente = "900314"  # último intento hace 1h -> menos prioridad que el viejo
    pk_viejo = _crear_servicio(numero_viejo)
    pk_reciente = _crear_servicio(numero_reciente)

    ahora = datetime.now(timezone.utc)
    with SessionLocal() as session:
        for pk, intento in (
            (pk_viejo, ahora - timedelta(hours=10)),
            (pk_reciente, ahora - timedelta(hours=1)),
        ):
            session.execute(
                text(
                    "INSERT INTO app.servicios_sync_prov "
                    "(servicio_id, ultima_sincronizacion_ok, ultimo_intento, ultimo_error, "
                    " nro_servicio_consultado, created_at, updated_at) "
                    "VALUES (:pk, NULL, :intento, 'fallo de prueba', 'x', :ahora, :ahora)"
                ),
                {"pk": pk, "intento": intento, "ahora": ahora},
            )
        session.commit()

    nunca_intentado = _servicio_unico(-900_141, "NUNCA")
    intento_viejo = _servicio_unico(pk_viejo, numero_viejo)
    intento_reciente = _servicio_unico(pk_reciente, numero_reciente)

    # Orden de entrada deliberadamente mezclado — si `priorizar_por_antiguedad` no ordenara nada,
    # este orden de entrada ya "pasaría" la aserción por casualidad para el primer elemento.
    ordenados = await refresco_prov.priorizar_por_antiguedad(
        [intento_reciente, nunca_intentado, intento_viejo]
    )

    assert [s.servicio_id_externo for s in ordenados] == ["NUNCA", numero_viejo, numero_reciente]


def test_disparar_refresco_prov_camino_feliz_encola_de_verdad(monkeypatch):
    """Complementa `test_prov_no_configurado_no_encola_nada`/`test_sin_loop_no_encola_y_sin_nota`
    (los dos caminos donde NO se encola nada): acá hay vencidos, hay loop y PROV está configurado,
    así que `_disparar_refresco_prov` tiene que devolver `refrescando=True`/`nota=None` Y
    efectivamente llamar `asyncio.run_coroutine_threadsafe` con la corrutina real y el loop del
    worker — antes de este test, el camino donde SÍ se encola no tenía ninguna cobertura directa."""
    loop_falso = MagicMock(name="loop_del_worker")
    listener = listener_module.IngresoListener(bot_token="xoxb-test", app_token="xapp-test", loop=loop_falso)

    cliente_falso = object()
    monkeypatch.setattr(listener_module, "get_prov_client", lambda: cliente_falso)

    corrutina_falsa = MagicMock(name="corrutina_refresco")
    espia_refrescar = MagicMock(return_value=corrutina_falsa)
    monkeypatch.setattr(listener_module, "refrescar_servicios_vencidos", espia_refrescar)

    espia_encolar = MagicMock()
    monkeypatch.setattr(listener_module.asyncio, "run_coroutine_threadsafe", espia_encolar)

    servicios = [_servicio_unico(-1, "X")]
    client_mock = MagicMock()
    refrescando, nota = listener._disparar_refresco_prov(123, servicios, client_mock, "C1", "1.1")

    assert refrescando is True
    assert nota is None
    espia_refrescar.assert_called_once_with(
        cable_n_id=123, servicios=servicios, client=client_mock, channel="C1", thread_ts="1.1"
    )
    espia_encolar.assert_called_once_with(corrutina_falsa, loop_falso)


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
