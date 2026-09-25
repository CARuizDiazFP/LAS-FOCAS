# Nombre de archivo: test_ingreso_correccion_service.py
# Ubicación de archivo: tests/test_ingreso_correccion_service.py
# Descripción: Pruebas del servicio de corrección "Forzar ingreso"/"Forzar egreso" (cascada del hilo, regla del momento, resolución de egreso y auditoría en todas las ramas)

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

from core.services.cromo.camara_botella_busqueda import ResultadoBusquedaExtendida
from core.services.ingreso_correccion_service import (
    CAMARA_TEXTO_DEL_HILO,
    CAMARA_TEXTO_NO_PARSEADO,
    COMANDO_FORZAR_EGRESO,
    COMANDO_FORZAR_INGRESO,
    FUENTE_MOMENTO_EXPLICITO,
    FUENTE_MOMENTO_HILO,
    RESULTADO_CAMARA_AMBIGUA,
    RESULTADO_CAMARA_NO_ENCONTRADA,
    RESULTADO_EGRESO_ANTERIOR_AL_INGRESO,
    RESULTADO_ERROR_INTERNO,
    RESULTADO_HILO_SIN_FORMULARIO,
    RESULTADO_INGRESO_NO_ENCONTRADO,
    RESULTADO_INGRESO_YA_CERRADO,
    RESULTADO_MOMENTO_INVALIDO,
    RESULTADO_OK_EGRESO_ASENTADO,
    RESULTADO_OK_EGRESO_CERRADO,
    RESULTADO_OK_INGRESO,
    RESULTADO_PENDIENTE_FECHA,
    RESULTADO_SIN_INGRESO_ABIERTO,
    RESULTADO_VARIOS_INGRESOS_ABIERTOS,
    procesar_comando_correccion,
)
from db.models.cromo import CromoBotella
from db.models.infra import Camara, Ingreso, IngresoCorreccion, IngresoSinMatch, IngresoTipo
from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError
from tests.test_ingreso_service import _assert_filtro_igualdad, _assert_filtro_null_safe

_MODULO = "core.services.ingreso_correccion_service"

# El `thread_ts` de una respuesta de Slack ES el `ts` del mensaje raíz del hilo, así que el servicio
# deriva de él el momento del formulario sin ninguna llamada de red. Se construye a partir de un
# datetime conocido para poder assertear la igualdad exacta.
MOMENTO_HILO = datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc)
THREAD_TS = f"{MOMENTO_HILO.timestamp():.6f}"
MENSAJE_TS = "1789200000.000500"
CANAL = "C0SLACKTEST"
ACTOR_ID = "U0OPERADOR1"
ACTOR_NOMBRE = "operador.qa"

# Momento de referencia para las validaciones de rango del parser (fecha futura / >90 días).
AHORA = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
# "20-09-2026 10:00" en hora de Buenos Aires (GMT-3) = 13:00 UTC.
MOMENTO_EXPLICITO = datetime(2026, 9, 20, 13, 0, tzinfo=timezone.utc)


def _form_workflow(tipo: str, nombre: str = "Cra Mitre 302 CF", con_persona: bool = True) -> str:
    """Formulario real del Workflow de Slack, con los tres campos que el servicio re-extrae."""
    persona = "Persona que solicito La Autorizacion\n<@U03DPFK0Q69|rider.fernandez>\n" if con_persona else ""
    return (
        "*Cual es el numero de Ticket MKT? o Numero de Linea*\nMKT-111111\n"
        f"*Nombre: Nodo/Camara/botella*\n{nombre}\n"
        f"*Ingreso o Egreso*\n{tipo}\n"
        f"{persona}"
    )


# ── Dobles de prueba ────────────────────────────────────────────────────────────────────────────


class _QueryStub:
    """Devuelve resultados programados para `.first()` y `.all()` en orden de llamada.

    Hace falta porque el servicio corre hasta tres consultas distintas sobre el mismo modelo
    `Ingreso` (nivel 1 de la cascada y candidatos vía `.all()`, búsqueda por `#<id>` vía `.first()`)
    y un `MagicMock` encadenado devolvería siempre lo mismo. `filter`/`order_by` se registran para
    poder asertar sobre ellos si hiciera falta."""

    def __init__(self, firsts: list[Any], alls: list[list[Any]]) -> None:
        self._firsts = list(firsts)
        self._alls = list(alls)
        self.filtros: list[tuple] = []

    def filter(self, *args: Any, **kwargs: Any) -> "_QueryStub":
        self.filtros.append(args)
        return self

    def order_by(self, *args: Any, **kwargs: Any) -> "_QueryStub":
        return self

    def first(self) -> Any:
        return self._firsts.pop(0) if self._firsts else None

    def all(self) -> list[Any]:
        return self._alls.pop(0) if self._alls else []


def _session(
    *,
    ingresos_hilo: list[Ingreso] | None = None,
    candidatos: list[Ingreso] | None = None,
    ingreso_por_id: Ingreso | None = None,
    caso: IngresoSinMatch | None = None,
) -> MagicMock:
    """Sesión de prueba con modelos ORM instanciados de verdad (patrón de `test_ingreso_service.py`)
    y `query.side_effect` discriminando por modelo (patrón de `test_slack_ingreso_listener.py`).

    `ingresos_hilo` es lo que devuelve el nivel 1 de la cascada; `candidatos`, el conjunto de
    ingresos abiertos de la cámara (ambos por `.all()`, en ese orden). `ingreso_por_id` es la fila
    que devuelve la forma `#<id>` (por `.first()`)."""
    session = MagicMock()
    stubs = {
        Ingreso: _QueryStub(
            firsts=[ingreso_por_id] if ingreso_por_id is not None else [],
            alls=[ingresos_hilo or [], candidatos or []],
        ),
        IngresoSinMatch: _QueryStub(firsts=[caso], alls=[]),
    }
    session.query.side_effect = lambda modelo: stubs.get(modelo, _QueryStub([], []))
    return session


def _client(*, replies: Any = None, replies_error: Exception | None = None) -> MagicMock:
    client = MagicMock()
    client.users_info.return_value = {"user": {"profile": {"display_name": ACTOR_NOMBRE}}}
    if replies_error is not None:
        client.conversations_replies.side_effect = replies_error
    else:
        client.conversations_replies.return_value = replies
    return client


def _camara(camara_id: int = 10, nombre: str = "Cra Mitre 302 CF") -> Camara:
    return Camara(id=camara_id, nombre=nombre)


def _botella(n_id: int = 777, nombre: str = "Bot 2 Cra Mitre 302") -> CromoBotella:
    return CromoBotella(n_id=n_id, nombre=nombre)


def _ingreso(
    ingreso_id: int = 501,
    *,
    camara: Camara | None = None,
    tipo: IngresoTipo = IngresoTipo.INGRESO,
    fecha_inicio: datetime | None = None,
    fecha_fin: datetime | None = None,
    tecnico: str | None = "rider.fernandez",
    thread_ts: str | None = None,
) -> Ingreso:
    fila = Ingreso(
        id=ingreso_id,
        camara_id=(camara.id if camara is not None else 10),
        tecnico_id=tecnico,
        tipo=tipo,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        thread_ts=thread_ts,
    )
    if camara is not None:
        fila.camara = camara
    return fila


def _caso_sin_match(texto_mensaje: str | None, caso_id: int = 33) -> IngresoSinMatch:
    return IngresoSinMatch(
        id=caso_id,
        texto_original="Cra Mitre 302 CF",
        origen="slack",
        contexto=CANAL,
        thread_ts=THREAD_TS,
        texto_mensaje=texto_mensaje,
        resuelto_via_empalme=False,
        resuelto_via_revalidacion=False,
        created_at=datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc),
    )


@contextmanager
def _entorno(
    *, busqueda: Any = None, error_busqueda: Exception | None = None, baneado: bool = False
) -> Iterator[MagicMock]:
    """Patchea las dos dependencias de DB que el servicio consume como caja negra: la búsqueda
    canónica de cámara y el contexto de baneo del grupo."""
    contexto = MagicMock()
    contexto.tiene_baneo_activo = baneado
    with patch(f"{_MODULO}.buscar_camara_o_botella_cromo") as mock_buscar, patch(
        f"{_MODULO}.get_camara_estado_contexto", return_value=contexto
    ):
        if error_busqueda is not None:
            mock_buscar.side_effect = error_busqueda
        else:
            mock_buscar.return_value = busqueda
        yield mock_buscar


def _resultado_busqueda(camara: Camara, botella: CromoBotella | None = None) -> ResultadoBusquedaExtendida:
    return ResultadoBusquedaExtendida(
        camara=camara,
        nombre_norm="cra mitre 302 cf",
        fuente="cromo_botella" if botella is not None else "camara",
        botella=botella,
    )


def _auditoria(session: MagicMock) -> IngresoCorreccion:
    """La fila de auditoría escrita en esta invocación. Que haya exactamente una es parte de la
    aserción: la tabla es append-only y cada invocación escribe una y sólo una."""
    filas = [
        llamada.args[0]
        for llamada in session.add.call_args_list
        if isinstance(llamada.args[0], IngresoCorreccion)
    ]
    assert len(filas) == 1, f"se esperaba 1 fila de auditoría, hubo {len(filas)}"
    return filas[0]


def _ingresos_escritos(session: MagicMock) -> list[Ingreso]:
    return [
        llamada.args[0]
        for llamada in session.add.call_args_list
        if isinstance(llamada.args[0], Ingreso)
    ]


def _ejecutar(
    texto: str,
    session: MagicMock,
    client: MagicMock,
    *,
    thread_ts: str | None = THREAD_TS,
    momento_explicito: datetime | None = None,
) -> Any:
    return procesar_comando_correccion(
        session,
        texto=texto,
        actor_slack_user_id=ACTOR_ID,
        canal_id=CANAL,
        mensaje_ts=MENSAJE_TS,
        thread_ts=thread_ts,
        client=client,
        momento_explicito=momento_explicito,
        ahora=AHORA,
    )


# ── Texto que no es un comando ──────────────────────────────────────────────────────────────────


class TestTextoQueNoEsComando:
    def test_mensaje_cualquiera_devuelve_none_y_no_escribe_nada(self) -> None:
        session = _session()
        resultado = _ejecutar("Cámara: Cra Mitre 302", session, _client())
        assert resultado is None
        session.add.assert_not_called()
        session.commit.assert_not_called()

    def test_forzar_algo_que_no_es_ingreso_ni_egreso_devuelve_none(self) -> None:
        session = _session()
        assert _ejecutar("Forzar reinicio del bot", session, _client()) is None
        session.add.assert_not_called()


# ── Step 1: cascada de resolución del hilo, en tres niveles ─────────────────────────────────────


class TestCascadaDelHilo:
    def test_nivel_1_usa_el_ingreso_del_hilo_sin_llamar_a_slack(self) -> None:
        """El nivel 1 da tipo, técnico y cámara desde la fila `Ingreso` del hilo (Task 2), sin una
        sola llamada de red."""
        camara = _camara()
        fila_hilo = _ingreso(
            camara=camara, tipo=IngresoTipo.INGRESO, fecha_inicio=MOMENTO_HILO, thread_ts=THREAD_TS
        )
        session = _session(ingresos_hilo=[fila_hilo], candidatos=[])
        client = _client()

        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar("Forzar ingreso Cra Mitre 302 CF", session, client)

        assert resultado.resultado == RESULTADO_OK_INGRESO
        client.conversations_replies.assert_not_called()
        fila = _auditoria(session)
        assert fila.momento_efectivo == MOMENTO_HILO
        assert fila.fuente_momento == FUENTE_MOMENTO_HILO
        # El técnico sale de la fila del hilo, ya con el nombre resuelto por el flujo en vivo.
        assert _ingresos_escritos(session)[0].tecnico_id == "rider.fernandez"

    def test_nivel_2_usa_el_texto_del_caso_sin_match(self) -> None:
        """Sin `Ingreso` en el hilo, el nivel 2 re-extrae tipo/técnico/cámara del `texto_mensaje`
        completo guardado en `IngresoSinMatch`, tampoco sin llamadas de red."""
        camara = _camara()
        caso = _caso_sin_match(_form_workflow("Ingreso"))
        session = _session(ingresos_hilo=[], candidatos=[], caso=caso)
        client = _client()

        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar("Forzar ingreso Cra Mitre 302 CF", session, client)

        assert resultado.resultado == RESULTADO_OK_INGRESO
        client.conversations_replies.assert_not_called()
        assert _auditoria(session).fuente_momento == FUENTE_MOMENTO_HILO
        # El técnico del formulario se resolvió vía users.info con el id de la mención.
        client.users_info.assert_any_call(user="U03DPFK0Q69")

    def test_nivel_3_lee_el_mensaje_raiz_via_conversations_replies(self) -> None:
        """Hilo histórico: ni `Ingreso.thread_ts` ni `IngresoSinMatch` — el mensaje raíz llega por
        `conversations.replies`."""
        camara = _camara()
        session = _session(ingresos_hilo=[], candidatos=[])
        client = _client(
            replies={"ok": True, "messages": [{"ts": THREAD_TS, "text": _form_workflow("Ingreso")}]}
        )

        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar("Forzar ingreso Cra Mitre 302 CF", session, client)

        assert resultado.resultado == RESULTADO_OK_INGRESO
        client.conversations_replies.assert_called_once_with(
            channel=CANAL, ts=THREAD_TS, limit=1
        )
        assert _auditoria(session).momento_efectivo == MOMENTO_HILO

    @pytest.mark.parametrize(
        "kwargs_client, detalle",
        [
            ({"replies_error": RuntimeError("missing_scope: channels:history")}, "excepción"),
            ({"replies": {"ok": False, "error": "missing_scope"}}, "ok=False"),
            ({"replies": {"ok": True, "messages": []}}, "sin messages"),
            ({"replies": None}, "respuesta None"),
        ],
    )
    def test_nivel_3_degrada_con_gracia(self, kwargs_client: dict, detalle: str) -> None:
        """El scope `channels:history` puede no estar habilitado. Los tres modos de falla reales
        (excepción, `ok=False`, respuesta sin `messages`) degradan al pedido de fecha explícita —
        nunca propagan."""
        camara = _camara()
        session = _session(ingresos_hilo=[], candidatos=[])
        client = _client(**kwargs_client)

        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar("Forzar ingreso Cra Mitre 302 CF", session, client)

        assert resultado.resultado == RESULTADO_HILO_SIN_FORMULARIO, detalle
        assert "fecha" in resultado.respuesta.lower()
        assert _ingresos_escritos(session) == []
        assert _auditoria(session).resultado == RESULTADO_HILO_SIN_FORMULARIO

    def test_ok_false_loguea_el_aviso_de_scope_faltante(self, caplog: Any) -> None:
        """El `ok=False` tiene su propio guard (y no sólo el catch-all) para dejar en el log una
        pista accionable: el modo de falla más probable es el scope que hay que habilitar a mano en
        el panel de la Slack App."""
        camara = _camara()
        session = _session(ingresos_hilo=[], candidatos=[])
        client = _client(replies={"ok": False, "error": "missing_scope"})

        with caplog.at_level(logging.WARNING, logger="slack_baneo_worker.ingreso_correccion"):
            with _entorno(busqueda=_resultado_busqueda(camara)):
                resultado = _ejecutar("Forzar ingreso Cra Mitre 302 CF", session, client)

        assert resultado.resultado == RESULTADO_HILO_SIN_FORMULARIO
        assert "channels:history" in caplog.text

    def test_comando_fuera_de_un_hilo_no_consulta_el_hilo(self) -> None:
        camara = _camara()
        session = _session(candidatos=[])
        client = _client()

        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar(
                "Forzar ingreso Cra Mitre 302 CF", session, client, thread_ts=None
            )

        assert resultado.resultado == RESULTADO_HILO_SIN_FORMULARIO
        client.conversations_replies.assert_not_called()

    def test_hilo_multibotella_no_adivina_la_camara_en_la_forma_bare(self) -> None:
        """Un mensaje multi-botella deja varias filas `Ingreso` con el mismo `thread_ts`: la cámara
        del hilo es ambigua y la forma bare no puede elegir una."""
        cam_a = _camara(10, "Bot 1 Cra Mitre 302")
        cam_b = _camara(11, "Bot 2 Cra Mitre 302")
        session = _session(
            ingresos_hilo=[
                _ingreso(1, camara=cam_a, tipo=IngresoTipo.EGRESO, fecha_fin=MOMENTO_HILO),
                _ingreso(2, camara=cam_b, tipo=IngresoTipo.EGRESO, fecha_fin=MOMENTO_HILO),
            ]
        )

        with _entorno():
            resultado = _ejecutar("Forzar egreso", session, _client())

        assert resultado.resultado == RESULTADO_CAMARA_AMBIGUA
        assert "Bot 1 Cra Mitre 302" in resultado.respuesta
        assert "Bot 2 Cra Mitre 302" in resultado.respuesta
        assert _auditoria(session).camara_texto_solicitado == CAMARA_TEXTO_DEL_HILO

    def test_dos_ingresos_de_la_misma_camara_en_el_hilo_no_es_ambigua_cae_en_varios_abiertos(
        self,
    ) -> None:
        """`Forzar ingreso` no tiene guard contra la repetición (decisión de producto deliberada:
        dos técnicos en la misma cámara es legítimo). Dos ejecuciones en el mismo hilo dejan dos
        filas `Ingreso` de la MISMA cámara con el mismo `thread_ts` — eso no es una cámara ambigua,
        es una sola cámara con dos ingresos abiertos, y el `Forzar egreso` siguiente debe
        resolverla y caer en `VARIOS_INGRESOS_ABIERTOS` (Step 4), nunca en `CAMARA_AMBIGUA` con el
        mismo nombre listado dos veces.

        Como las dos filas del hilo son de tipo Ingreso, forzar un Egreso sin fecha exige fecha
        explícita por la regla del momento implícito (Step 3, ortogonal a este bug) — se simula acá
        la reejecución con `momento_explicito` (Task 6) para aislar exactamente el punto que este
        test verifica: la resolución de cámara y candidatos. La cámara se resuelve ANTES que el
        momento en el código real, así que el bug (`CAMARA_AMBIGUA`) se dispara igual si no está
        arreglado, con o sin `momento_explicito` — lo confirma la mutación de abajo."""
        camara = _camara()
        ingreso_a = _ingreso(
            101, camara=camara, fecha_inicio=datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)
        )
        ingreso_b = _ingreso(
            102, camara=camara, fecha_inicio=datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
        )
        session = _session(ingresos_hilo=[ingreso_a, ingreso_b], candidatos=[ingreso_a, ingreso_b])

        with _entorno():
            resultado = _ejecutar(
                "Forzar egreso", session, _client(), momento_explicito=MOMENTO_EXPLICITO
            )

        assert resultado.resultado == RESULTADO_VARIOS_INGRESOS_ABIERTOS
        assert "#101" in resultado.respuesta and "#102" in resultado.respuesta
        assert _auditoria(session).camara_texto_solicitado == CAMARA_TEXTO_DEL_HILO
        assert _ingresos_escritos(session) == []


# ── Step 3: las cuatro filas de la tabla del momento implícito ──────────────────────────────────


class TestReglaDelMomentoImplicito:
    def test_hilo_ingreso_forzar_ingreso_toma_el_ts_del_hilo(self) -> None:
        camara = _camara()
        session = _session(
            ingresos_hilo=[_ingreso(camara=camara, fecha_inicio=MOMENTO_HILO, thread_ts=THREAD_TS)],
            candidatos=[],
        )
        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar("Forzar ingreso Cra Mitre 302 CF", session, _client())

        assert resultado.resultado == RESULTADO_OK_INGRESO
        fila = _auditoria(session)
        assert fila.fuente_momento == FUENTE_MOMENTO_HILO
        assert fila.momento_efectivo == MOMENTO_HILO
        assert fila.momento_solicitado is None
        assert _ingresos_escritos(session)[0].fecha_inicio == MOMENTO_HILO

    def test_hilo_egreso_forzar_egreso_toma_el_ts_del_hilo(self) -> None:
        camara = _camara()
        abierto = _ingreso(
            77, camara=camara, fecha_inicio=datetime(2026, 9, 22, 11, 0, tzinfo=timezone.utc)
        )
        session = _session(
            ingresos_hilo=[
                _ingreso(5, camara=camara, tipo=IngresoTipo.EGRESO, fecha_fin=MOMENTO_HILO)
            ],
            candidatos=[abierto],
        )
        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar("Forzar egreso Cra Mitre 302 CF", session, _client())

        assert resultado.resultado == RESULTADO_OK_EGRESO_CERRADO
        assert abierto.fecha_fin == MOMENTO_HILO
        assert _auditoria(session).fuente_momento == FUENTE_MOMENTO_HILO

    def test_hilo_ingreso_forzar_egreso_exige_fecha_explicita(self) -> None:
        """El caso operativo que más importa: el ingreso quedó abierto porque el formulario de
        egreso nunca llegó. Usar el `ts` del hilo registraría una visita de duración cero."""
        camara = _camara()
        session = _session(
            ingresos_hilo=[_ingreso(camara=camara, fecha_inicio=MOMENTO_HILO, thread_ts=THREAD_TS)],
            candidatos=[_ingreso(77, camara=camara, fecha_inicio=MOMENTO_HILO)],
        )
        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar("Forzar egreso Cra Mitre 302 CF", session, _client())

        assert resultado.resultado == RESULTADO_PENDIENTE_FECHA
        assert "egreso" in resultado.respuesta
        assert "DD-MM-AAAA HH:MM" in resultado.respuesta
        assert _ingresos_escritos(session) == []
        fila = _auditoria(session)
        assert fila.momento_efectivo is None and fila.fuente_momento is None

    def test_el_pedido_de_fecha_se_audita_como_estado_pendiente_no_como_rechazo(self) -> None:
        """Contrato cruzado con la Task 6: su guard de 30 minutos busca el string literal
        `'PENDIENTE_FECHA'` en `app.ingresos_correcciones.resultado`. Si alguien renombra la
        constante o su valor, el seguimiento deja de encontrar la fila y el flujo muere en silencio
        — por eso se assertea el literal, no sólo la constante."""
        assert RESULTADO_PENDIENTE_FECHA == "PENDIENTE_FECHA"

        camara = _camara()
        session = _session(
            ingresos_hilo=[_ingreso(camara=camara, fecha_inicio=MOMENTO_HILO, thread_ts=THREAD_TS)],
            candidatos=[_ingreso(77, camara=camara, fecha_inicio=MOMENTO_HILO)],
        )
        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar("Forzar egreso Cra Mitre 302 CF", session, _client())

        fila = _auditoria(session)
        assert fila.resultado == "PENDIENTE_FECHA"
        assert resultado.resultado == "PENDIENTE_FECHA"
        # Es un estado pendiente, no un movimiento: nada se escribió en app.ingresos, y el hilo
        # queda identificado para que la respuesta de seguimiento lo encuentre.
        assert _ingresos_escritos(session) == []
        assert fila.thread_ts == THREAD_TS
        assert fila.comando_crudo == "Forzar egreso Cra Mitre 302 CF"

    def test_hilo_egreso_forzar_ingreso_exige_fecha_explicita(self) -> None:
        camara = _camara()
        session = _session(
            ingresos_hilo=[
                _ingreso(5, camara=camara, tipo=IngresoTipo.EGRESO, fecha_fin=MOMENTO_HILO)
            ],
            candidatos=[],
        )
        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar("Forzar ingreso Cra Mitre 302 CF", session, _client())

        assert resultado.resultado == RESULTADO_PENDIENTE_FECHA
        assert "ingreso" in resultado.respuesta
        assert _ingresos_escritos(session) == []

    def test_fecha_explicita_gana_sobre_el_hilo(self) -> None:
        camara = _camara()
        session = _session(
            ingresos_hilo=[_ingreso(camara=camara, fecha_inicio=MOMENTO_HILO, thread_ts=THREAD_TS)],
            candidatos=[],
        )
        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar(
                "Forzar ingreso Cra Mitre 302 CF 20-09-2026 10:00", session, _client()
            )

        assert resultado.resultado == RESULTADO_OK_INGRESO
        fila = _auditoria(session)
        assert fila.momento_efectivo == MOMENTO_EXPLICITO
        assert fila.momento_solicitado == MOMENTO_EXPLICITO
        assert fila.fuente_momento == FUENTE_MOMENTO_EXPLICITO

    def test_momento_explicito_de_seguimiento_destraba_el_caso_pendiente(self) -> None:
        """Hook del flujo de "fecha pendiente" de la Task 6: el operador contesta en el hilo sólo
        con `DD-MM-AAAA HH:MM` y el comando original se re-ejecuta con ese momento."""
        camara = _camara()
        abierto = _ingreso(77, camara=camara, fecha_inicio=datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc))
        session = _session(
            ingresos_hilo=[_ingreso(camara=camara, fecha_inicio=MOMENTO_HILO, thread_ts=THREAD_TS)],
            candidatos=[abierto],
        )
        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar(
                "Forzar egreso Cra Mitre 302 CF",
                session,
                _client(),
                momento_explicito=MOMENTO_EXPLICITO,
            )

        assert resultado.resultado == RESULTADO_OK_EGRESO_CERRADO
        assert abierto.fecha_fin == MOMENTO_EXPLICITO
        assert _auditoria(session).fuente_momento == FUENTE_MOMENTO_EXPLICITO

    @pytest.mark.parametrize(
        "comando",
        [
            "Forzar ingreso Cra Mitre 302 CF 25-09-2026 10:00",  # futura
            "Forzar egreso Cra Mitre 302 CF 32-09-2026 10:00",  # formato
            "Forzar ingreso Cra Mitre 302 CF 20-09-2024 10:00",  # fuera de rango (>90 días)
        ],
    )
    def test_momento_invalido_se_rechaza_y_se_audita(self, comando: str) -> None:
        session = _session()
        with _entorno():
            resultado = _ejecutar(comando, session, _client())

        assert resultado.resultado == RESULTADO_MOMENTO_INVALIDO
        fila = _auditoria(session)
        assert fila.resultado == RESULTADO_MOMENTO_INVALIDO
        assert fila.error_detalle
        # Ruling 6: la columna es NOT NULL y el nombre de cámara nunca llegó a parsearse.
        assert fila.camara_texto_solicitado == CAMARA_TEXTO_NO_PARSEADO
        assert fila.comando_crudo == comando
        assert _ingresos_escritos(session) == []


# ── Step 4: las cuatro formas de "Forzar egreso" ────────────────────────────────────────────────


class TestFormasDeForzarEgreso:
    def _hilo_egreso(self, camara: Camara) -> Ingreso:
        return _ingreso(5, camara=camara, tipo=IngresoTipo.EGRESO, fecha_fin=MOMENTO_HILO)

    def test_forma_bare_resuelve_camara_y_momento_desde_el_hilo(self) -> None:
        camara = _camara()
        abierto = _ingreso(77, camara=camara, fecha_inicio=datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc))
        session = _session(ingresos_hilo=[self._hilo_egreso(camara)], candidatos=[abierto])

        with _entorno() as mock_buscar:
            resultado = _ejecutar("Forzar egreso", session, _client())

        assert resultado.resultado == RESULTADO_OK_EGRESO_CERRADO
        # La cámara vino del nivel 1, no de una búsqueda por texto.
        mock_buscar.assert_not_called()
        assert abierto.fecha_fin == MOMENTO_HILO
        assert _auditoria(session).camara_texto_solicitado == CAMARA_TEXTO_DEL_HILO

    def test_forma_camara_sin_fecha_en_hilo_de_egreso_cierra(self) -> None:
        camara = _camara()
        abierto = _ingreso(77, camara=camara, fecha_inicio=datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc))
        session = _session(ingresos_hilo=[self._hilo_egreso(camara)], candidatos=[abierto])

        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar("Forzar egreso Cra Mitre 302 CF", session, _client())

        assert resultado.resultado == RESULTADO_OK_EGRESO_CERRADO
        assert _auditoria(session).camara_texto_solicitado == "Cra Mitre 302 CF"

    def test_forma_camara_con_fecha_asienta_cuando_no_hay_nada_abierto(self) -> None:
        """Única forma que puede asentar un egreso de cero: cámara y fecha explícitas. Acá sí se
        deja que `registrar_movimiento_ingreso` corra de verdad, para verificar que la fila huérfana
        (`fecha_inicio=None`) se crea realmente."""
        camara = _camara()
        session = _session(ingresos_hilo=[], candidatos=[])

        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar(
                "Forzar egreso Cra Mitre 302 CF 20-09-2026 10:00", session, _client()
            )

        assert resultado.resultado == RESULTADO_OK_EGRESO_ASENTADO
        escritos = _ingresos_escritos(session)
        assert len(escritos) == 1
        assert escritos[0].tipo == IngresoTipo.EGRESO
        assert escritos[0].fecha_inicio is None
        assert escritos[0].fecha_fin == MOMENTO_EXPLICITO
        assert escritos[0].thread_ts == THREAD_TS

    def test_forma_por_id_cierra_exactamente_esa_fila(self) -> None:
        camara = _camara()
        objetivo = _ingreso(
            904, camara=camara, fecha_inicio=datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
        )
        session = _session(ingresos_hilo=[self._hilo_egreso(camara)], ingreso_por_id=objetivo)

        with _entorno() as mock_buscar:
            resultado = _ejecutar("Forzar egreso #904", session, _client())

        assert resultado.resultado == RESULTADO_OK_EGRESO_CERRADO
        assert objetivo.fecha_fin == MOMENTO_HILO
        mock_buscar.assert_not_called()
        # Ruling 6: la forma `#<id>` no nombra cámara — se audita con el id real, nunca vacío.
        assert _auditoria(session).camara_texto_solicitado == "#904"
        assert _ingresos_escritos(session) == []

    def test_forma_por_id_inexistente_se_rechaza(self) -> None:
        session = _session(ingresos_hilo=[], ingreso_por_id=None)
        with _entorno():
            resultado = _ejecutar("Forzar egreso #12345", session, _client())

        assert resultado.resultado == RESULTADO_INGRESO_NO_ENCONTRADO
        assert _auditoria(session).camara_texto_solicitado == "#12345"

    def test_forma_por_id_de_un_intento_bloqueado_no_se_cierra(self) -> None:
        """Un `INTENTO_BLOQUEADO` también tiene `fecha_fin IS NULL` pero nunca fue un ingreso real."""
        camara = _camara()
        bloqueado = _ingreso(
            904, camara=camara, tipo=IngresoTipo.INTENTO_BLOQUEADO, fecha_inicio=MOMENTO_HILO
        )
        session = _session(ingresos_hilo=[], ingreso_por_id=bloqueado)
        with _entorno():
            resultado = _ejecutar("Forzar egreso #904", session, _client())

        assert resultado.resultado == RESULTADO_INGRESO_NO_ENCONTRADO
        assert bloqueado.fecha_fin is None

    def test_forma_por_id_ya_cerrado_se_rechaza(self) -> None:
        camara = _camara()
        cerrado = _ingreso(
            904,
            camara=camara,
            fecha_inicio=datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc),
            fecha_fin=datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc),
        )
        session = _session(ingresos_hilo=[], ingreso_por_id=cerrado)
        with _entorno():
            resultado = _ejecutar("Forzar egreso #904", session, _client())

        assert resultado.resultado == RESULTADO_INGRESO_YA_CERRADO
        assert "904" in resultado.respuesta
        assert cerrado.fecha_fin == datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)


class TestResolucionDelEgresoSinFallbackImplicito:
    def test_sin_ingresos_abiertos_las_formas_implicitas_no_crean_huerfana(self) -> None:
        """La regla más importante de la tarea: `registrar_movimiento_ingreso("Egreso")` crearía una
        fila EGRESO huérfana. La forma implícita nunca llega a llamarla."""
        camara = _camara()
        session = _session(
            ingresos_hilo=[
                _ingreso(5, camara=camara, tipo=IngresoTipo.EGRESO, fecha_fin=MOMENTO_HILO)
            ],
            candidatos=[],
        )
        with _entorno(busqueda=_resultado_busqueda(camara)), patch(
            f"{_MODULO}.registrar_movimiento_ingreso"
        ) as mock_registrar:
            resultado = _ejecutar("Forzar egreso Cra Mitre 302 CF", session, _client())

        assert resultado.resultado == RESULTADO_SIN_INGRESO_ABIERTO
        mock_registrar.assert_not_called()
        assert _ingresos_escritos(session) == []

    def test_varios_ingresos_abiertos_se_listan_y_no_se_adivina(self) -> None:
        camara = _camara()
        abiertos = [
            _ingreso(77, camara=camara, fecha_inicio=datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc), tecnico="rider.fernandez"),
            _ingreso(78, camara=camara, fecha_inicio=datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc), tecnico=None),
        ]
        session = _session(
            ingresos_hilo=[
                _ingreso(5, camara=camara, tipo=IngresoTipo.EGRESO, fecha_fin=MOMENTO_HILO)
            ],
            candidatos=abiertos,
        )
        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar("Forzar egreso Cra Mitre 302 CF", session, _client())

        assert resultado.resultado == RESULTADO_VARIOS_INGRESOS_ABIERTOS
        assert "#77" in resultado.respuesta and "#78" in resultado.respuesta
        assert "Forzar egreso #" in resultado.respuesta
        assert all(i.fecha_fin is None for i in abiertos)
        assert _ingresos_escritos(session) == []

    def test_egreso_anterior_al_ingreso_se_rechaza_mostrando_la_fecha_real(self) -> None:
        camara = _camara()
        fecha_inicio = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        abierto = _ingreso(77, camara=camara, fecha_inicio=fecha_inicio)
        session = _session(ingresos_hilo=[], candidatos=[abierto])

        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar(
                "Forzar egreso Cra Mitre 302 CF 20-09-2026 10:00", session, _client()
            )

        assert resultado.resultado == RESULTADO_EGRESO_ANTERIOR_AL_INGRESO
        assert "21/09/2026 09:00" in resultado.respuesta  # fecha_inicio real, en GMT-3
        assert abierto.fecha_fin is None

    def test_egreso_igual_al_ingreso_se_rechaza_la_comparacion_es_estricta(self) -> None:
        camara = _camara()
        abierto = _ingreso(77, camara=camara, fecha_inicio=MOMENTO_EXPLICITO)
        session = _session(ingresos_hilo=[], candidatos=[abierto])

        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar(
                "Forzar egreso Cra Mitre 302 CF 20-09-2026 10:00", session, _client()
            )

        assert resultado.resultado == RESULTADO_EGRESO_ANTERIOR_AL_INGRESO
        assert abierto.fecha_fin is None

    def test_fecha_inicio_naive_no_rompe_la_comparacion(self) -> None:
        """Una fila histórica podría venir naive; comparar naive contra aware lanza `TypeError`."""
        camara = _camara()
        abierto = _ingreso(77, camara=camara, fecha_inicio=datetime(2026, 9, 19, 12, 0))
        session = _session(ingresos_hilo=[], candidatos=[abierto])

        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar(
                "Forzar egreso Cra Mitre 302 CF 20-09-2026 10:00", session, _client()
            )

        assert resultado.resultado == RESULTADO_OK_EGRESO_CERRADO
        assert abierto.fecha_fin == MOMENTO_EXPLICITO

    def test_bare_con_momento_explicito_y_cero_candidatos_no_asienta_huerfana(self) -> None:
        """Mitad del guard `deliberada` (`cmd.camara_texto is not None and momento.fuente ==
        FUENTE_MOMENTO_EXPLICITO`) que no tenía cobertura propia: sólo la forma con cámara Y fecha
        explícitas puede asentar de cero. Se alcanza en producción por el flujo de la Task 6: bare
        `Forzar egreso` en un hilo de Ingreso → `PENDIENTE_FECHA` → el operador contesta sólo
        `DD-MM-AAAA HH:MM` → re-ejecución con el `comando_crudo` bare guardado y
        `fuente="explicito"` — si mientras tanto alguien más ya cerró el ingreso, quedan 0
        candidatos. Sacar la mitad `cmd.camara_texto is not None` del guard crea acá una fila
        EGRESO huérfana con el resto de la suite en verde."""
        camara = _camara()
        session = _session(
            ingresos_hilo=[_ingreso(camara=camara, fecha_inicio=MOMENTO_HILO, thread_ts=THREAD_TS)],
            candidatos=[],
        )
        with _entorno(), patch(f"{_MODULO}.registrar_movimiento_ingreso") as mock_registrar:
            resultado = _ejecutar(
                "Forzar egreso", session, _client(), momento_explicito=MOMENTO_EXPLICITO
            )

        assert resultado.resultado == RESULTADO_SIN_INGRESO_ABIERTO
        mock_registrar.assert_not_called()
        assert _ingresos_escritos(session) == []
        assert _auditoria(session).fuente_momento == FUENTE_MOMENTO_EXPLICITO


# ── Filtros SQL (Step 1 y Step 4): `_QueryStub` ignora el WHERE, hay que asertarlo a mano ────────


class TestFiltrosSQLDeIngresosAbiertos:
    """`_QueryStub.filter` guarda los filtros pero el stub devuelve las listas programadas
    ignorando el `WHERE` por completo — sin asertar la EXPRESIÓN que llega a `.filter()`, romper
    cualquiera de estos filtros no hace fallar ningún test funcional. Mismo idioma que
    `test_ingreso_service.py` (`_assert_filtro_null_safe`/`_assert_filtro_igualdad`), que ya existe
    para exactamente este propósito."""

    def _filtros_planos(self, session: MagicMock) -> list:
        # `session.query(Ingreso)` devuelve el MISMO `_QueryStub` que ya usó el código bajo prueba
        # (está indexado por modelo en `_session`), así que esto no dispara ninguna consulta nueva.
        stub = session.query(Ingreso)
        return [expr for llamada in stub.filtros for expr in llamada]

    def test_ingresos_abiertos_filtra_camara_id_tipo_ingreso_y_fecha_fin_null(self) -> None:
        """El filtro que más importa: sin `tipo == INGRESO`, un `INTENTO_BLOQUEADO` (que también
        tiene `fecha_fin IS NULL`) entraría al conjunto de candidatos y se "cerraría" como si fuera
        un ingreso real."""
        camara = _camara()
        abierto = _ingreso(
            77, camara=camara, fecha_inicio=datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)
        )
        session = _session(
            ingresos_hilo=[
                _ingreso(5, camara=camara, tipo=IngresoTipo.EGRESO, fecha_fin=MOMENTO_HILO)
            ],
            candidatos=[abierto],
        )
        with _entorno(busqueda=_resultado_busqueda(camara)):
            _ejecutar("Forzar egreso Cra Mitre 302 CF", session, _client())

        filtros = self._filtros_planos(session)
        _assert_filtro_igualdad(filtros, "camara_id", camara.id)
        _assert_filtro_igualdad(filtros, "tipo", IngresoTipo.INGRESO)
        _assert_filtro_null_safe(filtros, "fecha_fin", None)

    def test_nivel_1_de_la_cascada_filtra_por_thread_ts_exacto(self) -> None:
        camara = _camara()
        session = _session(
            ingresos_hilo=[_ingreso(camara=camara, fecha_inicio=MOMENTO_HILO, thread_ts=THREAD_TS)],
            candidatos=[],
        )
        with _entorno(busqueda=_resultado_busqueda(camara)):
            _ejecutar("Forzar ingreso Cra Mitre 302 CF", session, _client())

        filtros = self._filtros_planos(session)
        _assert_filtro_igualdad(filtros, "thread_ts", THREAD_TS)


# ── Step 2 y Step 5: técnico, baneo y marcado del caso pendiente ────────────────────────────────


class TestForzarIngreso:
    def test_ok_con_fecha_explicita_registra_fila_nueva(self) -> None:
        camara = _camara()
        botella = _botella()
        session = _session(ingresos_hilo=[], candidatos=[])

        with _entorno(busqueda=_resultado_busqueda(camara, botella)):
            resultado = _ejecutar(
                "Forzar ingreso Bot 2 Cra Mitre 302 20-09-2026 10:00", session, _client()
            )

        assert resultado.resultado == RESULTADO_OK_INGRESO
        escritos = _ingresos_escritos(session)
        assert len(escritos) == 1
        assert escritos[0].tipo == IngresoTipo.INGRESO
        assert escritos[0].fecha_inicio == MOMENTO_EXPLICITO
        assert escritos[0].fecha_fin is None
        assert escritos[0].cromo_botella_id == botella.n_id
        assert escritos[0].thread_ts == THREAD_TS and escritos[0].canal_id == CANAL
        fila = _auditoria(session)
        assert fila.camara_id_resuelta == camara.id
        assert fila.cromo_botella_id_resuelta == botella.n_id
        assert fila.actor_slack_user_id == ACTOR_ID and fila.actor_nombre == ACTOR_NOMBRE

    def test_sobre_grupo_baneado_registra_ingreso_real_y_avisa(self) -> None:
        """Decisión deliberada: el operador afirma que el técnico entró, y el baneo de *ahora* no es
        evidencia sobre el pasado. Nunca `INTENTO_BLOQUEADO`."""
        camara = _camara()
        session = _session(ingresos_hilo=[], candidatos=[])

        with _entorno(busqueda=_resultado_busqueda(camara), baneado=True):
            resultado = _ejecutar(
                "Forzar ingreso Cra Mitre 302 CF 20-09-2026 10:00", session, _client()
            )

        assert resultado.resultado == RESULTADO_OK_INGRESO
        escritos = _ingresos_escritos(session)
        assert escritos[0].tipo == IngresoTipo.INGRESO
        assert "baneado en este momento" in resultado.respuesta

    def test_tecnico_no_identificado_no_bloquea_y_se_dice_en_la_respuesta(self) -> None:
        camara = _camara()
        caso = _caso_sin_match(_form_workflow("Ingreso", con_persona=False))
        session = _session(ingresos_hilo=[], candidatos=[], caso=caso)

        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar("Forzar ingreso Cra Mitre 302 CF", session, _client())

        assert resultado.resultado == RESULTADO_OK_INGRESO
        assert _ingresos_escritos(session)[0].tecnico_id is None
        assert "No pude identificar al técnico" in resultado.respuesta

    def test_camara_ambigua_se_rechaza_con_los_candidatos(self) -> None:
        session = _session(ingresos_hilo=[], candidatos=[])
        error = AmbiguousSearchError("Mitre", 3, ["Cra Mitre 302", "Cra Mitre 440", "Bot 2 Mitre"])

        with _entorno(error_busqueda=error):
            resultado = _ejecutar("Forzar ingreso Mitre 20-09-2026 10:00", session, _client())

        assert resultado.resultado == RESULTADO_CAMARA_AMBIGUA
        assert "Cra Mitre 440" in resultado.respuesta
        fila = _auditoria(session)
        assert fila.camara_id_resuelta is None
        assert fila.momento_solicitado == MOMENTO_EXPLICITO

    def test_camara_sin_match_se_rechaza(self) -> None:
        session = _session(ingresos_hilo=[], candidatos=[])
        vacio = ResultadoBusquedaExtendida(camara=None, nombre_norm="x", fuente=None, botella=None)

        with _entorno(busqueda=vacio):
            resultado = _ejecutar(
                "Forzar ingreso Cra Inexistente 999 20-09-2026 10:00", session, _client()
            )

        assert resultado.resultado == RESULTADO_CAMARA_NO_ENCONTRADA
        assert _ingresos_escritos(session) == []

    def test_marca_el_caso_sin_match_del_hilo_como_resuelto(self) -> None:
        camara = _camara()
        caso = _caso_sin_match(_form_workflow("Ingreso"))
        session = _session(ingresos_hilo=[], candidatos=[], caso=caso)

        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar("Forzar ingreso Cra Mitre 302 CF", session, _client())

        assert resultado.resultado == RESULTADO_OK_INGRESO
        assert caso.resuelto_via_revalidacion is True
        assert caso.ingreso_id == _ingresos_escritos(session)[0].id

    def test_no_remarca_un_caso_ya_resuelto(self) -> None:
        camara = _camara()
        caso = _caso_sin_match(_form_workflow("Ingreso"))
        caso.resuelto_via_revalidacion = True
        caso.ingreso_id = 999
        session = _session(ingresos_hilo=[], candidatos=[], caso=caso)

        with _entorno(busqueda=_resultado_busqueda(camara)):
            _ejecutar("Forzar ingreso Cra Mitre 302 CF", session, _client())

        assert caso.ingreso_id == 999


# ── Step 5: el catch-all ERROR_INTERNO también audita, con la sesión ya rollbackeada ─────────────


class TestErrorInterno:
    def test_excepcion_inesperada_hace_rollback_y_audita_error_interno(self) -> None:
        """`ERROR_INTERNO` es el catch-all que sostiene la garantía entera de "auditoría en todos
        los caminos": cualquier excepción inesperada durante el procesamiento (acá, la búsqueda de
        cámara reventando con algo que no es `AmbiguousSearchError`) tiene que dejar la sesión
        rollbackeada ANTES de que `_finalizar` intente escribir su propia fila, y esa fila tiene
        que quedar con el resultado y el detalle del error."""
        session = _session()
        with _entorno(error_busqueda=RuntimeError("conexión a Cromo caída")):
            resultado = _ejecutar(
                "Forzar ingreso Cra Mitre 302 CF 20-09-2026 10:00", session, _client()
            )

        assert resultado.resultado == RESULTADO_ERROR_INTERNO
        assert "error interno" in resultado.respuesta.lower()
        session.rollback.assert_called_once()
        fila = _auditoria(session)
        assert fila.resultado == RESULTADO_ERROR_INTERNO
        assert "RuntimeError" in fila.error_detalle
        assert "conexión a Cromo caída" in fila.error_detalle
        assert fila.camara_texto_solicitado == CAMARA_TEXTO_NO_PARSEADO
        assert _ingresos_escritos(session) == []


# ── Step 5: auditoría en TODAS las ramas ────────────────────────────────────────────────────────


class TestAuditoriaEnTodasLasRamas:
    """Un rechazo sin rastro es un agujero en el log: cada rama escribe su fila, con `resultado`
    y `error_detalle`."""

    def _escenarios(self) -> list[tuple[str, dict, str]]:
        camara = _camara()
        hilo_ingreso = [_ingreso(camara=camara, fecha_inicio=MOMENTO_HILO, thread_ts=THREAD_TS)]
        hilo_egreso = [_ingreso(5, camara=camara, tipo=IngresoTipo.EGRESO, fecha_fin=MOMENTO_HILO)]
        abierto = _ingreso(77, camara=camara, fecha_inicio=datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc))
        return [
            (
                "Forzar ingreso Cra Mitre 302 CF",
                {"ingresos_hilo": hilo_ingreso, "candidatos": []},
                RESULTADO_OK_INGRESO,
            ),
            (
                "Forzar egreso Cra Mitre 302 CF",
                {"ingresos_hilo": hilo_egreso, "candidatos": [abierto]},
                RESULTADO_OK_EGRESO_CERRADO,
            ),
            (
                "Forzar egreso Cra Mitre 302 CF 20-09-2026 10:00",
                {"ingresos_hilo": [], "candidatos": []},
                RESULTADO_OK_EGRESO_ASENTADO,
            ),
            (
                "Forzar egreso Cra Mitre 302 CF",
                {"ingresos_hilo": hilo_ingreso, "candidatos": [abierto]},
                RESULTADO_PENDIENTE_FECHA,
            ),
            (
                "Forzar egreso Cra Mitre 302 CF",
                {"ingresos_hilo": [], "candidatos": []},
                RESULTADO_HILO_SIN_FORMULARIO,
            ),
            (
                "Forzar egreso Cra Mitre 302 CF",
                {"ingresos_hilo": hilo_egreso, "candidatos": []},
                RESULTADO_SIN_INGRESO_ABIERTO,
            ),
            (
                "Forzar egreso Cra Mitre 302 CF",
                {
                    "ingresos_hilo": hilo_egreso,
                    "candidatos": [
                        abierto,
                        _ingreso(78, camara=camara, fecha_inicio=MOMENTO_HILO - timedelta(hours=5)),
                    ],
                },
                RESULTADO_VARIOS_INGRESOS_ABIERTOS,
            ),
            (
                "Forzar egreso Cra Mitre 302 CF 20-09-2026 10:00",
                {
                    "ingresos_hilo": [],
                    "candidatos": [
                        _ingreso(79, camara=camara, fecha_inicio=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc))
                    ],
                },
                RESULTADO_EGRESO_ANTERIOR_AL_INGRESO,
            ),
            (
                "Forzar egreso #904",
                {
                    "ingresos_hilo": hilo_egreso,
                    "ingreso_por_id": _ingreso(
                        904,
                        camara=camara,
                        fecha_inicio=datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc),
                        fecha_fin=datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc),
                    ),
                },
                RESULTADO_INGRESO_YA_CERRADO,
            ),
            (
                "Forzar egreso #12345",
                {"ingresos_hilo": hilo_egreso},
                RESULTADO_INGRESO_NO_ENCONTRADO,
            ),
            (
                "Forzar ingreso Cra Mitre 302 CF 25-09-2026 10:00",
                {},
                RESULTADO_MOMENTO_INVALIDO,
            ),
        ]

    def test_cada_rama_escribe_exactamente_una_fila_con_su_resultado(self) -> None:
        camara = _camara()
        for texto, kwargs, esperado in self._escenarios():
            session = _session(**kwargs)
            with _entorno(busqueda=_resultado_busqueda(camara)):
                resultado = _ejecutar(texto, session, _client())

            assert resultado is not None, texto
            assert resultado.resultado == esperado, f"{texto} → {resultado.resultado}"
            fila = _auditoria(session)
            assert fila.resultado == esperado
            assert fila.comando_crudo == texto
            assert fila.comando in (COMANDO_FORZAR_INGRESO, COMANDO_FORZAR_EGRESO)
            assert fila.actor_slack_user_id == ACTOR_ID
            assert fila.canal_id == CANAL
            assert fila.mensaje_ts == MENSAJE_TS
            assert fila.thread_ts == THREAD_TS
            assert fila.camara_texto_solicitado  # NOT NULL y nunca cadena vacía
            if not esperado.startswith("OK_"):
                assert fila.error_detalle, f"{texto}: rechazo sin error_detalle"

    def test_la_respuesta_sobrevive_a_un_fallo_de_la_escritura_de_auditoria(self) -> None:
        """El movimiento ya se registró: ocultárselo al operador porque falló el log sería peor."""
        camara = _camara()
        session = _session(ingresos_hilo=[], candidatos=[])
        session.commit.side_effect = [None, RuntimeError("audit down")]

        with _entorno(busqueda=_resultado_busqueda(camara)):
            resultado = _ejecutar(
                "Forzar ingreso Cra Mitre 302 CF 20-09-2026 10:00", session, _client()
            )

        assert resultado.resultado == RESULTADO_OK_INGRESO
        assert resultado.auditoria is None
        session.rollback.assert_called()

    def test_motivo_libre_se_persiste(self) -> None:
        camara = _camara()
        session = _session(ingresos_hilo=[], candidatos=[])
        with _entorno(busqueda=_resultado_busqueda(camara)):
            _ejecutar(
                "Forzar ingreso Cra Mitre 302 CF 20-09-2026 10:00 el form se mandó tarde",
                session,
                _client(),
            )

        assert _auditoria(session).motivo == "el form se mandó tarde"
