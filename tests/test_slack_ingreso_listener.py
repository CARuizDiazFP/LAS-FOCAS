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

        # Primera consulta (ILIKE) retorna la cámara
        query_mock = MagicMock()
        query_mock.filter.return_value.all.return_value = [camara_mock]
        session.query.return_value = query_mock

        camara, nombre_norm = buscar_camara("Av Libertador 1234", session)

        self.assertIsNotNone(camara)
        self.assertEqual(camara.nombre, "Cam Avenida Libertador 1234")

    @patch("modules.slack_baneo_notifier.camara_search.func")
    def test_no_encontrada_retorna_none(self, mock_func: MagicMock) -> None:
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        session = MagicMock()

        with (
            patch("modules.slack_baneo_notifier.camara_search._buscar_ilike", return_value=None),
            patch("modules.slack_baneo_notifier.camara_search._buscar_tokens", return_value=None),
        ):
            camara, nombre_norm = buscar_camara("XYZ Inexistente 9999", session)

        self.assertIsNone(camara)
        self.assertIsInstance(nombre_norm, str)


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
    ) -> dict:
        ev = {"text": text, "channel": channel, "ts": ts}
        if bot_id:
            ev["bot_id"] = bot_id
        return ev

    def test_ignora_mensajes_de_bots(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(bot_id="B999ABC")

        with patch.object(listener, "_get_config", return_value=("C123", True)):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_not_called()

    def test_responde_camara_no_encontrada(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Cám Inexistente 9999\nTécnico: Juan")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Cám Inexistente 9999"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara", return_value=(None, "cam inexistente 9999")),
            patch("modules.slack_baneo_notifier.listener._obtener_incidentes_activos_camara", return_value=[]),
        ):
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("No encontré", texto_respuesta)

    def test_responde_camara_libre(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = MagicMock()
        camara_mock.id = 42
        camara_mock.nombre = "Cam Libertad 1234"
        event = self._make_event(text="Cámara: Libertad 1234")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True)),
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
            patch.object(listener, "_get_config", return_value=("C123", True)),
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
            patch.object(listener, "_get_config", return_value=("C123", False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
        ):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_not_called()

    def test_ignora_canal_incorrecto(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(channel="COTHER")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
        ):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_not_called()

    def test_is_running_false_antes_de_start(self) -> None:
        listener = self._make_listener()
        self.assertFalse(listener.is_running())


if __name__ == "__main__":
    unittest.main()
