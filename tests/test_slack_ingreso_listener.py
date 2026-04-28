# Nombre de archivo: test_slack_ingreso_listener.py
# Ubicación de archivo: tests/test_slack_ingreso_listener.py
# Descripción: Tests unitarios para el listener de ingresos técnicos via Slack Socket Mode

"""
Tests para:
 - camara_search.extraer_nombre_camara()
 - camara_search.buscar_camara()
 - listener.IngresoListener._handle_message()  (casos ok, baneada, no encontrada, ignorar bot)
"""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import MagicMock, patch, call

os.environ.setdefault("TESTING", "true")


# ─── Tests de extracción de nombre ─────────────────────────────────────────────


class TestExtraerNombreCamara(unittest.TestCase):
    """Prueba camara_search.extraer_nombre_camara()."""

    def setUp(self) -> None:
        from modules.slack_baneo_notifier.camara_search import extraer_nombre_camara
        self.extraer = extraer_nombre_camara

    def test_campo_camara_simple(self) -> None:
        texto = "Técnico: Juan\nCámara: Cam Av. Libertador 1234\nMotivo: inspección"
        result = self.extraer(texto)
        self.assertEqual(result, "Cam Av. Libertador 1234")

    def test_campo_camara_con_acento(self) -> None:
        texto = "Cámara: Terminal Norte - Acceso\nFecha: hoy"
        result = self.extraer(texto)
        self.assertEqual(result, "Terminal Norte - Acceso")

    def test_campo_camara_sin_acento(self) -> None:
        texto = "Camara: Interseccion cra 7 clle 10"
        result = self.extraer(texto)
        self.assertEqual(result, "Interseccion cra 7 clle 10")

    def test_formato_workflow_nombre_nodo_camara(self) -> None:
        """Extrae el nombre de cámara del formato real del Workflow de Slack."""
        texto = (
            "*Cual es el numero de Ticket MKT? o Numero de Linea*\nMKT-111111\n"
            "*Es Camara Critica?*\nNo\n"
            "*Nombre: Nodo/Camara/botella*\nBot. estacion Alem linea B CF\n"
            "*Ingreso o Egreso*\nIngreso\n"
        )
        result = self.extraer(texto)
        self.assertEqual(result, "Bot. estacion Alem linea B CF")

    def test_formato_workflow_prioritario_sobre_campo_camara(self) -> None:
        """El regex de Workflow tiene prioridad sobre el campo libre 'Cámara:'."""
        texto = (
            "*Nombre: Nodo/Camara/botella*\nCam Real del Workflow\n"
            "Cámara: Cam de fallback\n"
        )
        result = self.extraer(texto)
        self.assertEqual(result, "Cam Real del Workflow")

    def test_sin_campo_camara_usa_primera_linea(self) -> None:
        texto = "Cam Zona Norte\nTécnico: María"
        result = self.extraer(texto)
        self.assertEqual(result, "Cam Zona Norte")

    def test_texto_vacio_retorna_vacio(self) -> None:
        result = self.extraer("")
        self.assertEqual(result, "")

    def test_texto_solo_espacios_retorna_vacio(self) -> None:
        result = self.extraer("   \n  ")
        self.assertEqual(result, "")


# ─── Tests de búsqueda de cámara ───────────────────────────────────────────────


class TestBuscarCamara(unittest.TestCase):
    """Prueba camara_search.buscar_camara() con sesión simulada."""

    def _make_camara(self, id_: int, nombre: str) -> MagicMock:
        cam = MagicMock()
        cam.id = id_
        cam.nombre = nombre
        return cam

    @patch("modules.slack_baneo_notifier.camara_search.func")
    def test_encontrada_por_ilike(self, mock_func: MagicMock) -> None:
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        session = MagicMock()
        camara_mock = self._make_camara(1, "Cam Avenida Libertador 1234")

        # Configurar mock para la query directa Y para la query JOIN de aliases
        query_mock = MagicMock()
        query_mock.filter.return_value.all.return_value = [camara_mock]
        query_mock.join.return_value.filter.return_value.all.return_value = []
        session.query.return_value = query_mock

        camara, nombre_norm = buscar_camara("Av Libertador 1234", session)

        self.assertIsNotNone(camara)
        self.assertEqual(camara.nombre, "Cam Avenida Libertador 1234")

    @patch("modules.slack_baneo_notifier.camara_search.func")
    def test_no_encontrada_retorna_none(self, mock_func: MagicMock) -> None:
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        session = MagicMock()

        with (
            patch("modules.slack_baneo_notifier.camara_search._buscar_ilike_lista", return_value=[]),
            patch("modules.slack_baneo_notifier.camara_search._buscar_tokens_lista", return_value=[]),
        ):
            camara, nombre_norm = buscar_camara("XYZ Inexistente 9999", session)

        self.assertIsNone(camara)
        self.assertIsInstance(nombre_norm, str)

    def test_cra_no_se_expande_a_carrera(self) -> None:
        """'Cra' debe llegar a la DB sin transformarse en 'carrera'."""
        from modules.slack_baneo_notifier.camara_search import _expandir_abreviaturas, _normalizar

        expandido = _expandir_abreviaturas("Bot 2 Cra Poste 202 Vias FFCC Roca Hudson")
        normalizado = _normalizar(expandido)
        self.assertNotIn("carrera", normalizado)
        self.assertIn("cra", normalizado)

    def test_buscar_camara_con_cra_encuentra_por_ilike(self) -> None:
        """buscar_camara debe encontrar cámara con 'Cra' en nombre via ILIKE directo."""
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        camara_mock = self._make_camara(7, "Bot 2 Cra Poste 202 Vias FFCC Roca Hudson")
        session = MagicMock()
        query_mock = MagicMock()
        query_mock.filter.return_value.all.return_value = [camara_mock]
        query_mock.join.return_value.filter.return_value.all.return_value = []
        session.query.return_value = query_mock

        camara, nombre_norm = buscar_camara(
            "Bot 2 Cra Poste 202 Vias FFCC Roca Hudson", session
        )

        self.assertIsNotNone(camara)
        self.assertEqual(camara.nombre, "Bot 2 Cra Poste 202 Vias FFCC Roca Hudson")
        self.assertIn("cra", nombre_norm)
        self.assertNotIn("carrera", nombre_norm)

    def test_intento4_fallback_sin_expansion(self) -> None:
        """Intento 4 usa el nombre sin expansión cuando intento 1-2 fallan.

        Nota: el intento 3 (sin números) se omite porque '100' está en el input.
        Con 'Cam Clle Principal 100' → nombre_norm='cam calle principal 100',
        numeros_requeridos={'100'} → intento 3 saltado.
        El intento 4 usa nombre_raw_norm='cam clle principal 100' (diferente al
        norm expandido), y encuentra la cámara.
        """
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        camara_mock = self._make_camara(8, "Cam Clle Principal 100")
        call_count: list[int] = [0]

        def ilike_lista_side_effect(patron: str, session: Any) -> Any:
            call_count[0] += 1
            # Llamado 1 (intento 1, expanded): vacío
            # Llamado 2 (intento 4, raw-norm): retorna cámara
            if call_count[0] <= 1:
                return []
            return [camara_mock]

        with (
            patch("modules.slack_baneo_notifier.camara_search._buscar_ilike_lista", side_effect=ilike_lista_side_effect),
            patch("modules.slack_baneo_notifier.camara_search._buscar_tokens_lista", return_value=[]),
        ):
            camara, nombre_norm = buscar_camara("Cam Clle Principal 100", session=MagicMock())

        self.assertIsNotNone(camara)


# ─── Tests del handler del listener ────────────────────────────────────────────


class TestIngresoListenerHandleMessage(unittest.TestCase):
    """Tests del método _handle_message de IngresoListener."""

    def _make_listener(self) -> "IngresoListener":  # type: ignore[name-defined]  # noqa: F821
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event(
        self,
        text: str = "Cámara: Cam Test",
        channel: str = "C123",
        ts: str = "1234567890.000001",
        bot_id: str | None = None,
        subtype: str | None = None,
    ) -> dict:
        ev = {"text": text, "channel": channel, "ts": ts}
        if bot_id:
            ev["bot_id"] = bot_id
        if subtype:
            ev["subtype"] = subtype
        return ev

    def test_ignora_message_changed(self) -> None:
        """Eventos subtype=message_changed deben descartarse sin procesar."""
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(subtype="message_changed")

        listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_not_called()

    def test_acepta_bot_message_de_workflow(self) -> None:
        """Mensajes con subtype=bot_message de Workflows externos deben procesarse."""
        listener = self._make_listener()
        client_mock = MagicMock()
        texto_workflow = (
            "*Cual es el numero de Ticket MKT? o Numero de Linea*\nMKT-111111\n"
            "*Nombre: Nodo/Camara/botella*\nBot. estacion Alem linea B CF\n"
            "*Ingreso o Egreso*\nIngreso\n"
        )
        event = self._make_event(
            text=texto_workflow,
            channel="C123",
            bot_id="B0AV5BDDUJE",
            subtype="bot_message",
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Bot. estacion Alem linea B CF",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara",
                return_value=(None, "bot estacion alem linea b cf"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener._obtener_incidentes_activos_camara",
                return_value=[],
            ),
        ):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()

    def test_responde_camara_no_encontrada(self) -> None:
        """Cuando buscar_camara no encuentra la cámara, el listener la auto-registra."""
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Cám Inexistente 9999\nTécnico: Juan")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Cám Inexistente 9999"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara", return_value=(None, "cam inexistente 9999")),
            patch("modules.slack_baneo_notifier.listener._obtener_incidentes_activos_camara", return_value=[]),
        ):
            mock_session_cls.return_value = MagicMock()
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("bajo revisión", texto_respuesta)

    def test_responde_camara_libre(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = MagicMock()
        camara_mock.id = 42
        camara_mock.nombre = "Cam Libertad 1234"
        event = self._make_event(text="Cámara: Libertad 1234")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Libertad 1234"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara", return_value=(camara_mock, "libertad 1234")),
            patch("modules.slack_baneo_notifier.listener._obtener_incidentes_activos_camara", return_value=[]),
        ):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("Sin incidentes activos", texto_respuesta)
        self.assertIn("Cam Libertad 1234", texto_respuesta)

    def test_responde_camara_baneada(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = MagicMock()
        camara_mock.id = 7
        camara_mock.nombre = "Cam Baneada Central"
        incidente_mock = MagicMock()
        incidente_mock.id = 99
        incidente_mock.ticket_asociado = "TKT-001"
        incidente_mock.servicio_protegido_id = 5
        event = self._make_event(text="Cámara: Baneada Central")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Baneada Central"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara", return_value=(camara_mock, "baneada central")),
            patch("modules.slack_baneo_notifier.listener._obtener_incidentes_activos_camara", return_value=[incidente_mock]),
        ):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("ATENCIÓN", texto_respuesta)
        self.assertIn("#99", texto_respuesta)

    def test_ignora_si_listener_inactivo(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event()

        with (
            patch.object(listener, "_get_config", return_value=("C123", False, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
        ):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_not_called()

    def test_ignora_canal_incorrecto(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(channel="COTHER")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
        ):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_not_called()

    def test_is_running_false_antes_de_start(self) -> None:
        listener = self._make_listener()
        self.assertFalse(listener.is_running())

    def test_ignora_mensaje_usuario_con_filtro_solo_workflows(self) -> None:
        """Si solo_workflows=True y el evento no trae workflow_id, se ignora."""
        listener = self._make_listener()
        client_mock = MagicMock()
        # Evento de usuario (sin workflow_id)
        event = self._make_event()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, ["Wf0ABC123"], True)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
        ):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_not_called()

    def test_acepta_workflow_id_en_lista(self) -> None:
        """Si solo_workflows=True y el workflow_id coincide, se procesa."""
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event()
        event["workflow_id"] = "Wf0ABC123"

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, ["Wf0ABC123"], True)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Cam Test"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara", return_value=(None, "cam test")),
            patch("modules.slack_baneo_notifier.listener._obtener_incidentes_activos_camara", return_value=[]),
        ):
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()

    def test_ignora_workflow_id_no_en_lista(self) -> None:
        """Si solo_workflows=True y el workflow_id no está en la lista, se ignora."""
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event()
        event["workflow_id"] = "WfOTROID99"

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, ["Wf0ABC123"], True)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
        ):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_not_called()

    def test_acepta_cualquier_workflow_si_lista_vacia(self) -> None:
        """Si solo_workflows=True pero workflow_ids vacío, acepta cualquier Workflow."""
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event()
        event["workflow_id"] = "WfCUALQUIERA"

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], True)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Cam Test"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara", return_value=(None, "cam test")),
            patch("modules.slack_baneo_notifier.listener._obtener_incidentes_activos_camara", return_value=[]),
        ):
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()


class TestObtenerIncidentesActivosCamara(unittest.TestCase):
    """Tests para _obtener_incidentes_activos_camara con estados LIBRE, DETECTADA y BANEADA."""

    def _make_camara(self, estado: Any) -> Any:
        camara = MagicMock()
        camara.id = 42
        camara.estado = estado
        return camara

    def test_detectada_sin_incidentes_retorna_vacio(self) -> None:
        """DETECTADA se trata como LIBRE — retorna [] sin consultar incidentes."""
        from modules.slack_baneo_notifier.listener import _obtener_incidentes_activos_camara

        with patch("db.models.infra.CamaraEstado") as mock_estado:
            mock_estado.BANEADA = "BANEADA"
            camara = self._make_camara("DETECTADA")
            result = _obtener_incidentes_activos_camara(camara, MagicMock())
        self.assertEqual(result, [])

    def test_libre_retorna_vacio(self) -> None:
        """LIBRE retorna [] sin consultar incidentes."""
        from modules.slack_baneo_notifier.listener import _obtener_incidentes_activos_camara

        with patch("db.models.infra.CamaraEstado") as mock_estado:
            mock_estado.BANEADA = "BANEADA"
            camara = self._make_camara("LIBRE")
            result = _obtener_incidentes_activos_camara(camara, MagicMock())
        self.assertEqual(result, [])


# ─── Tests de limpieza de puntuación y sinónimos ───────────────────────────────


class TestLimpiezaYSinonimos(unittest.TestCase):
    """Prueba _limpiar_puntuacion, _aplicar_sinonimos y flujo integrado."""

    def test_limpiar_puntuacion_coma(self) -> None:
        """Las comas se eliminan y se normalizan espacios."""
        from modules.slack_baneo_notifier.camara_search import _limpiar_puntuacion
        resultado = _limpiar_puntuacion("Cámara, Bartolomé Mitre 440. CF")
        self.assertNotIn(",", resultado)

    def test_limpiar_puntuacion_punto_final(self) -> None:
        """Puntos al final de palabra se eliminan."""
        from modules.slack_baneo_notifier.camara_search import _limpiar_puntuacion
        resultado = _limpiar_puntuacion("Bot. estacion Alem")
        # el punto es reemplazado por espacio
        self.assertNotIn("Bot.", resultado)

    def test_limpiar_puntuacion_guion_con_espacios(self) -> None:
        """Guiones con espacios se reemplazan por espacio simple."""
        from modules.slack_baneo_notifier.camara_search import _limpiar_puntuacion
        resultado = _limpiar_puntuacion("Terminal Norte - Acceso Sur")
        self.assertNotIn(" - ", resultado)
        self.assertIn("Norte", resultado)
        self.assertIn("Acceso", resultado)

    def test_sinonimo_botella_a_bot(self) -> None:
        """'botella' como palabra completa se convierte a 'bot' post-normalización."""
        from modules.slack_baneo_notifier.camara_search import _aplicar_sinonimos
        resultado = _aplicar_sinonimos("botella 2 cra poste 202")
        self.assertIn("bot", resultado)
        self.assertNotIn("botella", resultado)

    def test_sinonimo_camara_a_cra(self) -> None:
        """'camara' (post-unidecode de 'cámara') se convierte a 'cra'."""
        from modules.slack_baneo_notifier.camara_search import _aplicar_sinonimos, _normalizar
        # Simular flujo real: unidecode('cámara') → 'camara'
        texto_norm = _normalizar("Cámara Bartolomé Mitre 440")
        resultado = _aplicar_sinonimos(texto_norm)
        self.assertIn("cra", resultado)
        self.assertNotIn("camara", resultado)

    def test_buscar_camara_por_alias(self) -> None:
        """buscar_camara encuentra una cámara a través de su alias en CamaraAlias."""
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        camara_mock = MagicMock()
        camara_mock.id = 5
        camara_mock.nombre = "Bot 2 Cra Poste 202"

        with patch("modules.slack_baneo_notifier.camara_search._buscar_ilike_lista", return_value=[camara_mock]):
            camara, _ = buscar_camara("Botella 2 Cra Poste 202", session=MagicMock())

        self.assertIsNotNone(camara)
        self.assertEqual(camara.nombre, "Bot 2 Cra Poste 202")

    def test_autoregistro_camara_pendiente(self) -> None:
        """Cuando buscar_camara retorna None, listener registra cámara como PENDIENTE_REVISION."""
        from modules.slack_baneo_notifier.listener import IngresoListener

        listener = IngresoListener(bot_token="xoxb-test", app_token="xapp-test")
        client_mock = MagicMock()
        event: dict = {
            "text": "Cámara: CRA Inexistente XYZ 9999",
            "channel": "C123",
            "ts": "1234567890.000001",
        }

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="CRA Inexistente XYZ 9999"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara", return_value=(None, "cra inexistente xyz 9999")),
        ):
            # El listener usa session = SessionLocal() directamente (no context manager)
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(event, client_mock)

        # Verificar que se llamó session.add (auto-registro)
        session_mock.add.assert_called_once()
        session_mock.commit.assert_called_once()

        # Verificar que la respuesta indica auto-registro
        client_mock.chat_postMessage.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("bajo revisión", texto)


# ─── Tests de filtros: número estricto y exclusión de Bots secundarios ────────


class TestFiltrosNumeroBot(unittest.TestCase):
    """Prueba las nuevas reglas de búsqueda estricta por número y exclusión de Bot 2+."""

    def _make_camara(self, id_: int, nombre: str) -> MagicMock:
        cam = MagicMock()
        cam.id = id_
        cam.nombre = nombre
        return cam

    def test_filtro_numero_estricto_descarta_numero_incorrecto(self) -> None:
        """Si el input contiene '440', no debe devolverse una cámara con '399'."""
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        cam_399 = self._make_camara(1, "Cra Bartolome Mitre 399")
        cam_440 = self._make_camara(2, "Cra Bartolome Mitre 440")

        # La query retorna ambas candidatas; la 399 debe ser descartada
        with patch(
            "modules.slack_baneo_notifier.camara_search._buscar_ilike_lista",
            return_value=[cam_399, cam_440],
        ):
            camara, _ = buscar_camara("Cámara, Bartolomé Mitre 440. CF", session=MagicMock())

        self.assertIsNotNone(camara)
        self.assertEqual(camara.nombre, "Cra Bartolome Mitre 440")

    def test_filtro_numero_sin_numero_en_input_no_filtra(self) -> None:
        """Sin número en el input, ningún candidato se descarta por número."""
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        cam_399 = self._make_camara(1, "Cra Bartolome Mitre 399")

        with patch(
            "modules.slack_baneo_notifier.camara_search._buscar_ilike_lista",
            return_value=[cam_399],
        ):
            camara, _ = buscar_camara("Cra Bartolome Mitre", session=MagicMock())

        self.assertIsNotNone(camara)
        self.assertEqual(camara.nombre, "Cra Bartolome Mitre 399")

    def test_filtro_bot_secundario_excluido_sin_mencion_bot(self) -> None:
        """Si el usuario NO menciona 'bot'/'botella', los 'Bot 2+' deben excluirse."""
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        cam_bot2 = self._make_camara(3, "Bot 2 Cra Bartolome Mitre 440")

        with patch(
            "modules.slack_baneo_notifier.camara_search._buscar_ilike_lista",
            return_value=[cam_bot2],
        ):
            # Input sin "bot" ni "botella"
            camara, _ = buscar_camara("Cra Bartolome Mitre 440", session=MagicMock())

        self.assertIsNone(camara)

    def test_filtro_bot_secundario_permitido_con_botella(self) -> None:
        """Si el usuario menciona 'botella', los 'Bot 2+' NO deben excluirse."""
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        cam_bot2 = self._make_camara(3, "Bot 2 Cra Bartolome Mitre 440")

        with patch(
            "modules.slack_baneo_notifier.camara_search._buscar_ilike_lista",
            return_value=[cam_bot2],
        ):
            camara, _ = buscar_camara("Botella 2 Cra Bartolome Mitre 440", session=MagicMock())

        self.assertIsNotNone(camara)
        self.assertEqual(camara.nombre, "Bot 2 Cra Bartolome Mitre 440")

    def test_filtro_bot_principal_no_excluido(self) -> None:
        """'Bot ' sin número secundario (Bot principal) nunca se excluye."""
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        cam_bot1 = self._make_camara(4, "Bot Cra Bartolome Mitre 440")

        with patch(
            "modules.slack_baneo_notifier.camara_search._buscar_ilike_lista",
            return_value=[cam_bot1],
        ):
            # Input sin "bot"/"botella" pero el candidato es el Bot principal
            camara, _ = buscar_camara("Cra Bartolome Mitre 440", session=MagicMock())

        self.assertIsNotNone(camara)
        self.assertEqual(camara.nombre, "Bot Cra Bartolome Mitre 440")

    def test_intento3_omitido_cuando_hay_numeros(self) -> None:
        """Con números en el input, el intento 3 (sin números) se salta."""
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        call_count: list[int] = [0]
        patrones_llamados: list[str] = []

        def ilike_lista_side_effect(patron: str, session: Any) -> list:
            call_count[0] += 1
            patrones_llamados.append(patron)
            return []  # Siempre vacío; nos interesa cuántas veces se llama

        with (
            patch("modules.slack_baneo_notifier.camara_search._buscar_ilike_lista", side_effect=ilike_lista_side_effect),
            patch("modules.slack_baneo_notifier.camara_search._buscar_tokens_lista", return_value=[]),
        ):
            camara, _ = buscar_camara("Cra Mitre 440", session=MagicMock())

        self.assertIsNone(camara)
        # Con "440" en el input, intento 3 se omite.
        # El nombre raw_norm == nombre_norm para "Cra Mitre 440" (Cra no se expande),
        # por lo que intento 4 también se omite.
        # Solo intento 1 → 1 llamada a _buscar_ilike_lista.
        self.assertEqual(call_count[0], 1)
        # Verificar que nunca se llamó con un patrón sin "440"
        for p in patrones_llamados:
            self.assertIn("440", p)


# ─── Tests del parser multi-bot ────────────────────────────────────────────────


class TestDetectarMultiBot(unittest.TestCase):
    """Prueba detectar_multi_bot() — detección y expansión de 'Botella 1 y 2'."""

    def setUp(self) -> None:
        from modules.slack_baneo_notifier.camara_search import detectar_multi_bot
        self.detectar = detectar_multi_bot

    def test_botella_1_y_2_genera_dos_strings(self) -> None:
        """Patrón canónico: 'Bartolomé Mitre 301. Botella 1 y 2. CF'."""
        resultado = self.detectar("Bartolomé Mitre 301. Botella 1 y 2. CF")
        self.assertIsNotNone(resultado)
        assert resultado is not None
        self.assertEqual(len(resultado), 2)
        # Botella 1 → solo base sin prefijo Bot
        self.assertNotIn("Bot 1", resultado[0])
        self.assertIn("Mitre 301", resultado[0])
        # Botella 2 → prefijo "Bot 2" + base
        self.assertIn("Bot 2", resultado[1])
        self.assertIn("Mitre 301", resultado[1])

    def test_bot_1_y_2_minusculas(self) -> None:
        """Variante con 'bot' en minúscula."""
        resultado = self.detectar("bot 1 y 2 calle principal 100")
        self.assertIsNotNone(resultado)
        assert resultado is not None
        self.assertEqual(len(resultado), 2)
        self.assertNotIn("Bot 1", resultado[0])
        self.assertIn("Bot 2", resultado[1])

    def test_bot_2_y_3_ambos_con_prefijo(self) -> None:
        """Cuando ambos números son ≥2, ambos llevan prefijo 'Bot N'."""
        resultado = self.detectar("Bot 2 y 3 Calle Real 50")
        self.assertIsNotNone(resultado)
        assert resultado is not None
        self.assertEqual(len(resultado), 2)
        self.assertIn("Bot 2", resultado[0])
        self.assertIn("Bot 3", resultado[1])

    def test_sin_patron_multi_bot_retorna_none(self) -> None:
        """Sin patrón 'bot N y M', retorna None."""
        self.assertIsNone(self.detectar("Cra Mitre 440 sin botellas"))
        self.assertIsNone(self.detectar("Botella 2"))
        self.assertIsNone(self.detectar(""))

    def test_botellas_plural(self) -> None:
        """Variante plural: 'Botellas 1 y 2'."""
        resultado = self.detectar("Botellas 1 y 2 Av Principal 300 CF")
        self.assertIsNotNone(resultado)

    def test_base_sin_cf_puntuacion_limpia(self) -> None:
        """La base queda limpia de puntuación sobrante."""
        resultado = self.detectar("Bartolomé Mitre 301. Botella 1 y 2. CF")
        assert resultado is not None
        # La base no debe terminar en punto
        for s in resultado:
            self.assertFalse(s.strip().endswith("."), f"Trailing dot en: {s!r}")


class TestHandleMessageMultiBot(unittest.TestCase):
    """Prueba que el listener responde por cada cámara cuando se detecta multi-bot."""

    def _make_listener(self) -> Any:
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _evento(self, texto: str) -> dict:
        return {
            "text": texto,
            "ts": "1234567890.000001",
            "channel": "C_TEST",
        }

    def test_multi_bot_responde_dos_estados(self) -> None:
        """Un mensaje con 'Botella 1 y 2' genera una respuesta con ambas cámaras."""
        listener = self._make_listener()

        cam1 = MagicMock()
        cam1.nombre = "Cra Bartolomé Mitre 301"
        cam2 = MagicMock()
        cam2.nombre = "Bot 2 Cra Bartolomé Mitre 301"

        client_mock = MagicMock()
        config_mock = ("C_TEST", True, [], False)

        # buscar_camara: primera llamada → cam1, segunda → cam2
        buscar_side = [
            (cam1, "cra bartolome mitre 301"),
            (cam2, "bot 2 cra bartolome mitre 301"),
        ]

        with patch(
            "modules.slack_baneo_notifier.listener.IngresoListener._get_config",
            return_value=config_mock,
        ):
            with patch(
                "modules.slack_baneo_notifier.listener.buscar_camara",
                side_effect=buscar_side,
            ):
                with patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_sess:
                    mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
                    mock_sess.return_value.__exit__ = MagicMock(return_value=False)
                    # _get_config se llama con session, usamos patch directo
                    listener._handle_message(
                        self._evento("Cámara: Bartolomé Mitre 301. Botella 1 y 2. CF"),
                        client_mock,
                    )

        client_mock.chat_postMessage.assert_called_once()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        # Ambos nombres deben aparecer en el texto compuesto
        self.assertIn("Cra Bartolomé Mitre 301", texto_respuesta)
        self.assertIn("Bot 2 Cra Bartolomé Mitre 301", texto_respuesta)

    def test_sin_multi_bot_flujo_normal(self) -> None:
        """Sin patrón multi-bot, buscar_camara se llama una sola vez."""
        listener = self._make_listener()

        cam = MagicMock()
        cam.nombre = "Cra Mitre 440"
        client_mock = MagicMock()
        config_mock = ("C_TEST", True, [], False)

        with patch(
            "modules.slack_baneo_notifier.listener.IngresoListener._get_config",
            return_value=config_mock,
        ):
            with patch(
                "modules.slack_baneo_notifier.listener.buscar_camara",
                return_value=(cam, "cra mitre 440"),
            ) as mock_buscar:
                with patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_sess:
                    mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
                    mock_sess.return_value.__exit__ = MagicMock(return_value=False)
                    listener._handle_message(
                        self._evento("Cámara: Cra Mitre 440"),
                        client_mock,
                    )

        self.assertEqual(mock_buscar.call_count, 1)


if __name__ == "__main__":
    unittest.main()
