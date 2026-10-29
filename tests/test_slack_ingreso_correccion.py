# Nombre de archivo: test_slack_ingreso_correccion.py
# Ubicación de archivo: tests/test_slack_ingreso_correccion.py
# Descripción: Tests del listener de ingresos de Slack: Forzar ingreso/egreso, fecha pendiente, orden de handlers e integración real

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

os.environ.setdefault("TESTING", "true")

from core.services.ingreso_correccion_service import RESULTADO_PENDIENTE_FECHA
from tests.soporte_postgres_real import requiere_postgres_real
from tests.soporte_slack_ingreso import _resultado_camara


# ─── Tests del wiring de "Forzar ingreso"/"Forzar egreso" (Task 6, 2026-09-23) ──


class TestReescrituraCamara(unittest.TestCase):
    """`_procesar_reescritura_camara` (2026-10-23): una persona reescribe la Cámara en el hilo de un
    `IngresoSinMatch` pendiente. Último eslabón de la cadena: después de empalme, revalidación y
    corrección. Si matchea, cierra el caso por el camino de la revalidación; si no, sigue sin
    match; la charla del hilo se ignora en silencio."""

    def _make_listener(self) -> Any:
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _event(self, text: str, user: str | None = "U0TECNICO", **extra: Any) -> dict:
        event = {"text": text, "channel": "C123", "ts": "2222.000002", "thread_ts": "1111.000001"}
        if user:
            event["user"] = user
        event.update(extra)
        return event

    def _caso(self) -> Any:
        from datetime import datetime, timezone

        caso = MagicMock()
        caso.id = 9
        caso.resuelto_via_empalme = False
        caso.resuelto_via_revalidacion = False
        caso.ingreso_id = None
        caso.texto_mensaje = "*Nombre: Nodo/Camara/botella*\nCra Mitre 404\n*Ingreso o Egreso*\nIngreso\n"
        caso.created_at = datetime(2026, 10, 23, 9, 15, tzinfo=timezone.utc)
        caso.thread_ts = "1111.000001"
        caso.contexto = "C123"
        return caso

    def _session(self, caso: Any) -> MagicMock:
        from db.models.infra import IngresoCorreccion, IngresoSinMatch

        session_mock = MagicMock()

        def _side_effect(model: Any) -> Any:
            q = MagicMock()
            if model is IngresoSinMatch:
                q.filter.return_value.order_by.return_value.first.return_value = caso
            elif model is IngresoCorreccion:
                q.filter.return_value.order_by.return_value.first.return_value = None
            return q

        session_mock.query.side_effect = _side_effect
        return session_mock

    def _correr(self, text: str, caso: Any, *, buscar: Any = None, user: str | None = "U0TECNICO",
                es_nodo: bool = False, **extra: Any):
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = self._session(caso)
        contexto_libre = CamaraEstadoContexto(
            camara_id=7, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False,
            inconsistente=False, incidentes_activos=[], ticket_baneo=None,
        )
        ingreso = MagicMock()
        ingreso.id = 501
        buscar = buscar if buscar is not None else MagicMock()
        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo", buscar),
            patch("modules.slack_baneo_notifier.listener.get_camara_estado_contexto", return_value=contexto_libre),
            patch("modules.slack_baneo_notifier.listener.resolver_nombre_tecnico", return_value="Técnico"),
            patch(
                "modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso", return_value=ingreso
            ) as mock_registrar,
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="") as mock_extraer,
            patch("modules.slack_baneo_notifier.listener.corresponde_a_nodo", return_value=es_nodo),
        ):
            listener._handle_message(self._event(text, user, **extra), client_mock)
        return client_mock, session_mock, mock_registrar, mock_extraer

    def test_reescritura_que_matchea_cierra_el_caso_con_el_horario_original(self) -> None:
        camara = MagicMock()
        camara.id = 7
        camara.nombre = "Cra Mitre 440 CF"
        caso = self._caso()
        buscar = MagicMock(return_value=_resultado_camara(camara, "cra mitre 440"))

        client_mock, session_mock, mock_registrar, mock_extraer = self._correr("Cra Mitre 440", caso, buscar=buscar)

        buscar.assert_called_once()
        self.assertEqual(buscar.call_args.args[0], "Cra Mitre 440")
        mock_extraer.assert_not_called()  # cortó antes del flujo normal
        mock_registrar.assert_called_once()
        kwargs = mock_registrar.call_args.kwargs
        self.assertIs(kwargs["camara"], camara)
        self.assertEqual(kwargs["tipo_movimiento"], "Ingreso")  # del mensaje ORIGINAL del caso
        self.assertEqual(kwargs["momento"], caso.created_at)
        self.assertEqual(kwargs["thread_ts"], "1111.000001")
        self.assertTrue(caso.resuelto_via_revalidacion)
        self.assertEqual(caso.ingreso_id, 501)
        session_mock.commit.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("Cámara corregida", texto)
        self.assertIn("Cra Mitre 440 CF", texto)
        self.assertIn("23/10/2026 09:15", texto)

    def test_reescritura_sin_match_responde_y_deja_el_caso(self) -> None:
        caso = self._caso()
        buscar = MagicMock(return_value=_resultado_camara(None, "cra mitre 9999"))

        client_mock, session_mock, mock_registrar, mock_extraer = self._correr("Cra Mitre 9999", caso, buscar=buscar)

        mock_registrar.assert_not_called()
        mock_extraer.assert_not_called()
        self.assertFalse(caso.resuelto_via_revalidacion)
        session_mock.commit.assert_not_called()
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("sigue sin match", texto)
        self.assertEqual(client_mock.chat_postMessage.call_args.kwargs["thread_ts"], "1111.000001")

    def test_reescritura_con_numero_que_no_coincide_sugiere_sin_asignar(self) -> None:
        from modules.slack_baneo_notifier.camara_search import NumeroNoCoincideError

        caso = self._caso()
        buscar = MagicMock(side_effect=NumeroNoCoincideError("Cra Mitre 404", 1, ["Cra Mitre 440 CF"]))

        client_mock, session_mock, mock_registrar, _ = self._correr("Cra Mitre 404", caso, buscar=buscar)

        mock_registrar.assert_not_called()
        self.assertFalse(caso.resuelto_via_revalidacion)
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("sigue sin match", texto)
        self.assertIn("• Cra Mitre 440 CF", texto)

    def test_charla_del_hilo_se_ignora_en_silencio(self) -> None:
        caso = self._caso()
        for texto in ("ok gracias", "dale", "👍"):
            buscar = MagicMock()
            client_mock, session_mock, mock_registrar, mock_extraer = self._correr(texto, caso, buscar=buscar)
            buscar.assert_not_called()
            client_mock.chat_postMessage.assert_not_called()
            mock_extraer.assert_not_called()  # no cae al flujo normal como un ingreso nuevo
            self.assertFalse(caso.resuelto_via_revalidacion)

    def test_ruido_real_de_hilos_de_prod_se_ignora(self) -> None:
        """Respuestas humanas reales de 6 hilos de prod (revisión 2026-10-23): con la heurística
        anterior 13 de 22 recibían "sigue sin match". Ahora ninguna se busca ni se responde."""
        caso = self._caso()
        ruido = [
            "verificando", "gracias", "ingreso ok", "ingreso para Sergio de T Y C", "GRACIAS", ":+1:",
            "ingreso ok, abriendo puerta", "Ahí abrio", "Buenas", "Hola, va a pedir el egreso?", "Si",
            "egreso ok, requiere apertura?", "No gracias", "ingreso ok, abriendo", "Listo gracias",
            "egreso ok", "Perdón Lomas de Zamora", "Bueno, ahí abro", "dale ya lo cargo",
            "<!subteam^S056XUXU5FD> me podrán abrir un momentito la puerta por favor",
            # Falsos positivos de la heurística anterior: texto corto con un número de 1 dígito.
            "sala 1", "Poste 1 frente",
            # Ronda 3: charla con números de 2 dígitos (no son una altura).
            "llego en 20 minutos", "en 10 minutos salgo", "son las 14 30 ya termine",
        ]
        for texto in ruido:
            with self.subTest(texto=texto):
                buscar = MagicMock()
                client_mock, _, _, _ = self._correr(texto, caso, buscar=buscar)
                buscar.assert_not_called()
                client_mock.chat_postMessage.assert_not_called()

    def test_nombres_reales_se_buscan(self) -> None:
        caso = self._caso()
        nombres = {
            "ingreso ok, sin id, nombre: BOT INTERNA NICARAGUA 2853 NAVE D6": "BOT INTERNA NICARAGUA 2853 NAVE D6",
            "Cra Mitre 440": "Cra Mitre 440",
            "Cra 25 de Mayo 302": "Cra 25 de Mayo 302",
            "Cra camacua 80": "Cra camacua 80",
            "Poste Colectora Oeste Panamericana": "Poste Colectora Oeste Panamericana",
            "egreso ok, nombre: Tza Florida 142 :+1:": "Tza Florida 142",
        }
        for texto, esperado in nombres.items():
            with self.subTest(texto=texto):
                buscar = MagicMock(return_value=_resultado_camara(None, "x"))
                self._correr(texto, caso, buscar=buscar)
                buscar.assert_called_once()
                self.assertEqual(buscar.call_args.args[0], esperado)

    def test_nodo_reescrito_se_ignora(self) -> None:
        caso = self._caso()
        buscar = MagicMock()
        client_mock, _, _, _ = self._correr("Nodo Pilar Centro 120", caso, buscar=buscar, es_nodo=True)
        buscar.assert_not_called()
        client_mock.chat_postMessage.assert_not_called()

    def test_evento_de_bot_no_reescribe_aunque_traiga_user(self) -> None:
        """Guard contra loops entre bots: un evento con `user` Y `bot_id`, o con un `subtype` que no
        sea `thread_broadcast`, nunca dispara la reescritura."""
        caso = self._caso()
        for extra in ({"bot_id": "B0OTRO"}, {"subtype": "bot_message"}):
            with self.subTest(extra=extra):
                buscar = MagicMock()
                self._correr("Cra Mitre 440", caso, buscar=buscar, **extra)
                buscar.assert_not_called()
        buscar = MagicMock(return_value=_resultado_camara(None, "x"))
        self._correr("Cra Mitre 440", caso, buscar=buscar, subtype="thread_broadcast")
        buscar.assert_called_once()

    def test_sin_caso_pendiente_sigue_el_flujo_normal(self) -> None:
        buscar = MagicMock()
        client_mock, _, _, mock_extraer = self._correr("Cra Mitre 440", None, buscar=buscar)
        mock_extraer.assert_called_once()  # flujo normal (extrae "" y no responde)
        buscar.assert_not_called()
        client_mock.chat_postMessage.assert_not_called()

    def test_evento_sin_user_no_reescribe(self) -> None:
        caso = self._caso()
        buscar = MagicMock()
        _, _, _, mock_extraer = self._correr("Cra Mitre 440", caso, buscar=buscar, user=None)
        buscar.assert_not_called()
        mock_extraer.assert_called_once()

    def test_comandos_conocidos_no_se_toman_como_camara(self) -> None:
        caso = self._caso()
        for texto in ("<@U0BOT> track 123456", "Info cable C-1234", "Servicios C-1234 B2", "23-10-2026 14:30"):
            buscar = MagicMock()
            self._correr(texto, caso, buscar=buscar)
            buscar.assert_not_called()
            self.assertFalse(caso.resuelto_via_revalidacion)

    def test_numero_solo_sigue_siendo_seguimiento_de_empalme(self) -> None:
        """Orden de la cadena: un número solo lo toma el seguimiento de empalme, nunca la
        reescritura."""
        caso = self._caso()
        buscar = MagicMock()
        with patch(
            "modules.slack_baneo_notifier.listener.resolver_botella_por_fusion_sync", return_value=None
        ) as mock_empalme, patch(
            "modules.slack_baneo_notifier.listener.buscar_por_id_legacy", return_value=None
        ):
            self._correr("1234567", caso, buscar=buscar)
        mock_empalme.assert_called_once()
        buscar.assert_not_called()

    def test_forzar_ingreso_lo_toma_la_correccion(self) -> None:
        caso = self._caso()
        buscar = MagicMock()
        with patch(
            "modules.slack_baneo_notifier.listener.procesar_comando_correccion", return_value=None
        ) as mock_correccion:
            self._correr("Forzar ingreso Cra Mitre 440", caso, buscar=buscar)
        mock_correccion.assert_called_once()
        buscar.assert_not_called()


class TestCorreccionIngresoWiring(unittest.TestCase):
    """Prueba `_procesar_correccion_ingreso` / su integración en `_handle_message` (Task 6): cablea
    `core/services/ingreso_correccion_service.py` (Task 5) al listener. No re-testea las 10 formas
    de respuesta del servicio (ya cubiertas en `tests/test_ingreso_correccion_service.py`) — sólo el
    wiring: qué se le pasa al servicio, qué se postea, y que nunca se rompe la respuesta."""

    def _make_listener(self) -> Any:
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event_reply(
        self, text: str, thread_ts: str = "1111.000001", ts: str = "2222.000002",
        channel: str = "C123", user: str = "U0OPERADOR",
    ) -> dict:
        return {"text": text, "channel": channel, "ts": ts, "thread_ts": thread_ts, "user": user}

    def _resultado(self, resultado: str, respuesta: str, comando: str = "FORZAR_INGRESO") -> Any:
        from core.services.ingreso_correccion_service import ResultadoCorreccion
        return ResultadoCorreccion(resultado=resultado, respuesta=respuesta, comando=comando)

    def test_comando_reconocido_responde_en_hilo(self) -> None:
        """"Forzar ingreso <CAMARA>" dentro de un hilo: se delega en `procesar_comando_correccion`
        con las coordenadas del evento y `actor_slack_user_id=event['user']` (nunca el técnico del
        formulario, que resuelve el servicio internamente), se postea `resultado.respuesta` en el
        hilo, y se corta antes del flujo normal (no llega a `extraer_nombre_camara`)."""
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        resultado = self._resultado("OK_INGRESO", "✅ Ingreso forzado registrado en *Cra Mitre 300*.")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.procesar_comando_correccion",
                return_value=resultado,
            ) as mock_procesar,
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara") as mock_extraer,
        ):
            listener._handle_message(
                self._make_event_reply("Forzar ingreso Cra Mitre 300", user="U0OPERADOR"), client_mock
            )
            mock_extraer.assert_not_called()

        mock_procesar.assert_called_once()
        kwargs = mock_procesar.call_args.kwargs
        self.assertEqual(kwargs["texto"], "Forzar ingreso Cra Mitre 300")
        self.assertEqual(kwargs["actor_slack_user_id"], "U0OPERADOR")
        self.assertEqual(kwargs["canal_id"], "C123")
        self.assertEqual(kwargs["thread_ts"], "1111.000001")
        self.assertEqual(kwargs["mensaje_ts"], "2222.000002")
        self.assertIs(kwargs["client"], client_mock)
        self.assertIsNone(kwargs.get("momento_explicito"))

        client_mock.chat_postMessage.assert_called_once()
        post_kwargs = client_mock.chat_postMessage.call_args.kwargs
        self.assertEqual(post_kwargs["thread_ts"], "1111.000001")
        self.assertEqual(post_kwargs["text"], resultado.respuesta)

    def test_pedido_fecha_pendiente_responde_en_hilo(self) -> None:
        """El pedido de fecha explícita (`RESULTADO_PENDIENTE_FECHA`) usa el mismo camino de posteo
        que un resultado OK — sin casos especiales en el listener para este resultado."""
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        resultado = self._resultado(
            "PENDIENTE_FECHA",
            ":warning: Para forzar un egreso en *Cra Mitre 300* hace falta la fecha y hora...",
            comando="FORZAR_EGRESO",
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.procesar_comando_correccion",
                return_value=resultado,
            ),
        ):
            listener._handle_message(self._make_event_reply("Forzar egreso"), client_mock)

        client_mock.chat_postMessage.assert_called_once()
        self.assertEqual(client_mock.chat_postMessage.call_args.kwargs["text"], resultado.respuesta)

    def test_texto_no_es_comando_sigue_flujo_normal(self) -> None:
        """Un mensaje que no matchea ningún comando de corrección (`procesar_comando_correccion`
        real, sin mockear, devuelve `None` sin tocar la DB) sigue de largo al flujo normal — mismo
        caso normal que cualquier otro mensaje del canal.

        Desde el Fix round 1 (Important 3) `_handle_message` consulta `IngresoCorreccion` una vez
        al entrar a cualquier hilo (chequeo de prioridad de "fecha pendiente"); acá no hay ningún
        pendiente. Desde 2026-10-23 la reescritura de la Cámara (`_procesar_reescritura_camara`)
        consulta además si hay un `IngresoSinMatch` pendiente en el hilo: no lo hay."""
        from db.models.infra import IngresoCorreccion, IngresoSinMatch

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()

        def _query_side_effect(model: Any) -> Any:
            q = MagicMock()
            if model in (IngresoCorreccion, IngresoSinMatch):
                q.filter.return_value.order_by.return_value.first.return_value = None
            return q

        session_mock.query.side_effect = _query_side_effect

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value=""
            ) as mock_extraer,
        ):
            listener._handle_message(self._make_event_reply("hola, todo bien?"), client_mock)

        mock_extraer.assert_called_once()
        client_mock.chat_postMessage.assert_not_called()
        self.assertEqual(
            [c.args[0] for c in session_mock.query.call_args_list], [IngresoCorreccion, IngresoSinMatch]
        )

    def test_fallo_db_no_impide_responder(self) -> None:
        """Si `procesar_comando_correccion` lanza (fallo de DB, p. ej.), se loguea, se hace
        `session.rollback()` (mismo contrato que `_registrar_movimiento_si_corresponde`) y se
        responde igual en el hilo — nunca se deja el comando sin respuesta ni la sesión compartida
        en `PendingRollbackError` para el resto de `_handle_message`."""
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.procesar_comando_correccion",
                side_effect=RuntimeError("DB caída"),
            ),
        ):
            listener._handle_message(
                self._make_event_reply("Forzar ingreso Cra Mitre 300"), client_mock
            )

        session_mock.rollback.assert_called_once()
        client_mock.chat_postMessage.assert_called_once()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("error interno", texto_respuesta)

    def test_evento_sin_user_no_ejecuta_correccion(self) -> None:
        """Fix final (Important B) — un evento sin `user` (los mensajes de bot/Workflow traen
        `bot_id`, no `user`) nunca tiene que llegar a `procesar_comando_correccion`: escribiría una
        fila de auditoría anónima (`actor_slack_user_id=""`), rompiendo la premisa de producto "sin
        allowlist, la auditoría es el único control". El filtro `solo_workflows` no lo ataja porque
        `_procesar_correccion_ingreso` se evalúa antes a propósito (ver comentario en
        `_handle_message`) — el guard tiene que vivir en el propio call-site."""
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        event = {
            "text": "Forzar egreso #42",
            "channel": "C123",
            "ts": "2222.000002",
            "thread_ts": "1111.000001",
            "bot_id": "B0AV5BDDUJE",
        }

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.procesar_comando_correccion"
            ) as mock_procesar,
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value=""),
        ):
            listener._handle_message(event, client_mock)

        mock_procesar.assert_not_called()


# ─── Tests del flujo de "fecha pendiente" (respuesta de seguimiento) ────────────


def _assert_order_by_desc(order_by_args: tuple, columna_attr: str) -> None:
    """Verifica que un `.order_by(...)` haya recibido `<columna_attr>.desc()` — no sólo que el
    mock ya devuelva la fila "correcta" sin importar qué orden se haya pedido (Important 4,
    revisión Fix round 1: un mock que ignora el argumento de `order_by` no distingue
    `created_at.desc()` de `id.asc()`, y una regresión a un orden distinto pasaría inadvertida).
    Mismo espíritu que `_assert_filtro_igualdad`/`_assert_filtro_null_safe` de
    `tests/test_ingreso_service.py`, aplicado a la expresión de orden en vez de a un filtro."""
    from sqlalchemy.sql import operators as sa_operators

    assert len(order_by_args) == 1, "se esperaba un solo criterio de order_by"
    expr = order_by_args[0]
    elemento = getattr(expr, "element", None)
    assert elemento is not None and getattr(elemento, "key", None) == columna_attr, (
        f"se esperaba ordenar por '{columna_attr}', se ordenó por {elemento!r}"
    )
    assert expr.modifier is sa_operators.desc_op, (
        f"se esperaba DESC (fila más reciente primero) para '{columna_attr}'"
    )


class TestFechaPendienteSeguimiento(unittest.TestCase):
    """Prueba `_procesar_fecha_pendiente_seguimiento` / `_pendiente_fecha_vigente` (Task 6): el
    operador responde en el hilo sólo con `DD-MM-AAAA HH:MM` tras el pedido de fecha explícita —
    guard estricto (ruling del coordinador): fila `PENDIENTE_FECHA` de este `thread_ts`, de menos de
    30 minutos, sin ninguna fila posterior del mismo hilo con un `resultado` terminal."""

    def _make_listener(self) -> Any:
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event_reply(
        self, text: str, thread_ts: str = "1111.000001", ts: str = "2222.000002",
        channel: str = "C123", user: str = "U0OPERADOR",
    ) -> dict:
        return {"text": text, "channel": channel, "ts": ts, "thread_ts": thread_ts, "user": user}

    def _fecha_reciente_texto(self, *, horas_atras: int = 2) -> str:
        """Fecha "DD-MM-AAAA HH:MM" siempre reciente relativa al momento real de ejecución del test
        (nunca un literal fijo): evita que la suite se rompa por la validación de rango del parser
        (futuro / más de 90 días) según cuándo se corra."""
        from datetime import datetime, timedelta
        from core.utils.tz import TZ_ARG
        momento = datetime.now(TZ_ARG) - timedelta(hours=horas_atras)
        return momento.strftime("%d-%m-%Y %H:%M")

    def _make_fila_pendiente(
        self, *, created_at: Any, comando_crudo: str = "Forzar egreso", id_: int = 77
    ) -> Any:
        fila = MagicMock()
        fila.id = id_
        fila.resultado = RESULTADO_PENDIENTE_FECHA
        fila.comando_crudo = comando_crudo
        fila.created_at = created_at
        return fila

    def _make_fila_terminal(
        self, *, created_at: Any, resultado: str = "OK_EGRESO_ASENTADO", id_: int = 78
    ) -> Any:
        fila = MagicMock()
        fila.id = id_
        fila.resultado = resultado
        fila.created_at = created_at
        return fila

    def _query_side_effect(self, ultima_fila: Any) -> tuple:
        """Arma el `side_effect` de `session.query(...)` para `IngresoCorreccion`: sólo importa la
        ÚLTIMA fila del hilo (`.order_by(created_at.desc()).first()`) — desde el Fix round 1,
        `_pendiente_fecha_vigente` dejó de traer todas las filas y recorrerlas en Python (ver el
        docstring del método: ahí vivía el bug Critical). Devuelve `(side_effect, capturas)`:
        `capturas` guarda cada mock `q` de `IngresoCorreccion` para poder inspeccionar después cómo
        se llamó `.order_by(...)` (Important 4 — ver `_assert_order_by_desc`)."""
        from db.models.infra import IngresoCorreccion

        capturas: list = []

        def _side_effect(model: Any) -> Any:
            q = MagicMock()
            if model is IngresoCorreccion:
                q.filter.return_value.order_by.return_value.first.return_value = ultima_fila
                capturas.append(q)
            return q

        return _side_effect, capturas

    def _resultado_ok(self) -> Any:
        from core.services.ingreso_correccion_service import ResultadoCorreccion
        return ResultadoCorreccion(
            resultado="OK_EGRESO_ASENTADO", respuesta="✅ Egreso asentado.", comando="FORZAR_EGRESO"
        )

    def test_ciclo_completo_fecha_suelta_con_pendiente_vigente_reejecuta_comando_original(self) -> None:
        """Fila `PENDIENTE_FECHA` reciente y sin fila terminal posterior → se reintenta
        `comando_crudo` con `momento_explicito` (nunca se muta la fila anterior: se pasa tal cual a
        `procesar_comando_correccion`, que escribe una fila nueva — la tabla es append-only)."""
        from datetime import datetime, timedelta, timezone

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()

        ahora = datetime.now(timezone.utc)
        fila_pendiente = self._make_fila_pendiente(created_at=ahora - timedelta(minutes=5))
        side_effect, capturas = self._query_side_effect(fila_pendiente)
        session_mock.query.side_effect = side_effect

        resultado_final = self._resultado_ok()

        def _procesar_side_effect(
            session, *, texto, actor_slack_user_id, canal_id, mensaje_ts,
            thread_ts=None, client=None, momento_explicito=None, ahora=None,
        ):
            # La primera llamada (¿el texto crudo del evento es un comando completo?) siempre
            # devuelve None para una fecha suelta; sólo la segunda (con `momento_explicito`, re-
            # ejecutando `comando_crudo`) produce el resultado final.
            if momento_explicito is not None:
                return resultado_final
            return None

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.procesar_comando_correccion",
                side_effect=_procesar_side_effect,
            ) as mock_procesar,
        ):
            listener._handle_message(
                self._make_event_reply(self._fecha_reciente_texto()), client_mock
            )

        self.assertEqual(mock_procesar.call_count, 2)
        segunda = mock_procesar.call_args_list[1].kwargs
        self.assertEqual(segunda["texto"], "Forzar egreso")  # comando_crudo de la fila pendiente
        self.assertIsNotNone(segunda["momento_explicito"])
        self.assertEqual(segunda["thread_ts"], "1111.000001")
        self.assertEqual(segunda["actor_slack_user_id"], "U0OPERADOR")

        # El listener nunca escribe directamente sobre la fila pendiente ni la sesión — toda
        # escritura real la hace el servicio (mockeado acá, ya probado en
        # test_ingreso_correccion_service.py).
        session_mock.add.assert_not_called()
        session_mock.commit.assert_not_called()

        # Important 4: el guard tiene que pedir la ÚLTIMA fila por `created_at DESC`, no confiar
        # en que el mock ya devuelve la fila correcta sin importar el criterio pedido.
        self.assertGreaterEqual(len(capturas), 1)
        for q in capturas:
            _assert_order_by_desc(q.filter.return_value.order_by.call_args[0], "created_at")

        client_mock.chat_postMessage.assert_called_once()
        self.assertEqual(
            client_mock.chat_postMessage.call_args.kwargs["text"], resultado_final.respuesta
        )

    def test_guard_30_minutos_expirado_no_reejecuta(self) -> None:
        """Fila `PENDIENTE_FECHA` de más de 30 minutos → la fecha suelta no se interpreta, sigue el
        flujo normal (no hay una segunda invocación de `procesar_comando_correccion`)."""
        from datetime import datetime, timedelta, timezone

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()

        ahora = datetime.now(timezone.utc)
        fila_pendiente = self._make_fila_pendiente(created_at=ahora - timedelta(minutes=31))
        side_effect, _capturas = self._query_side_effect(fila_pendiente)
        session_mock.query.side_effect = side_effect

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.procesar_comando_correccion",
                return_value=None,
            ) as mock_procesar,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value=""
            ) as mock_extraer,
        ):
            listener._handle_message(
                self._make_event_reply(self._fecha_reciente_texto()), client_mock
            )

        mock_procesar.assert_called_once()  # sólo el chequeo de "¿es un comando completo?"
        mock_extraer.assert_called_once()  # cayó al flujo normal
        client_mock.chat_postMessage.assert_not_called()

    def test_guard_ya_resuelto_no_reejecuta(self) -> None:
        """Fila `PENDIENTE_FECHA` reciente, pero con una fila posterior de `resultado` terminal en
        el mismo hilo → el pendiente ya fue resuelto (por otra respuesta u otro operador), la fecha
        suelta no se interpreta ni re-ejecuta el comando por segunda vez.

        La fila terminal es la ÚLTIMA del hilo (`created_at` mayor) — exactamente lo que
        `ORDER BY created_at DESC LIMIT 1` devolvería en un Postgres real; el mock sólo necesita esa
        última fila, no la lista completa (ver `_query_side_effect`, reescrito en el Fix round 1)."""
        from datetime import datetime, timedelta, timezone

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()

        ahora = datetime.now(timezone.utc)
        fila_terminal = self._make_fila_terminal(created_at=ahora - timedelta(minutes=8))
        side_effect, _capturas = self._query_side_effect(fila_terminal)
        session_mock.query.side_effect = side_effect

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.procesar_comando_correccion",
                return_value=None,
            ) as mock_procesar,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value=""
            ) as mock_extraer,
        ):
            listener._handle_message(
                self._make_event_reply(self._fecha_reciente_texto()), client_mock
            )

        mock_procesar.assert_called_once()
        mock_extraer.assert_called_once()
        client_mock.chat_postMessage.assert_not_called()

    def test_fecha_suelta_sin_fila_pendiente_no_hace_nada(self) -> None:
        """Ninguna fila `PENDIENTE_FECHA` para este hilo (el hilo no tiene ninguna fila en
        `IngresoCorreccion` todavía) → la fecha suelta no se interpreta, sigue el flujo normal sin
        postear nada."""
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        side_effect, _capturas = self._query_side_effect(None)
        session_mock.query.side_effect = side_effect

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.procesar_comando_correccion",
                return_value=None,
            ) as mock_procesar,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value=""
            ) as mock_extraer,
        ):
            listener._handle_message(
                self._make_event_reply(self._fecha_reciente_texto()), client_mock
            )

        mock_procesar.assert_called_once()
        mock_extraer.assert_called_once()
        client_mock.chat_postMessage.assert_not_called()

    def test_texto_que_no_es_fecha_suelta_no_reejecuta_nada(self) -> None:
        """Un mensaje que no matchea ni un comando completo ni la forma "DD-MM-AAAA HH:MM" (acá,
        sin ningún `PENDIENTE_FECHA` vigente en el hilo) sigue de largo al flujo normal sin postear
        nada. Desde la prioridad agregada en el Fix round 1 (Important 3), `_handle_message` SÍ
        consulta `IngresoCorreccion` una vez al entrar a cualquier hilo (para decidir si le da
        prioridad al seguimiento de fecha sobre el de empalme) — pero encontrando que no hay
        ningún pendiente, no pasa de ahí: ni una segunda consulta de corrección, ni ningún posteo.
        (Desde 2026-10-23 se suma la consulta de `IngresoSinMatch` pendiente de la reescritura de
        la Cámara, que acá no existe.)"""
        from db.models.infra import IngresoCorreccion, IngresoSinMatch

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        side_effect, _capturas = self._query_side_effect(None)

        def _side_effect_sin_caso(model: Any) -> Any:
            q = side_effect(model)
            if model is IngresoSinMatch:
                q.filter.return_value.order_by.return_value.first.return_value = None
            return q

        session_mock.query.side_effect = _side_effect_sin_caso

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value=""
            ) as mock_extraer,
        ):
            listener._handle_message(self._make_event_reply("sí, dale"), client_mock)

        # Sólo el chequeo de prioridad (ningún pendiente) y el de caso sin match pendiente.
        self.assertEqual(
            [c.args[0] for c in session_mock.query.call_args_list], [IngresoCorreccion, IngresoSinMatch]
        )
        client_mock.chat_postMessage.assert_not_called()
        mock_extraer.assert_called_once()

    def test_fecha_invalida_sin_pendiente_no_responde(self) -> None:
        """Texto con la forma "DD-MM-AAAA HH:MM" pero valor calendáricamente inválido, sin ningún
        pendiente en el hilo → no rompe, no responde, sigue el flujo normal."""
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        side_effect, _capturas = self._query_side_effect(None)
        session_mock.query.side_effect = side_effect

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.procesar_comando_correccion",
                return_value=None,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value=""
            ) as mock_extraer,
        ):
            listener._handle_message(self._make_event_reply("32-13-2026 25:99"), client_mock)

        mock_extraer.assert_called_once()
        client_mock.chat_postMessage.assert_not_called()

    def test_fecha_invalida_con_pendiente_vigente_responde_error(self) -> None:
        """Misma forma inválida, pero con un pendiente vigente en el hilo → sí responde (el
        operador claramente está contestando el pedido de fecha, sólo que con un valor que no sirve)
        en vez de dejarlo sin ningún aviso."""
        from datetime import datetime, timedelta, timezone

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        ahora = datetime.now(timezone.utc)
        fila_pendiente = self._make_fila_pendiente(created_at=ahora - timedelta(minutes=5))
        side_effect, _capturas = self._query_side_effect(fila_pendiente)
        session_mock.query.side_effect = side_effect

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.procesar_comando_correccion",
                return_value=None,
            ),
        ):
            listener._handle_message(self._make_event_reply("32-13-2026 25:99"), client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("No pude interpretar", texto_respuesta)


# ─── Test de orden: la fecha suelta no puede ser capturada por otro handler ────


class TestOrdenHandlersCorreccion(unittest.TestCase):
    """Pin del orden elegido entre los tres handlers de respuesta-en-hilo (Task 6): el regex de
    seguimiento de empalme exige dígitos puros (mínimo 3) y el de "Revalidar ingreso" una frase
    fija — ninguno de los dos matchea una fecha suelta "DD-MM-AAAA HH:MM" ni un comando "Forzar
    ingreso/egreso". No hay ambigüedad real entre los tres handlers, pero queda fijado con un test
    directo para que un cambio futuro de cualquiera de los dos regex no lo rompa en silencio."""

    def test_fecha_dd_mm_aaaa_hh_mm_no_matchea_regex_empalme(self) -> None:
        from modules.slack_baneo_notifier.listener import _RE_SEGUIMIENTO_EMPALME
        self.assertIsNone(_RE_SEGUIMIENTO_EMPALME.match("23-09-2026 14:30"))

    def test_fecha_dd_mm_aaaa_hh_mm_no_matchea_regex_revalidar(self) -> None:
        from modules.slack_baneo_notifier.listener import _RE_REVALIDAR_INGRESO
        self.assertIsNone(_RE_REVALIDAR_INGRESO.match("23-09-2026 14:30"))

    def test_comando_forzar_no_matchea_regex_empalme_ni_revalidar(self) -> None:
        from modules.slack_baneo_notifier.listener import _RE_SEGUIMIENTO_EMPALME, _RE_REVALIDAR_INGRESO
        self.assertIsNone(_RE_SEGUIMIENTO_EMPALME.match("Forzar ingreso Cra Mitre 300"))
        self.assertIsNone(_RE_REVALIDAR_INGRESO.match("Forzar ingreso Cra Mitre 300"))
        self.assertIsNone(_RE_SEGUIMIENTO_EMPALME.match("Forzar egreso"))
        self.assertIsNone(_RE_REVALIDAR_INGRESO.match("Forzar egreso"))

    def test_orden_real_seguimiento_empalme_se_evalua_antes_que_correccion(self) -> None:
        """Aunque no hay overlap real de regex, se fija el orden elegido en `_handle_message`: el
        seguimiento de empalme se evalúa primero — un texto puramente numérico con un
        `IngresoSinMatch` pendiente en el hilo nunca llega a `_procesar_correccion_ingreso`."""
        from modules.slack_baneo_notifier.listener import IngresoListener
        from db.models.infra import IngresoSinMatch

        listener = IngresoListener(bot_token="xoxb-test", app_token="xapp-test")
        client_mock = MagicMock()
        session_mock = MagicMock()

        caso_mock = MagicMock()
        caso_mock.id = 5
        caso_mock.resuelto_via_empalme = False

        def _side_effect(model: Any) -> Any:
            q = MagicMock()
            if model is IngresoSinMatch:
                q.filter.return_value.order_by.return_value.first.return_value = caso_mock
            return q

        session_mock.query.side_effect = _side_effect

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_botella_por_fusion_sync",
                return_value=None,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.procesar_comando_correccion"
            ) as mock_procesar,
        ):
            listener._handle_message(
                {
                    "text": "1234567",
                    "channel": "C123",
                    "ts": "2222.000002",
                    "thread_ts": "1111.000001",
                },
                client_mock,
            )

        mock_procesar.assert_not_called()

    def test_coexistencia_pendiente_fecha_vigente_le_gana_a_empalme(self) -> None:
        """Important 3 (Fix round 1): coexistencia armada explícitamente — un `IngresoSinMatch`
        pendiente (empalme) Y un `PENDIENTE_FECHA` vigente (corrección) en el MISMO hilo. Cuando
        hay un pendiente vigente, la interpretación de fecha se evalúa ANTES que el seguimiento de
        empalme, así que gana ella: `_procesar_seguimiento_empalme` ni siquiera se invoca (nunca
        se llama a `resolver_botella_por_fusion_sync`, el `caso_empalme` no se toca).

        Bajo el formato estricto actual (`DD-MM-AAAA HH:MM`) ningún string real matchea a la vez
        los dos regex (ver `TestOrdenHandlersCorreccion` arriba) — así que acá se mockea
        `extraer_momento_solo` para forzar el reconocimiento de fecha sobre un texto puramente
        numérico ("1234567", que también tiene forma de ID de empalme). Esto ejercita el
        MECANISMO de prioridad en `_handle_message` en sí, no depende de que exista hoy un string
        ambiguo — la revisión pidió la coexistencia de datos armada, no una colisión de regex."""
        from datetime import datetime, timedelta, timezone

        from core.services.ingreso_correccion_service import ResultadoCorreccion
        from db.models.infra import IngresoCorreccion, IngresoSinMatch
        from modules.slack_baneo_notifier.listener import IngresoListener

        listener = IngresoListener(bot_token="xoxb-test", app_token="xapp-test")
        client_mock = MagicMock()
        session_mock = MagicMock()

        caso_empalme = MagicMock()
        caso_empalme.id = 5
        caso_empalme.resuelto_via_empalme = False

        fila_pendiente = MagicMock()
        fila_pendiente.id = 77
        fila_pendiente.resultado = RESULTADO_PENDIENTE_FECHA
        fila_pendiente.comando_crudo = "Forzar egreso"
        fila_pendiente.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)

        def _query_side_effect(model: Any) -> Any:
            q = MagicMock()
            if model is IngresoSinMatch:
                q.filter.return_value.order_by.return_value.first.return_value = caso_empalme
            elif model is IngresoCorreccion:
                q.filter.return_value.order_by.return_value.first.return_value = fila_pendiente
            return q

        session_mock.query.side_effect = _query_side_effect

        resultado_final = ResultadoCorreccion(
            resultado="OK_EGRESO_ASENTADO",
            respuesta="✅ Egreso asentado (ganó la corrección, no el empalme).",
            comando="FORZAR_EGRESO",
        )

        def _procesar_side_effect(session, *, momento_explicito=None, **_kwargs: Any) -> Any:
            # Sólo la reinvocación con `momento_explicito` (el segundo paso del flujo de fecha
            # pendiente) produce el resultado final — mismo patrón que el resto de la suite.
            return resultado_final if momento_explicito is not None else None

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_botella_por_fusion_sync"
            ) as mock_resolver_empalme,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_momento_solo",
                return_value=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.procesar_comando_correccion",
                side_effect=_procesar_side_effect,
            ) as mock_procesar,
        ):
            listener._handle_message(
                {
                    "text": "1234567",
                    "channel": "C123",
                    "ts": "2222.000002",
                    "thread_ts": "1111.000001",
                    "user": "U0OPERADOR",
                },
                client_mock,
            )

        # La corrección ganó: el seguimiento de empalme nunca llegó a ejecutarse.
        mock_resolver_empalme.assert_not_called()
        self.assertFalse(caso_empalme.resuelto_via_empalme)

        mock_procesar.assert_called()
        client_mock.chat_postMessage.assert_called_once()
        self.assertEqual(
            client_mock.chat_postMessage.call_args.kwargs["text"], resultado_final.respuesta
        )


# ─── Test de integración real: Critical del Fix round 1 ────────────────────────


def _insertar_correccion_test(session: Any, *, thread_ts: str, resultado: str, created_at: Any, comando_crudo: str) -> Any:
    """Inserta una fila mínima válida de `IngresoCorreccion` (todas las columnas NOT NULL
    completas) para el test de integración real de abajo. `session.flush()` la envía a la DB
    dentro de la transacción abierta, sin comprometerla — nunca se llama `session.commit()`."""
    from db.models.infra import IngresoCorreccion

    fila = IngresoCorreccion(
        comando="FORZAR_EGRESO",
        actor_slack_user_id="U0TEST",
        canal_id="C_FIXROUND1_TEST",
        thread_ts=thread_ts,
        mensaje_ts="1.1",
        comando_crudo=comando_crudo,
        camara_texto_solicitado="(test)",
        resultado=resultado,
        created_at=created_at,
    )
    session.add(fila)
    session.flush()
    return fila


@requiere_postgres_real
def test_pendiente_fecha_vigente_ciclo_previo_completo_real_db() -> None:
    """Reproducción real (Postgres, sin mocks) del bug Critical del Fix round 1
    (`_pendiente_fecha_vigente`): un hilo con un ciclo previo COMPLETO (`PENDIENTE_FECHA` →
    resultado terminal) seguido de un `PENDIENTE_FECHA` nuevo y vigente —
    `[PENDIENTE_FECHA@-60min, OK_EGRESO_ASENTADO@-55min, PENDIENTE_FECHA@-5min]`, el historial
    exacto que reprodujo el hallazgo.

    La versión vieja de `_pendiente_fecha_vigente` recorría todas las filas del hilo llevando "el
    último `PENDIENTE_FECHA` visto" y cortaba (`return None`) apenas encontraba una fila terminal
    posterior a él, sin seguir mirando el resto — devolvía `None` acá, aunque la fila 3 (el
    pendiente fresco) no tuviera ninguna fila posterior. El guard quedaba permanentemente roto
    para cualquier hilo que ya hubiera completado un ciclo. La versión nueva
    (`ORDER BY created_at DESC LIMIT 1`, sin loop en Python) reconoce la fila 3 correctamente.

    Se necesita un Postgres real (no un mock de `session.query`) porque el bug es específicamente
    sobre CÓMO se arma y se recorre la consulta con 3+ filas reales — un mock de unidad que ya
    devuelve "la fila correcta" sin importar el criterio no puede reproducirlo de forma honesta
    (por eso la suite no lo tenía: todos los fixtures mockeados eran de 1 o 2 filas). Ver
    `task-6-report.md`, sección "Fix round 1", para la corrida fallando contra la implementación
    vieja y pasando contra la nueva.

    Inserta las 3 filas con `flush()` (nunca `commit()`) y hace `rollback()` en el `finally`: la
    transacción nunca se comprometió, así que el trigger de inmutabilidad de
    `app.ingresos_correcciones` (que sólo bloquea UPDATE/DELETE sobre filas ya COMMITEADAS) nunca
    entra en juego, y no queda ningún rastro en la DB de dev."""
    from datetime import datetime, timedelta, timezone

    from db.session import SessionLocal
    from modules.slack_baneo_notifier.listener import IngresoListener

    listener = IngresoListener(bot_token="xoxb-test", app_token="xapp-test")
    # `thread_ts` es VARCHAR(32) — un ts sintético con la misma forma que uno real de Slack
    # ("<segundos>.<microsegundos>"), fuera de cualquier rango real para no colisionar.
    thread_ts = "9999999999.999901"
    ahora = datetime.now(timezone.utc)

    session = SessionLocal()
    try:
        _insertar_correccion_test(
            session, thread_ts=thread_ts, resultado=RESULTADO_PENDIENTE_FECHA,
            created_at=ahora - timedelta(minutes=60), comando_crudo="Forzar egreso",
        )
        _insertar_correccion_test(
            session, thread_ts=thread_ts, resultado="OK_EGRESO_ASENTADO",
            created_at=ahora - timedelta(minutes=55), comando_crudo="Forzar egreso 20-09-2026 10:00",
        )
        fila_vigente = _insertar_correccion_test(
            session, thread_ts=thread_ts, resultado=RESULTADO_PENDIENTE_FECHA,
            created_at=ahora - timedelta(minutes=5), comando_crudo="Forzar ingreso Cra Test 123",
        )

        resultado = listener._pendiente_fecha_vigente(session, thread_ts)

        assert resultado is not None, (
            "el guard debería reconocer el PENDIENTE_FECHA fresco (fila 3) como vigente, aunque "
            "haya un ciclo previo completo antes en el mismo hilo — este es el bug Critical del "
            "Fix round 1 si falla acá"
        )
        assert resultado.id == fila_vigente.id
        assert resultado.comando_crudo == "Forzar ingreso Cra Test 123"
    finally:
        session.rollback()  # nunca commit: ninguna fila queda persistida en la DB de dev
        session.close()



@requiere_postgres_real
def test_fontaine_id_real_registra_en_la_camara_33978_sin_dejar_datos() -> None:
    """Datos reales de dev (5433): "ingreso ok, id: 1228619" en el hilo de un `IngresoSinMatch`
    pendiente registra el movimiento en la Cámara 33978 (Botella 10245762) y confirma. Todo corre
    en una transacción que nunca se compromete: `session.commit` se reemplaza por `flush` (el camino
    de registro commitea internamente) y el `finally` hace `rollback()` — no queda nada en dev."""
    from datetime import datetime, timedelta, timezone

    from db.models.infra import IngresoSinMatch
    from db.session import SessionLocal
    from modules.slack_baneo_notifier.listener import IngresoListener

    listener = IngresoListener(bot_token="xoxb-test", app_token="xapp-test")
    client_mock = MagicMock()
    thread_ts = "9999999999.999902"
    session = SessionLocal()
    session.commit = session.flush  # type: ignore[method-assign]
    try:
        caso = IngresoSinMatch(
            texto_original="Cra 25 de Mayo 320",
            origen="slack",
            contexto="C_TEST_FONTAINE",
            thread_ts=thread_ts,
            texto_mensaje="*Nombre: Nodo/Camara/botella*\nCra 25 de Mayo 320\n*Ingreso o Egreso*\nIngreso\n",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        session.add(caso)
        session.flush()

        with patch("modules.slack_baneo_notifier.listener.resolver_nombre_tecnico", return_value="Test Fontaine"):
            tratado = listener._procesar_seguimiento_empalme(
                "ingreso ok, id: 1228619", thread_ts, session, client_mock, "C_TEST_FONTAINE"
            )

        assert tratado is True
        assert caso.resuelto_via_revalidacion is True
        assert caso.ingreso_id is not None
        assert caso.ingreso.camara_id == 33978
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        assert "(Fontaine ID 1228619)" in texto
        assert "Cra 25 de Mayo 302" in texto
    finally:
        session.rollback()  # nunca commit real: ninguna fila queda en la DB de dev
        session.close()
