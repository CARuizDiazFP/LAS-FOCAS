# Nombre de archivo: test_slack_ingreso_seguimiento.py
# Ubicación de archivo: tests/test_slack_ingreso_seguimiento.py
# Descripción: Tests del listener de ingresos de Slack: seguimiento de empalme, ID de Fontaine y Revalidar ingreso

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

os.environ.setdefault("TESTING", "true")

from core.services.cromo.camara_botella_busqueda import ResultadoBusquedaExtendida
from core.services.ingreso_correccion_service import RESULTADO_PENDIENTE_FECHA


# ─── Tests del regex de seguimiento de empalme ─────────────────────────────────


class TestRegexSeguimientoEmpalme(unittest.TestCase):
    """Prueba directa de `_RE_SEGUIMIENTO_EMPALME` (Tarea 2, 2026-08-23) — el patrón que detecta
    una respuesta de seguimiento con el ID de empalme en el hilo de un caso `IngresoSinMatch`
    pendiente."""

    def setUp(self) -> None:
        from modules.slack_baneo_notifier.listener import _RE_SEGUIMIENTO_EMPALME
        self.regex = _RE_SEGUIMIENTO_EMPALME

    def test_matchea_digitos_puros(self) -> None:
        m = self.regex.match("1234567")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "1234567")

    def test_matchea_con_prefijo_empalme(self) -> None:
        m = self.regex.match("empalme 1234567")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "1234567")

    def test_matchea_con_numeral(self) -> None:
        m = self.regex.match("#1234567")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "1234567")

    def test_matchea_con_espacios_alrededor(self) -> None:
        m = self.regex.match("   1234567   ")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "1234567")

    def test_no_matchea_menos_de_3_digitos(self) -> None:
        """Mínimo 3 dígitos a propósito — evita falsos positivos con números de piso cortos."""
        self.assertIsNone(self.regex.match("12"))
        self.assertIsNone(self.regex.match("7"))

    def test_no_matchea_texto_no_numerico(self) -> None:
        self.assertIsNone(self.regex.match("sí"))
        self.assertIsNone(self.regex.match("ok"))
        self.assertIsNone(self.regex.match("dale"))

    def test_no_matchea_numero_dentro_de_una_oracion(self) -> None:
        """El regex ancla ^...$ (vía `.match` sobre todo el string) — un número que forma parte de
        una oración más larga no debe interpretarse como ID de empalme."""
        self.assertIsNone(self.regex.match("Cámara: Mitre 1234"))
        self.assertIsNone(self.regex.match("el empalme es 1234 seguro"))

    def test_matchea_formas_reales_del_fontaine_id(self) -> None:
        """2026-10-23: el operador valida con "ingreso ok, id: 1228619" (y variantes)."""
        for texto in (
            "id: 1228619",
            "id 1228619",
            "ID:1228619",
            "ingreso ok, id: 1228619",
            "INGRESO OK, ID: 1228619",
            "Ingreso ok id 1228619",
            "  ingreso ok,id:1228619  ",
            "egreso ok, id: 1228619",
        ):
            m = self.regex.match(texto)
            self.assertIsNotNone(m, texto)
            self.assertEqual(m.group(1), "1228619", texto)

    def test_matchea_egreso_ok_id(self) -> None:
        """Fix de la revisión: el operador también valida el egreso con "egreso ok, id: N"."""
        for texto in ("egreso ok, id: 1228619", "EGRESO OK id 1228619"):
            m = self.regex.match(texto)
            self.assertIsNotNone(m, texto)
            self.assertEqual(m.group(1), "1228619")

    def test_no_matchea_otras_frases_con_id(self) -> None:
        self.assertIsNone(self.regex.match("ingreso ok"))
        self.assertIsNone(self.regex.match("reingreso ok, id: 1228619"))
        self.assertIsNone(self.regex.match("el id es 1228619"))


# ─── Tests del mecanismo de "hilo esperando ID de empalme" ─────────────────────


class TestSeguimientoEmpalme(unittest.TestCase):
    """Prueba `_procesar_seguimiento_empalme` / la integración en `_handle_message` (Tarea 2,
    2026-08-23): un técnico responde en el hilo de un caso `IngresoSinMatch` pendiente con el ID de
    empalme más cercano."""

    def setUp(self) -> None:
        # Desde 2026-10-23 el número se prueba primero como Fontaine ID: en estos tests no existe
        # (los de Fontaine están en `TestSeguimientoFontaineId`).
        patcher = patch("modules.slack_baneo_notifier.listener.buscar_por_id_legacy", return_value=None)
        self.mock_fontaine = patcher.start()
        self.addCleanup(patcher.stop)

    def _make_listener(self) -> Any:
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event_reply(
        self, text: str, thread_ts: str = "1111.000001", ts: str = "2222.000002", channel: str = "C123"
    ) -> dict:
        """Evento de una respuesta REAL dentro de un hilo: thread_ts presente y distinto de ts."""
        return {"text": text, "channel": channel, "ts": ts, "thread_ts": thread_ts}

    def _query_side_effect_con_caso(self, caso_mock: Any, camara_mock: Any = None) -> Any:
        from db.models.infra import Camara, IngresoSinMatch

        def _side_effect(model: Any) -> Any:
            q = MagicMock()
            if model is IngresoSinMatch:
                q.filter.return_value.order_by.return_value.first.return_value = caso_mock
            elif model is Camara:
                q.filter.return_value.one_or_none.return_value = camara_mock
            return q

        return _side_effect

    def test_seguimiento_resuelve_botella_y_marca_caso(self) -> None:
        """Fila pendiente + fusión que resuelve una Botella con Cámara asociada → aplica el mismo
        chequeo de acceso de siempre sobre esa Cámara, responde en el hilo, y marca el caso
        `resuelto_via_empalme=True` (commit) para no reprocesar el mismo hilo."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()

        caso_mock = MagicMock()
        caso_mock.id = 5
        caso_mock.resuelto_via_empalme = False

        camara_mock = MagicMock()
        camara_mock.id = 42
        camara_mock.nombre = "Cam Resuelta Por Empalme"
        camara_mock.estado = CamaraEstado.LIBRE
        contexto_libre = CamaraEstadoContexto(
            camara_id=42, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        botella_mock = MagicMock()
        botella_mock.camara_id = 42

        session_mock.query.side_effect = self._query_side_effect_con_caso(caso_mock, camara_mock)

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_botella_por_fusion_sync",
                return_value=botella_mock,
            ) as mock_resolver,
            patch("modules.slack_baneo_notifier.listener.get_camara_estado_contexto", return_value=contexto_libre),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara") as mock_extraer,
        ):
            listener._handle_message(self._make_event_reply("1234567"), client_mock)
            mock_extraer.assert_not_called()  # cortó antes de llegar al flujo normal

        mock_resolver.assert_called_once_with(session_mock, 1234567)
        self.assertTrue(caso_mock.resuelto_via_empalme)
        session_mock.commit.assert_called_once()

        client_mock.chat_postMessage.assert_called_once()
        kwargs = client_mock.chat_postMessage.call_args.kwargs
        self.assertEqual(kwargs["thread_ts"], "1111.000001")
        self.assertIn("✅", kwargs["text"])
        self.assertIn("Cam Resuelta Por Empalme", kwargs["text"])

    def test_seguimiento_no_resuelve_botella_no_bloquea_y_marca_caso(self) -> None:
        """Si `resolver_botella_por_fusion_sync` no resuelve nada (empate, fusión inexistente),
        se avisa sin bloquear el ingreso — y el caso igual se marca resuelto para no reprocesar."""
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()

        caso_mock = MagicMock()
        caso_mock.id = 9
        caso_mock.resuelto_via_empalme = False
        session_mock.query.side_effect = self._query_side_effect_con_caso(caso_mock)

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_botella_por_fusion_sync",
                return_value=None,
            ) as mock_resolver,
        ):
            listener._handle_message(self._make_event_reply("999999"), client_mock)

        mock_resolver.assert_called_once_with(session_mock, 999999)
        self.assertTrue(caso_mock.resuelto_via_empalme)
        session_mock.commit.assert_called_once()

        kwargs = client_mock.chat_postMessage.call_args.kwargs
        self.assertIn("Podés continuar con el ingreso con normalidad", kwargs["text"])
        self.assertNotIn("no_entry", kwargs["text"])
        self.assertNotIn("ATENCIÓN", kwargs["text"])

    def test_seguimiento_botella_sin_camara_id_no_bloquea(self) -> None:
        """Botella resuelta pero sin `camara_id` (backfill pendiente) → mismo tratamiento que "no
        resuelve nada": avisa sin bloquear, marca el caso resuelto."""
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()

        caso_mock = MagicMock()
        caso_mock.id = 11
        caso_mock.resuelto_via_empalme = False
        session_mock.query.side_effect = self._query_side_effect_con_caso(caso_mock)

        botella_mock = MagicMock()
        botella_mock.camara_id = None

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_botella_por_fusion_sync",
                return_value=botella_mock,
            ),
        ):
            listener._handle_message(self._make_event_reply("555555"), client_mock)

        self.assertTrue(caso_mock.resuelto_via_empalme)
        kwargs = client_mock.chat_postMessage.call_args.kwargs
        self.assertIn("Podés continuar con el ingreso con normalidad", kwargs["text"])

    def test_seguimiento_sin_fila_pendiente_sigue_flujo_normal(self) -> None:
        """Texto numérico válido, pero ningún `IngresoSinMatch` pendiente para este hilo → se
        ignora como intento de empalme y sigue el flujo normal (no corta antes de
        extraer_nombre_camara)."""
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        session_mock.query.side_effect = self._query_side_effect_con_caso(None)

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_botella_por_fusion_sync"
            ) as mock_resolver,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value=""
            ) as mock_extraer,
        ):
            listener._handle_message(self._make_event_reply("1234567"), client_mock)

        mock_extraer.assert_called_once()
        mock_resolver.assert_not_called()
        client_mock.chat_postMessage.assert_not_called()
        session_mock.commit.assert_not_called()

    def test_seguimiento_texto_no_numerico_se_ignora(self) -> None:
        """Texto que no matchea el regex de seguimiento: `_procesar_seguimiento_empalme` ni
        siquiera consulta si hay un caso pendiente — sigue el flujo normal sin más (puede ser
        cualquier otro mensaje del canal).

        Desde el Fix round 1 (Important 3, Task 6, 2026-09-23) `_handle_message` SÍ consulta
        `IngresoCorreccion` una vez al entrar a cualquier hilo, para decidir si le da prioridad al
        seguimiento de "fecha pendiente" sobre el de empalme — pero al no haber ningún
        `PENDIENTE_FECHA` vigente acá, no pasa de esa única consulta."""
        from db.models.infra import IngresoCorreccion

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()

        def _query_side_effect(model: Any) -> Any:
            q = MagicMock()
            if model is IngresoCorreccion:
                q.filter.return_value.order_by.return_value.first.return_value = None
            return q

        session_mock.query.side_effect = _query_side_effect

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_botella_por_fusion_sync"
            ) as mock_resolver,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value=""
            ) as mock_extraer,
        ):
            listener._handle_message(self._make_event_reply("sí, dale"), client_mock)

        session_mock.query.assert_called_once()  # sólo el chequeo de prioridad de fecha pendiente
        mock_resolver.assert_not_called()
        mock_extraer.assert_called_once()

    def test_mensaje_raiz_del_hilo_no_se_trata_como_seguimiento(self) -> None:
        """thread_ts == ts (mensaje raíz de un hilo nuevo, no una respuesta) → nunca se evalúa como
        seguimiento, aunque el texto sea puramente numérico."""
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        evento_raiz = {"text": "1234567", "channel": "C123", "ts": "3333.000003"}  # sin thread_ts

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_botella_por_fusion_sync"
            ) as mock_resolver,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value=""
            ) as mock_extraer,
        ):
            listener._handle_message(evento_raiz, client_mock)

        session_mock.query.assert_not_called()
        mock_resolver.assert_not_called()
        mock_extraer.assert_called_once()


# ─── Tests del regex de "Revalidar ingreso" ─────────────────────────────────────


class TestSeguimientoFontaineId(unittest.TestCase):
    """2026-10-23: el número de la respuesta en hilo se prueba primero como Fontaine ID
    (`cromo_botellas.id_legacy`) y después como ID de empalme."""

    def _caso(self, tipo: str = "Ingreso") -> Any:
        from datetime import datetime, timezone

        caso = MagicMock()
        caso.id = 5
        caso.resuelto_via_empalme = False
        caso.resuelto_via_revalidacion = False
        caso.ingreso_id = None
        caso.texto_mensaje = f"*Nombre: Nodo/Camara/botella*\nCra 25 de Mayo 320\n*Ingreso o Egreso*\n{tipo}\n"
        caso.created_at = datetime(2026, 10, 23, 9, 15, tzinfo=timezone.utc)
        caso.thread_ts = "1111.000001"
        caso.contexto = "C123"
        return caso

    def _camara(self) -> Any:
        camara = MagicMock()
        camara.id = 33978
        camara.nombre = "Cra 25 de Mayo 302 CF"
        return camara

    def _correr(self, texto: str, *, fontaine: Any = None, fusion: Any = None, camara_fusion: Any = None,
                user: str | None = "U0OPERADOR", tipo: str = "Ingreso", es_nodo: bool = False):
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto
        from db.models.infra import Camara, IngresoCorreccion, IngresoSinMatch
        from modules.slack_baneo_notifier.listener import IngresoListener

        listener = IngresoListener(bot_token="xoxb-test", app_token="xapp-test")
        client_mock = MagicMock()
        session_mock = MagicMock()
        caso = self._caso(tipo)

        def _side_effect(model: Any) -> Any:
            q = MagicMock()
            if model is IngresoSinMatch:
                q.filter.return_value.order_by.return_value.first.return_value = caso
            elif model is IngresoCorreccion:
                q.filter.return_value.order_by.return_value.first.return_value = None
            elif model is Camara:
                q.filter.return_value.one_or_none.return_value = camara_fusion
            return q

        session_mock.query.side_effect = _side_effect
        contexto_libre = CamaraEstadoContexto(
            camara_id=33978, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False,
            inconsistente=False, incidentes_activos=[], ticket_baneo=None,
        )
        fontaine_mock = MagicMock(**({"side_effect": fontaine} if isinstance(fontaine, Exception) else {"return_value": fontaine}))
        event = {"text": texto, "channel": "C123", "ts": "2222.000002", "thread_ts": "1111.000001"}
        if user:
            event["user"] = user
        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch("modules.slack_baneo_notifier.listener.buscar_por_id_legacy", fontaine_mock),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_botella_por_fusion_sync", return_value=fusion
            ) as mock_fusion,
            patch("modules.slack_baneo_notifier.listener.get_camara_estado_contexto", return_value=contexto_libre),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo") as mock_buscar,
            patch("modules.slack_baneo_notifier.listener.resolver_nombre_tecnico", return_value="Técnico"),
            patch("modules.slack_baneo_notifier.listener.corresponde_a_nodo", return_value=es_nodo),
            patch(
                "modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso", return_value=self.ingreso
            ) as mock_registrar,
        ):
            listener._handle_message(event, client_mock)
        self.mock_registrar = mock_registrar
        return client_mock, session_mock, caso, fontaine_mock, mock_fusion, mock_buscar

    def setUp(self) -> None:
        self.ingreso = MagicMock()
        self.ingreso.id = 501

    def _fontaine(self, camara: Any) -> ResultadoBusquedaExtendida:
        botella = MagicMock()
        botella.n_id = 10245762
        botella.nombre = "Cra 25 de Mayo 302 CF"
        return ResultadoBusquedaExtendida(camara=camara, nombre_norm="x", fuente="cromo_botella", botella=botella)

    def test_numero_solo_resuelve_como_fontaine_id_registra_y_confirma(self) -> None:
        """Decisión del usuario 2026-10-23 ("Registrar y confirmar"): el Fontaine ID registra el
        movimiento del caso (tipo y horario originales) y confirma con la Cámara y el ID usado."""
        camara = self._camara()
        resultado = self._fontaine(camara)
        client_mock, session_mock, caso, fontaine, fusion, buscar = self._correr("1228619", fontaine=resultado)
        fontaine.assert_called_once_with("1228619", session_mock)
        fusion.assert_not_called()  # Fontaine primero: no se prueba el empalme
        buscar.assert_not_called()
        self.mock_registrar.assert_called_once()
        kwargs = self.mock_registrar.call_args.kwargs
        self.assertIs(kwargs["camara"], camara)
        self.assertIs(kwargs["botella"], resultado.botella)
        self.assertEqual(kwargs["tipo_movimiento"], "Ingreso")
        self.assertEqual(kwargs["momento"], caso.created_at)
        self.assertTrue(caso.resuelto_via_revalidacion)
        self.assertFalse(caso.resuelto_via_empalme)
        self.assertEqual(caso.ingreso_id, 501)
        session_mock.commit.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn(
            "✅ Registré el ingreso en *Cra 25 de Mayo 302 CF* (Fontaine ID 1228619).",
            texto,
        )
        self.assertNotIn("administrador", texto)

    def test_fontaine_id_con_egreso_registra_egreso(self) -> None:
        camara = self._camara()
        client_mock, session_mock, caso, fontaine, _, _ = self._correr(
            "egreso ok, id: 1228619", fontaine=self._fontaine(camara), tipo="Egreso"
        )
        fontaine.assert_called_once_with("1228619", session_mock)
        self.assertEqual(self.mock_registrar.call_args.kwargs["tipo_movimiento"], "Egreso")
        self.assertIn("✅ Registré el egreso en *Cra 25 de Mayo 302 CF* (Fontaine ID 1228619)",
                      client_mock.chat_postMessage.call_args.kwargs["text"])

    def test_formato_del_operador_ingreso_ok_id(self) -> None:
        camara = self._camara()
        client_mock, session_mock, caso, fontaine, _, _ = self._correr(
            "ingreso ok, id: 1228619", fontaine=self._fontaine(camara)
        )
        fontaine.assert_called_once_with("1228619", session_mock)
        self.mock_registrar.assert_called_once()
        self.assertTrue(caso.resuelto_via_revalidacion)
        self.assertIn("Fontaine ID 1228619", client_mock.chat_postMessage.call_args.kwargs["text"])

    def test_formas_del_operador_con_texto_alrededor(self) -> None:
        """Ronda 3: "Ingreso ok, ID 1228619." (punto final) e "ingreso ok, id: 1228619 abriendo
        puerta" (texto después) también son el Fontaine ID."""
        for texto in ("Ingreso ok, ID 1228619.", "ingreso ok, id: 1228619 abriendo puerta"):
            with self.subTest(texto=texto):
                client_mock, session_mock, caso, fontaine, _, _ = self._correr(
                    texto, fontaine=self._fontaine(self._camara())
                )
                fontaine.assert_called_once_with("1228619", session_mock)
                self.mock_registrar.assert_called_once()
                self.assertTrue(caso.resuelto_via_revalidacion)

    def test_id_corto_suelto_no_se_prueba_como_fontaine(self) -> None:
        """Ronda 3: hay `id_legacy` cortos (túneles, 7274-7330): "7300" suelto va sólo al empalme,
        como antes; con la forma explícita "id: 7300" sí se prueba como Fontaine ID."""
        _, _, _, fontaine, fusion, _ = self._correr("7300", fontaine=self._fontaine(self._camara()))
        fontaine.assert_not_called()
        fusion.assert_called_once()
        self.mock_registrar.assert_not_called()

        _, session_mock, _, fontaine, fusion, _ = self._correr("id: 7300", fontaine=self._fontaine(self._camara()))
        fontaine.assert_called_once_with("7300", session_mock)
        fusion.assert_not_called()

    def test_fontaine_id_que_resuelve_a_un_nodo_se_ignora(self) -> None:
        client_mock, session_mock, caso, _, fusion, _ = self._correr(
            "id: 1228619", fontaine=self._fontaine(self._camara()), es_nodo=True
        )
        self.mock_registrar.assert_not_called()
        fusion.assert_not_called()
        self.assertFalse(caso.resuelto_via_revalidacion)
        self.assertFalse(caso.resuelto_via_empalme)
        session_mock.commit.assert_not_called()
        client_mock.chat_postMessage.assert_not_called()

    def test_si_no_es_fontaine_prueba_como_id_de_empalme(self) -> None:
        camara = self._camara()
        botella = MagicMock()
        botella.camara_id = 33978
        client_mock, session_mock, caso, fontaine, fusion, _ = self._correr(
            "id 10245999", fontaine=None, fusion=botella, camara_fusion=camara
        )
        fontaine.assert_called_once()
        fusion.assert_called_once_with(session_mock, 10245999)
        self.assertTrue(caso.resuelto_via_empalme)
        self.mock_registrar.assert_not_called()  # por ID de empalme: cierra sin registrar, como antes
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("Resuelto por ID de empalme *10245999*", texto)
        self.assertIn("Cra 25 de Mayo 302 CF", texto)

    def test_ni_fontaine_ni_empalme_mantiene_la_respuesta_de_hoy(self) -> None:
        client_mock, session_mock, caso, _, fusion, buscar = self._correr("999999", fontaine=None, fusion=None)
        fusion.assert_called_once()
        buscar.assert_not_called()
        # Mismo camino que antes de 2026-10-23: se marca el caso y se avisa que puede continuar.
        self.assertTrue(caso.resuelto_via_empalme)
        session_mock.commit.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("No pude ubicar una botella asociada al ID de empalme *999999*", texto)
        self.assertIn("Fontaine", texto)
        self.assertIn("Podés continuar con el ingreso con normalidad", texto)

    def test_fontaine_id_que_no_resuelve_no_cierra_el_caso(self) -> None:
        """Fix de la revisión: con la forma del Fontaine ID ("id: N"), un número que no resuelve
        por ninguno de los dos caminos NO marca `resuelto_via_empalme` (la reescritura de la
        Cámara sigue disponible en el hilo). El número suelto conserva el cierre de antes
        (`test_ni_fontaine_ni_empalme_mantiene_la_respuesta_de_hoy`)."""
        for texto in ("id: 1999999", "ingreso ok, id: 1999999", "egreso ok, id: 1999999"):
            with self.subTest(texto=texto):
                client_mock, session_mock, caso, _, fusion, _ = self._correr(texto, fontaine=None, fusion=None)
                fusion.assert_called_once()
                self.assertFalse(caso.resuelto_via_empalme)
                session_mock.commit.assert_not_called()
                respuesta = client_mock.chat_postMessage.call_args.kwargs["text"]
                self.assertIn("No encontré el Fontaine ID *1999999*", respuesta)
                self.assertIn("escribí la cámara correcta en este hilo", respuesta)

    def test_caso_pendiente_excluye_los_resueltos_por_revalidacion(self) -> None:
        from modules.slack_baneo_notifier.listener import IngresoListener

        listener = IngresoListener(bot_token="xoxb-test", app_token="xapp-test")
        session_mock = MagicMock()
        q = session_mock.query.return_value
        q.filter.return_value.order_by.return_value.first.return_value = None

        self.assertFalse(
            listener._procesar_seguimiento_empalme("1228619", "1111.000001", session_mock, MagicMock(), "C123")
        )
        filtros = [str(arg) for arg in q.filter.call_args.args]
        self.assertTrue(any("resuelto_via_revalidacion" in f for f in filtros), filtros)
        self.assertTrue(any("resuelto_via_empalme" in f for f in filtros), filtros)

    def test_fontaine_id_repetido_nunca_elige_y_deja_el_caso_pendiente(self) -> None:
        from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError

        dup = AmbiguousSearchError("1256524", 2, ["Poste Paunero 1543 SAN MIGUEL", "Poste Paunero 1543 SAN MIGUEL"])
        client_mock, session_mock, caso, _, fusion, _ = self._correr("id: 1256524", fontaine=dup)
        fusion.assert_not_called()
        self.mock_registrar.assert_not_called()
        self.assertFalse(caso.resuelto_via_empalme)
        self.assertFalse(caso.resuelto_via_revalidacion)
        session_mock.commit.assert_not_called()
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("más de una botella", texto)
        self.assertIn("• Poste Paunero 1543 SAN MIGUEL", texto)

    def test_prioridad_fecha_pendiente_le_gana_al_fontaine_id(self) -> None:
        """La corrección con fecha pendiente sigue primero: con un `PENDIENTE_FECHA` vigente que
        reconoce el texto, el número nunca se busca como Fontaine ID ni como empalme."""
        from datetime import datetime, timedelta, timezone

        from core.services.ingreso_correccion_service import ResultadoCorreccion
        from db.models.infra import IngresoCorreccion, IngresoSinMatch
        from modules.slack_baneo_notifier.listener import IngresoListener

        listener = IngresoListener(bot_token="xoxb-test", app_token="xapp-test")
        client_mock = MagicMock()
        session_mock = MagicMock()
        caso = self._caso()
        fila_pendiente = MagicMock()
        fila_pendiente.id = 77
        fila_pendiente.resultado = RESULTADO_PENDIENTE_FECHA
        fila_pendiente.comando_crudo = "Forzar egreso"
        fila_pendiente.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)

        def _side_effect(model: Any) -> Any:
            q = MagicMock()
            if model is IngresoSinMatch:
                q.filter.return_value.order_by.return_value.first.return_value = caso
            elif model is IngresoCorreccion:
                q.filter.return_value.order_by.return_value.first.return_value = fila_pendiente
            return q

        session_mock.query.side_effect = _side_effect
        resultado_final = ResultadoCorreccion(
            resultado="OK_EGRESO_ASENTADO", respuesta="✅ Egreso asentado.", comando="FORZAR_EGRESO"
        )
        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch("modules.slack_baneo_notifier.listener.buscar_por_id_legacy") as mock_fontaine,
            patch("modules.slack_baneo_notifier.listener.resolver_botella_por_fusion_sync") as mock_fusion,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_momento_solo",
                return_value=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.procesar_comando_correccion",
                side_effect=lambda session, *, momento_explicito=None, **_k: (
                    resultado_final if momento_explicito is not None else None
                ),
            ),
        ):
            listener._handle_message(
                {"text": "id: 1228619", "channel": "C123", "ts": "2222.000002",
                 "thread_ts": "1111.000001", "user": "U0OPERADOR"},
                client_mock,
            )

        mock_fontaine.assert_not_called()
        mock_fusion.assert_not_called()
        self.assertFalse(caso.resuelto_via_empalme)
        self.assertEqual(client_mock.chat_postMessage.call_args.kwargs["text"], resultado_final.respuesta)


class TestRegexRevalidarIngreso(unittest.TestCase):
    """Prueba directa de `_RE_REVALIDAR_INGRESO` (2026-09-07)."""

    def setUp(self) -> None:
        from modules.slack_baneo_notifier.listener import _RE_REVALIDAR_INGRESO
        self.regex = _RE_REVALIDAR_INGRESO

    def test_matchea_frase_exacta(self) -> None:
        self.assertIsNotNone(self.regex.match("Revalidar ingreso"))

    def test_matchea_case_insensitive_y_espacios_extra(self) -> None:
        self.assertIsNotNone(self.regex.match("  REVALIDAR   ingreso  "))
        self.assertIsNotNone(self.regex.match("revalidar Ingreso"))

    def test_no_matchea_solo_una_palabra(self) -> None:
        self.assertIsNone(self.regex.match("Revalidar"))
        self.assertIsNone(self.regex.match("ingreso"))

    def test_no_matchea_frase_con_palabras_de_mas(self) -> None:
        self.assertIsNone(self.regex.match("Revalidar el ingreso"))
        self.assertIsNone(self.regex.match("necesito revalidar ingreso urgente"))


# ─── Tests del mecanismo "Revalidar ingreso" ────────────────────────────────────


class TestRevalidacionIngreso(unittest.TestCase):
    """Prueba `_procesar_revalidacion_ingreso` / la integración en `_handle_message` (2026-09-07):
    respuesta en el hilo de un caso `IngresoSinMatch` pendiente (sin match o ambiguo) que reintenta
    la búsqueda y, si resuelve, registra el movimiento real preservando el horario original."""

    def _make_listener(self) -> Any:
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event_reply(
        self, text: str = "Revalidar ingreso", thread_ts: str = "1111.000001",
        ts: str = "2222.000002", channel: str = "C123",
    ) -> dict:
        return {"text": text, "channel": channel, "ts": ts, "thread_ts": thread_ts}

    def _query_side_effect(self, caso_mock: Any) -> Any:
        from db.models.infra import IngresoSinMatch

        def _side_effect(model: Any) -> Any:
            q = MagicMock()
            if model is IngresoSinMatch:
                q.filter.return_value.order_by.return_value.first.return_value = caso_mock
            return q

        return _side_effect

    def _make_caso(
        self, *, texto_mensaje: str | None = "*Nombre: ...*\ntexto", resuelto_empalme: bool = False,
        resuelto_revalidacion: bool = False, created_at: Any = None,
        thread_ts: str | None = "9999.000009", contexto: str | None = "C_ORIGINAL",
    ) -> Any:
        from datetime import datetime, timezone

        caso = MagicMock()
        caso.id = 5
        caso.texto_mensaje = texto_mensaje
        caso.resuelto_via_empalme = resuelto_empalme
        caso.resuelto_via_revalidacion = resuelto_revalidacion
        caso.ingreso_id = None
        caso.created_at = created_at or datetime(2026, 9, 7, 22, 22, 8, tzinfo=timezone.utc)
        # thread_ts/contexto (canal) del caso IngresoSinMatch ORIGINAL — deliberadamente distintos
        # de los del evento "Revalidar ingreso" (`_make_event_reply`: thread_ts="1111.000001",
        # channel="C123") para que un test pueda distinguir cuál de los dos se propaga.
        caso.thread_ts = thread_ts
        caso.contexto = contexto
        return caso

    def test_sin_fila_pendiente_responde_y_corta(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        session_mock.query.side_effect = self._query_side_effect(None)

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara") as mock_extraer,
        ):
            listener._handle_message(self._make_event_reply(), client_mock)
            mock_extraer.assert_not_called()  # cortó antes de llegar al flujo normal

        session_mock.add.assert_not_called()
        session_mock.commit.assert_not_called()
        kwargs = client_mock.chat_postMessage.call_args.kwargs
        self.assertIn("No encontré", kwargs["text"])

    def test_caso_ya_resuelto_via_empalme_no_reprocesa(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        caso_mock = self._make_caso(resuelto_empalme=True)
        session_mock.query.side_effect = self._query_side_effect(caso_mock)

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo") as mock_buscar,
        ):
            listener._handle_message(self._make_event_reply(), client_mock)

        mock_buscar.assert_not_called()
        session_mock.commit.assert_not_called()
        self.assertIn("ya fue validado", client_mock.chat_postMessage.call_args.kwargs["text"])

    def test_caso_ya_resuelto_via_revalidacion_no_reprocesa(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        caso_mock = self._make_caso(resuelto_revalidacion=True)
        session_mock.query.side_effect = self._query_side_effect(caso_mock)

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo") as mock_buscar,
        ):
            listener._handle_message(self._make_event_reply(), client_mock)

        mock_buscar.assert_not_called()
        self.assertIn("ya fue validado", client_mock.chat_postMessage.call_args.kwargs["text"])

    def test_sin_texto_mensaje_guardado_no_puede_revalidar(self) -> None:
        """Caso creado antes de 2026-09-07 (sin `texto_mensaje`) — no hay forma de re-extraer nada,
        no se marca resuelto (para que un humano lo revise vía `revisado`, no se pierde)."""
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        caso_mock = self._make_caso(texto_mensaje=None)
        session_mock.query.side_effect = self._query_side_effect(caso_mock)

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo") as mock_buscar,
        ):
            listener._handle_message(self._make_event_reply(), client_mock)

        mock_buscar.assert_not_called()
        self.assertFalse(caso_mock.resuelto_via_revalidacion)
        session_mock.commit.assert_not_called()

    def test_sigue_ambigua_no_marca_resuelto(self) -> None:
        from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        caso_mock = self._make_caso()
        session_mock.query.side_effect = self._query_side_effect(caso_mock)

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="e:"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                side_effect=AmbiguousSearchError("e:", 0, []),
            ),
        ):
            listener._handle_message(self._make_event_reply(), client_mock)

        self.assertFalse(caso_mock.resuelto_via_revalidacion)
        session_mock.commit.assert_not_called()
        self.assertIn("sigue sin poder", client_mock.chat_postMessage.call_args.kwargs["text"])

    def test_numero_no_coincide_en_revalidacion_se_trata_como_ambigua(self) -> None:
        from modules.slack_baneo_notifier.camara_search import NumeroNoCoincideError

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        caso_mock = self._make_caso()
        session_mock.query.side_effect = self._query_side_effect(caso_mock)

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Cra Mitre 404"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                side_effect=NumeroNoCoincideError("Cra Mitre 404", 1, ["Cra Mitre 440"]),
            ),
        ):
            listener._handle_message(self._make_event_reply(), client_mock)

        self.assertFalse(caso_mock.resuelto_via_revalidacion)
        session_mock.commit.assert_not_called()
        self.assertIn("sigue sin poder", client_mock.chat_postMessage.call_args.kwargs["text"])

    def test_sigue_sin_match_no_marca_resuelto(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        caso_mock = self._make_caso()
        session_mock.query.side_effect = self._query_side_effect(caso_mock)
        resultado_sin_match = ResultadoBusquedaExtendida(
            camara=None, nombre_norm="algo", fuente=None, botella=None
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Algo"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=resultado_sin_match,
            ),
        ):
            listener._handle_message(self._make_event_reply(), client_mock)

        self.assertFalse(caso_mock.resuelto_via_revalidacion)
        session_mock.commit.assert_not_called()
        self.assertIn("todavía no matchea", client_mock.chat_postMessage.call_args.kwargs["text"])

    def test_resuelve_y_registra_movimiento_con_horario_original(self) -> None:
        """Caso feliz: la revalidación matchea una única cámara y el mensaje original traía
        'Ingreso o Egreso' — se registra el movimiento real con `momento=caso.created_at` (el
        horario del intento original, no el de la revalidación), se enlaza `ingreso_id` y se marca
        `resuelto_via_revalidacion=True`."""
        from datetime import datetime, timezone
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        momento_original = datetime(2026, 9, 7, 22, 22, 8, tzinfo=timezone.utc)
        caso_mock = self._make_caso(
            texto_mensaje="*Nombre: Nodo/Camara/botella*\nCra Curupayti 2951 CF\n*Ingreso o Egreso*\nEgreso\n",
            created_at=momento_original,
        )
        session_mock.query.side_effect = self._query_side_effect(caso_mock)

        camara_mock = self._make_camara(id_=42, nombre="Cra Curupayti 2951 CF")
        camara_mock.estado = CamaraEstado.LIBRE
        resultado_ok = ResultadoBusquedaExtendida(
            camara=camara_mock, nombre_norm="cra curupayti 2951", fuente="camara", botella=None
        )
        contexto_libre = CamaraEstadoContexto(
            camara_id=42, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False,
            inconsistente=False, incidentes_activos=[], ticket_baneo=None,
        )
        ingreso_creado = MagicMock()
        ingreso_creado.id = 777

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=resultado_ok,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=contexto_libre,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_nombre_tecnico",
                return_value="Rider Fernández",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso",
                return_value=ingreso_creado,
            ) as mock_registrar,
        ):
            listener._handle_message(self._make_event_reply(), client_mock)

        mock_registrar.assert_called_once_with(
            session_mock,
            camara=camara_mock,
            botella=None,
            tipo_movimiento="Egreso",
            tecnico_nombre="Rider Fernández",
            slack_user_id=None,
            momento=momento_original,
            # Del caso IngresoSinMatch ORIGINAL (`caso.thread_ts`/`caso.contexto`), no del evento
            # "Revalidar ingreso" en sí (`_make_event_reply`: thread_ts="1111.000001", channel="C123").
            thread_ts="9999.000009",
            canal_id="C_ORIGINAL",
        )
        self.assertTrue(caso_mock.resuelto_via_revalidacion)
        self.assertEqual(caso_mock.ingreso_id, 777)
        session_mock.commit.assert_called_once()

        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("✅", texto_respuesta)
        self.assertIn("Cra Curupayti 2951 CF", texto_respuesta)

    def test_resuelve_pero_sin_tipo_no_registra_movimiento(self) -> None:
        """La cámara matchea pero el mensaje original no traía 'Ingreso o Egreso' — se marca
        resuelto igual (la identificación de la cámara sí se logró) pero no se crea ningún
        `Ingreso`, y la respuesta lo deja explícito."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        caso_mock = self._make_caso(texto_mensaje="*Nombre: Nodo/Camara/botella*\nCra Curupayti 2951 CF\n")
        session_mock.query.side_effect = self._query_side_effect(caso_mock)

        camara_mock = self._make_camara(id_=42, nombre="Cra Curupayti 2951 CF")
        camara_mock.estado = CamaraEstado.LIBRE
        resultado_ok = ResultadoBusquedaExtendida(
            camara=camara_mock, nombre_norm="cra curupayti 2951", fuente="camara", botella=None
        )
        contexto_libre = CamaraEstadoContexto(
            camara_id=42, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False,
            inconsistente=False, incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=resultado_ok,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=contexto_libre,
            ),
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
        ):
            listener._handle_message(self._make_event_reply(), client_mock)

        mock_registrar.assert_not_called()
        self.assertTrue(caso_mock.resuelto_via_revalidacion)
        self.assertIsNone(caso_mock.ingreso_id)
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("no se registró ningún movimiento", texto_respuesta)

    def _make_camara(self, id_: int, nombre: str) -> MagicMock:
        cam = MagicMock()
        cam.id = id_
        cam.nombre = nombre
        return cam
