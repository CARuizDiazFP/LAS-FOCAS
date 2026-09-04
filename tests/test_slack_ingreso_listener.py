# Nombre de archivo: test_slack_ingreso_listener.py
# Ubicación de archivo: tests/test_slack_ingreso_listener.py
# Descripción: Tests unitarios para el listener de ingresos técnicos via Slack Socket Mode

"""
Tests para:
 - camara_search.extraer_nombre_camara()
 - camara_search.buscar_camara()
 - listener.IngresoListener._handle_message()  (casos ok, baneada, no encontrada, ignorar bot)
 - listener.IngresoListener._construir_respuesta_camara() usa buscar_camara_o_botella_cromo()
   (Tarea 2, 2026-08-23) en vez de buscar_camara() directo — los tests que ejercitan
   _handle_message/_construir_respuesta_camara mockean el punto de uso
   (modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo, ver _resultado_camara()
   abajo); los que ejercitan camara_search.buscar_camara() en forma aislada no cambian.
 - listener.IngresoListener._procesar_seguimiento_empalme()  (hilo esperando ID de empalme)
"""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import MagicMock, patch, call

os.environ.setdefault("TESTING", "true")

from core.services.cromo.camara_botella_busqueda import ResultadoBusquedaExtendida


def _resultado_camara(camara: Any, nombre_norm: str = "") -> ResultadoBusquedaExtendida:
    """Wrapper de test: arma un `ResultadoBusquedaExtendida` con `fuente='camara'` si hay match, o
    sin match (`fuente=None`, `camara=None`) si no — evita repetir los 4 campos del dataclass en
    cada mock de `buscar_camara_o_botella_cromo` (Tarea 2, reemplaza `buscar_camara` directo en
    `_construir_respuesta_camara`). No cubre el caso `fuente="cromo_botella"` porque ningún test de
    este archivo necesita distinguirlo — sólo le importa a `_construir_respuesta_camara` si
    `resultado.camara` es `None` o no."""
    return ResultadoBusquedaExtendida(
        camara=camara, nombre_norm=nombre_norm, fuente="camara" if camara is not None else None, botella=None
    )


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

    def test_campo_camara_con_coma(self) -> None:
        """Regresión: 'Cámara, nombre' (coma en lugar de dos puntos) debe extraer el nombre."""
        texto = "Cámara, Bartolomé Mitre 301. Botella 1 y 2. CF"
        result = self.extraer(texto)
        self.assertEqual(result, "Bartolomé Mitre 301. Botella 1 y 2. CF")

    def test_campo_camara_dos_puntos_sigue_funcionando(self) -> None:
        """Retrocompatibilidad: 'Cámara: nombre' (dos puntos) sigue funcionando."""
        texto = "Cámara: Bartolomé Mitre 301 CF"
        result = self.extraer(texto)
        self.assertEqual(result, "Bartolomé Mitre 301 CF")


# ─── Tests de extracción de tipo de movimiento ────────────────────────────────


class TestExtraerTipoMovimiento(unittest.TestCase):
    """Prueba camara_search.extraer_tipo_movimiento()."""

    def setUp(self) -> None:
        from modules.slack_baneo_notifier.camara_search import extraer_tipo_movimiento
        self.extraer = extraer_tipo_movimiento

    def test_ingreso_presente(self) -> None:
        """Extrae 'Ingreso' cuando el campo está presente."""
        texto = (
            "*Nombre: Nodo/Camara/botella*\nRuta 8 Km 34 MALVINAS ARGENTINAS\n"
            "*Ingreso o Egreso*\nIngreso\n"
            "Persona que solicito La Autorizacion\n<@U0AUB6CRE4A|Rider Fernández>\n"
        )
        result = self.extraer(texto)
        self.assertEqual(result, "Ingreso")

    def test_egreso_presente(self) -> None:
        """Extrae 'Egreso' cuando el campo está presente."""
        texto = (
            "*Nombre: Nodo/Camara/botella*\nRuta 8 Km 34 MALVINAS ARGENTINAS\n"
            "*Ingreso o Egreso*\nEgreso\n"
            "Persona que solicito La Autorizacion\n<@U0AUB6CRE4A|Rider Fernández>\n"
        )
        result = self.extraer(texto)
        self.assertEqual(result, "Egreso")

    def test_campo_ausente_retorna_none(self) -> None:
        """Retorna None cuando el campo 'Ingreso o Egreso' no está presente."""
        texto = (
            "*Nombre: Nodo/Camara/botella*\nRuta 8 Km 34 MALVINAS ARGENTINAS\n"
            "Persona que solicito La Autorizacion\n<@U0AUB6CRE4A|Rider Fernández>\n"
        )
        result = self.extraer(texto)
        self.assertIsNone(result)

    def test_ejemplo_real_completo(self) -> None:
        """Usa el texto de ejemplo real del plan como fixture."""
        texto = (
            "*Cual es el numero de Ticket MKT? o Numero de Linea*\n122833\n"
            "*Es Camara Critica?*\nNo\n"
            "*Nombre: Nodo/Camara/botella*\n"
            "Ruta 8 Km 34 MALVINAS ARGENTINAS - FRAGATA HEROINA 4803 - DEL VISO - Buenos Aires\n"
            "*Ingreso o Egreso*\nIngreso\n"
            "*Hubo intervencion sobre la/las Fibras?*\nSI\n"
            "Persona que solicito La Autorizacion\n"
            "<@U0AUB6CRE4A|Rider Fernández>\n"
        )
        result = self.extraer(texto)
        self.assertEqual(result, "Ingreso")

    def test_insensible_a_mayusculas_minusculas_normaliza_ingreso(self) -> None:
        """Regresión: el regex es (?i) pero group(1) preserva el casing original de la fuente.

        Si el Workflow de Slack llega a mandar 'ingreso' en minúsculas, el valor
        crudo capturado no debe propagarse tal cual — debe normalizarse a
        'Ingreso' exacto, porque `registrar_movimiento_ingreso` hace un chequeo
        de string exacto y trata cualquier otra cosa como Egreso.
        """
        texto = (
            "*Nombre: Nodo/Camara/botella*\nRuta 8 Km 34 MALVINAS ARGENTINAS\n"
            "*Ingreso o Egreso*\ningreso\n"
            "Persona que solicito La Autorizacion\n<@U0AUB6CRE4A|Rider Fernández>\n"
        )
        result = self.extraer(texto)
        self.assertEqual(result, "Ingreso")

    def test_insensible_a_mayusculas_minusculas_normaliza_egreso(self) -> None:
        """Misma regresión que arriba, pero con 'EGRESO' en mayúsculas y para Egreso."""
        texto = (
            "*Nombre: Nodo/Camara/botella*\nRuta 8 Km 34 MALVINAS ARGENTINAS\n"
            "*Ingreso o Egreso*\nEGRESO\n"
            "Persona que solicito La Autorizacion\n<@U0AUB6CRE4A|Rider Fernández>\n"
        )
        result = self.extraer(texto)
        self.assertEqual(result, "Egreso")


# ─── Tests de extracción de Slack user ID de autorización ────────────────────


class TestExtraerSlackUserIdAutorizacion(unittest.TestCase):
    """Prueba camara_search.extraer_slack_user_id_autorizacion()."""

    def setUp(self) -> None:
        from modules.slack_baneo_notifier.camara_search import extraer_slack_user_id_autorizacion
        self.extraer = extraer_slack_user_id_autorizacion

    def test_mencion_con_nombre_mostrado(self) -> None:
        """Extrae user ID de mención con nombre mostrado <@U.../Nombre>."""
        texto = (
            "*Nombre: Nodo/Camara/botella*\nRuta 8 Km 34\n"
            "Persona que solicito La Autorizacion\n"
            "<@U0AUB6CRE4A|Rider Fernández>\n"
        )
        result = self.extraer(texto)
        self.assertEqual(result, "U0AUB6CRE4A")

    def test_mencion_sin_nombre_mostrado(self) -> None:
        """Extrae user ID de mención sin nombre mostrado <@U...>."""
        texto = (
            "*Nombre: Nodo/Camara/botella*\nRuta 8 Km 34\n"
            "Persona que solicito La Autorizacion\n"
            "<@U1234567890>\n"
        )
        result = self.extraer(texto)
        self.assertEqual(result, "U1234567890")

    def test_campo_ausente_retorna_none(self) -> None:
        """Retorna None cuando el campo de autorización no está presente."""
        texto = (
            "*Nombre: Nodo/Camara/botella*\nRuta 8 Km 34\n"
            "*Ingreso o Egreso*\nIngreso\n"
        )
        result = self.extraer(texto)
        self.assertIsNone(result)

    def test_ejemplo_real_completo(self) -> None:
        """Usa el texto de ejemplo real del plan como fixture."""
        texto = (
            "*Cual es el numero de Ticket MKT? o Numero de Linea*\n122833\n"
            "*Es Camara Critica?*\nNo\n"
            "*Nombre: Nodo/Camara/botella*\n"
            "Ruta 8 Km 34 MALVINAS ARGENTINAS - FRAGATA HEROINA 4803 - DEL VISO - Buenos Aires\n"
            "*Ingreso o Egreso*\nIngreso\n"
            "*Hubo intervencion sobre la/las Fibras?*\nSI\n"
            "Persona que solicito La Autorizacion\n"
            "<@U0AUB6CRE4A|Rider Fernández>\n"
        )
        result = self.extraer(texto)
        self.assertEqual(result, "U0AUB6CRE4A")


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
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(None, "bot estacion alem linea b cf"),
            ),
        ):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()

    def test_responde_camara_no_encontrada(self) -> None:
        """Cuando buscar_camara no encuentra la cámara, el listener NUNCA bloquea el ingreso — sólo
        registra el caso para revisión manual (2026-08-11, ya no auto-registra una Camara)."""
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Cám Inexistente 9999\nTécnico: Juan")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Cám Inexistente 9999"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo", return_value=_resultado_camara(None, "cam inexistente 9999")),
        ):
            mock_session_cls.return_value = MagicMock()
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("Podés continuar con el ingreso", texto_respuesta)
        # Invitación al seguimiento por ID de empalme (Tarea 2, 2026-08-23).
        self.assertIn("ID de empalme", texto_respuesta)
        self.assertNotIn("bajo revisión", texto_respuesta)

    def test_responde_camara_libre(self) -> None:
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = MagicMock()
        camara_mock.id = 42
        camara_mock.nombre = "Cam Libertad 1234"
        event = self._make_event(text="Cámara: Libertad 1234")
        contexto_libre = CamaraEstadoContexto(
            camara_id=42, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Libertad 1234"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo", return_value=_resultado_camara(camara_mock, "libertad 1234")),
            patch("modules.slack_baneo_notifier.listener.get_camara_estado_contexto", return_value=contexto_libre),
        ):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("Sin incidentes activos", texto_respuesta)
        self.assertIn("Cam Libertad 1234", texto_respuesta)

    def test_responde_camara_baneada(self) -> None:
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

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
        contexto_con_incidente = CamaraEstadoContexto(
            camara_id=7, estado_actual=CamaraEstado.BANEADA, estado_sugerido=CamaraEstado.BANEADA,
            tiene_baneo_activo=True, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[incidente_mock], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Baneada Central"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo", return_value=_resultado_camara(camara_mock, "baneada central")),
            patch("modules.slack_baneo_notifier.listener.get_camara_estado_contexto", return_value=contexto_con_incidente),
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
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo", return_value=_resultado_camara(None, "cam test")),
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
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo", return_value=_resultado_camara(None, "cam test")),
        ):
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()


# ─── Tests de registro de movimiento Ingreso/Egreso (Tarea 4) ─────────────────


class TestRegistrarMovimientoIngreso(unittest.TestCase):
    """Prueba el wiring de la Tarea 4: `_construir_respuesta_camara` (vía `_handle_message`) debe
    invocar `registrar_movimiento_ingreso` (Tarea 3) como efecto secundario cuando hay match Y el
    texto completo del evento trae el campo 'Ingreso o Egreso' parseable — mockeado a nivel del
    import real en `modules.slack_baneo_notifier.listener` (el punto de uso, no la definición en
    `core/services/ingreso_service.py`). La respuesta de Slack no debe cambiar nunca por esto."""

    TEXTO_CON_INGRESO = (
        "*Nombre: Nodo/Camara/botella*\nRuta 8 Km 34 MALVINAS ARGENTINAS\n"
        "*Ingreso o Egreso*\nIngreso\n"
        "Persona que solicito La Autorizacion\n<@U0AUB6CRE4A|Rider Fernández>\n"
    )
    TEXTO_CON_EGRESO = (
        "*Nombre: Nodo/Camara/botella*\nRuta 8 Km 34 MALVINAS ARGENTINAS\n"
        "*Ingreso o Egreso*\nEgreso\n"
        "Persona que solicito La Autorizacion\n<@U0AUB6CRE4A|Rider Fernández>\n"
    )
    TEXTO_SIN_MOVIMIENTO = (
        "*Nombre: Nodo/Camara/botella*\nRuta 8 Km 34 MALVINAS ARGENTINAS\n"
    )

    def _make_listener(self) -> Any:
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event(self, text: str, channel: str = "C123", ts: str = "1234567890.000001") -> dict:
        return {"text": text, "channel": channel, "ts": ts}

    def _make_camara(self, id_: int = 42, nombre: str = "Cam Libertad 1234") -> MagicMock:
        cam = MagicMock()
        cam.id = id_
        cam.nombre = nombre
        return cam

    def test_registra_movimiento_cuando_hay_match_camara_directa_y_texto_trae_ingreso(self) -> None:
        """fuente='camara' (match directo, sin pasar por CromoBotella) + campo 'Ingreso o Egreso'
        presente, grupo LIBRE (no bloqueado) → registrar_movimiento_ingreso se llama con botella=None
        y el nombre YA resuelto por `resolver_nombre_tecnico`."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = self._make_camara()
        camara_mock.estado = CamaraEstado.LIBRE
        contexto_libre = CamaraEstadoContexto(
            camara_id=camara_mock.id, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Ruta 8 Km 34 MALVINAS ARGENTINAS",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "ruta 8 km 34 malvinas argentinas"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=contexto_libre,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_nombre_tecnico",
                return_value="Rider Fernández",
            ) as mock_resolver,
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
        ):
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(self._make_event(text=self.TEXTO_CON_INGRESO), client_mock)

        mock_resolver.assert_called_once_with(client_mock, "U0AUB6CRE4A")
        mock_registrar.assert_called_once_with(
            session_mock,
            camara=camara_mock,
            botella=None,
            tipo_movimiento="Ingreso",
            tecnico_nombre="Rider Fernández",
        )
        # La respuesta de Slack de siempre no debe verse afectada por el registro.
        client_mock.chat_postMessage.assert_called_once()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("✅", texto_respuesta)

    def test_registra_movimiento_con_botella_cromo_y_egreso(self) -> None:
        """fuente='cromo_botella' (match resuelto vía CromoBotella) → registrar_movimiento_ingreso
        recibe la `botella` real, no None. Cubre también tipo_movimiento='Egreso', grupo LIBRE (no
        bloqueado) y el nombre YA resuelto por `resolver_nombre_tecnico`."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = self._make_camara(id_=7, nombre="Cam Resuelta Desde Botella")
        camara_mock.estado = CamaraEstado.LIBRE
        botella_mock = MagicMock()
        botella_mock.n_id = 999

        resultado = ResultadoBusquedaExtendida(
            camara=camara_mock,
            nombre_norm="ruta 8 km 34 malvinas argentinas",
            fuente="cromo_botella",
            botella=botella_mock,
        )
        contexto_libre = CamaraEstadoContexto(
            camara_id=camara_mock.id, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Ruta 8 Km 34 MALVINAS ARGENTINAS",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=resultado,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=contexto_libre,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_nombre_tecnico",
                return_value="Rider Fernández",
            ),
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
        ):
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(self._make_event(text=self.TEXTO_CON_EGRESO), client_mock)

        mock_registrar.assert_called_once_with(
            session_mock,
            camara=camara_mock,
            botella=botella_mock,
            tipo_movimiento="Egreso",
            tecnico_nombre="Rider Fernández",
        )
        client_mock.chat_postMessage.assert_called_once()

    def test_no_registra_movimiento_cuando_texto_no_trae_campo(self) -> None:
        """Hay match de cámara, pero el texto no trae 'Ingreso o Egreso' → no se escribe nada. No
        necesita mockear `resolver_nombre_tecnico` — la rama de registro corta antes de llegar a
        resolverlo (`extraer_tipo_movimiento` devuelve `None`). `get_camara_estado_contexto` sí se
        mockea porque `_evaluar_estado_acceso_camara` corre siempre que hay match de cámara,
        independientemente del campo 'Ingreso o Egreso' (reemplaza el mock retirado de
        `_obtener_incidentes_activos_camara`)."""
        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = self._make_camara()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Ruta 8 Km 34 MALVINAS ARGENTINAS",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "ruta 8 km 34 malvinas argentinas"),
            ),
            patch("modules.slack_baneo_notifier.listener.get_camara_estado_contexto", return_value=None),
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
        ):
            listener._handle_message(self._make_event(text=self.TEXTO_SIN_MOVIMIENTO), client_mock)

        mock_registrar.assert_not_called()
        client_mock.chat_postMessage.assert_called_once()

    def test_no_registra_movimiento_cuando_no_hay_match(self) -> None:
        """Rama sin match (camara is None) → nunca se llega a registrar_movimiento_ingreso, incluso
        si el texto trae 'Ingreso o Egreso'. `IngresoSinMatch` sigue registrándose igual que antes
        (comportamiento no tocado por esta tarea)."""
        listener = self._make_listener()
        client_mock = MagicMock()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Ruta 8 Km 34 MALVINAS ARGENTINAS",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(None, "ruta 8 km 34 malvinas argentinas"),
            ),
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
        ):
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(self._make_event(text=self.TEXTO_CON_INGRESO), client_mock)

        mock_registrar.assert_not_called()
        # IngresoSinMatch sigue registrándose igual que antes de esta tarea.
        session_mock.add.assert_called_once()
        session_mock.commit.assert_called_once()
        client_mock.chat_postMessage.assert_called_once()

    def test_no_registra_movimiento_cuando_ambiguo(self) -> None:
        """AmbiguousSearchError se lanza antes de que exista un `resultado.camara` — el helper
        nunca se alcanza, sin cambios respecto al manejo previo de la excepción."""
        from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError

        listener = self._make_listener()
        client_mock = MagicMock()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Ruta 8",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                side_effect=AmbiguousSearchError("Ruta 8", 3, []),
            ),
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
        ):
            listener._handle_message(self._make_event(text=self.TEXTO_CON_INGRESO), client_mock)

        mock_registrar.assert_not_called()
        client_mock.chat_postMessage.assert_called_once()

    def test_no_registra_movimiento_cuando_es_nodo(self) -> None:
        """Mensajes de Nodo se excluyen ANTES de cualquier búsqueda (ver `TestExclusionNodo`) — el
        helper nunca se alcanza, ni siquiera se llega a instanciar `resultado`."""
        listener = self._make_listener()
        client_mock = MagicMock()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Nodo Pilar",
            ),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo") as mock_buscar,
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
        ):
            listener._handle_message(self._make_event(text=self.TEXTO_CON_INGRESO), client_mock)

        mock_buscar.assert_not_called()
        mock_registrar.assert_not_called()
        client_mock.chat_postMessage.assert_not_called()

    def test_excepcion_en_registrar_movimiento_no_rompe_respuesta_slack(self) -> None:
        """Si registrar_movimiento_ingreso lanza cualquier excepción, se loguea y se ignora — la
        respuesta de Slack se envía igual (el bot en vivo nunca debe dejar de responder por un
        error de escritura en DB). Además (revisión post-Tarea 4, 2026-08-31) verifica que el
        `except` hace `session.rollback()` — sin él, el `commit()` fallido de
        `registrar_movimiento_ingreso` deja la sesión compartida en estado inválido
        (`PendingRollbackError` en cualquier uso posterior), lo que podía silenciar la respuesta de
        Slack por completo en vez de sólo perder el registro del movimiento."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = self._make_camara()
        camara_mock.estado = CamaraEstado.LIBRE
        contexto_libre = CamaraEstadoContexto(
            camara_id=camara_mock.id, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Ruta 8 Km 34 MALVINAS ARGENTINAS",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "ruta 8 km 34 malvinas argentinas"),
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
                side_effect=RuntimeError("DB caída"),
            ),
        ):
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(self._make_event(text=self.TEXTO_CON_INGRESO), client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("✅", texto_respuesta)
        # La sesión compartida debe quedar utilizable después del fallo: rollback explícito.
        session_mock.rollback.assert_called_once()

    def test_multibot_registra_movimiento_independiente_por_botella(self) -> None:
        """Multi-botella: cada búsqueda independiente del loop de `nombres_a_buscar` en
        `_handle_message` debe invocar su propio `registrar_movimiento_ingreso` (brief Tarea 4:
        'Multi-botella sale gratis' — el loop no se toca, cada llamada a
        `_construir_respuesta_camara` resuelve y escribe su propia fila)."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        cam1 = self._make_camara(id_=1, nombre="Cra Mitre 300")
        cam2 = self._make_camara(id_=2, nombre="Bot 2 Cra Mitre 300")
        contexto_libre = CamaraEstadoContexto(
            camara_id=1, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        texto = (
            "Cámara: Cra Mitre 300 Botella 1 y 2\n"
            "*Ingreso o Egreso*\nEgreso\n"
            "Persona que solicito La Autorizacion\n<@U0AUB6CRE4A|Rider Fernández>\n"
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Cra Mitre 300 Botella 1 y 2",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                side_effect=[
                    _resultado_camara(cam1, "cra mitre 300"),
                    _resultado_camara(cam2, "bot 2 cra mitre 300"),
                ],
            ) as mock_buscar,
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=contexto_libre,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_nombre_tecnico",
                return_value="Rider Fernández",
            ),
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
        ):
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(self._make_event(text=texto), client_mock)

        self.assertEqual(mock_buscar.call_count, 2)
        self.assertEqual(mock_registrar.call_count, 2)
        self.assertEqual(mock_registrar.call_args_list[0].kwargs["camara"], cam1)
        self.assertEqual(mock_registrar.call_args_list[1].kwargs["camara"], cam2)
        for c in mock_registrar.call_args_list:
            self.assertEqual(c.kwargs["tipo_movimiento"], "Egreso")
            self.assertEqual(c.kwargs["tecnico_nombre"], "Rider Fernández")
        client_mock.chat_postMessage.assert_called_once()

    def test_grupo_baneado_registra_intento_bloqueado_no_ingreso(self) -> None:
        """Bug real que motivó esta tarea: un Ingreso a un grupo BANEADO debía cancelarse y
        registrarse como Intento bloqueado, no como un Ingreso 'en curso' — antes se registraba
        siempre, sin condicionar al resultado de la evaluación de acceso."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = self._make_camara()
        camara_mock.estado = CamaraEstado.BANEADA
        contexto_baneado = CamaraEstadoContexto(
            camara_id=camara_mock.id, estado_actual=CamaraEstado.BANEADA, estado_sugerido=CamaraEstado.BANEADA,
            tiene_baneo_activo=True, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Ruta 8 Km 34 MALVINAS ARGENTINAS",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "ruta 8 km 34 malvinas argentinas"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=contexto_baneado,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                return_value="Corte de fibra",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_nombre_tecnico",
                return_value="Rider Fernández",
            ),
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
            patch("modules.slack_baneo_notifier.listener.registrar_intento_bloqueado") as mock_intento,
        ):
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(self._make_event(text=self.TEXTO_CON_INGRESO), client_mock)

        mock_intento.assert_called_once_with(
            session_mock, camara=camara_mock, botella=None, tecnico_nombre="Rider Fernández"
        )
        mock_registrar.assert_not_called()
        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn(":no_entry:", texto_respuesta)

    def test_egreso_de_grupo_baneado_no_se_bloquea(self) -> None:
        """Un Egreso nunca se bloquea, incluso si el grupo está BANEADO — sólo Ingreso se convierte
        en Intento."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = self._make_camara()
        camara_mock.estado = CamaraEstado.BANEADA
        contexto_baneado = CamaraEstadoContexto(
            camara_id=camara_mock.id, estado_actual=CamaraEstado.BANEADA, estado_sugerido=CamaraEstado.BANEADA,
            tiene_baneo_activo=True, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch(
                "modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                return_value="Ruta 8 Km 34 MALVINAS ARGENTINAS",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "ruta 8 km 34 malvinas argentinas"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=contexto_baneado,
            ),
            patch(
                "modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                return_value="Corte de fibra",
            ),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_nombre_tecnico",
                return_value="Rider Fernández",
            ),
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
            patch("modules.slack_baneo_notifier.listener.registrar_intento_bloqueado") as mock_intento,
        ):
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(self._make_event(text=self.TEXTO_CON_EGRESO), client_mock)

        mock_registrar.assert_called_once_with(
            session_mock, camara=camara_mock, botella=None, tipo_movimiento="Egreso",
            tecnico_nombre="Rider Fernández",
        )
        mock_intento.assert_not_called()


# ─── Tests de filtro de ambigüedad ─────────────────────────────────────────────


class TestFiltroAmbiguedad(unittest.TestCase):
    """Prueba el filtro de ambigüedad en buscar_camara y la respuesta del listener."""

    def _make_camara(self, id_: int, nombre: str) -> MagicMock:
        cam = MagicMock()
        cam.id = id_
        cam.nombre = nombre
        return cam

    def _make_listener(self) -> Any:
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event(self, text: str = "Cámara: test", channel: str = "C123") -> dict:
        return {"text": text, "channel": channel, "ts": "1234567890.000001"}

    # ── Tests sobre buscar_camara ──────────────────────────────────────────────

    def test_nombre_una_palabra_raises_ambiguous(self) -> None:
        """Un nombre con 1 token significativo y sin números lanza AmbiguousSearchError."""
        from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError, buscar_camara

        with self.assertRaises(AmbiguousSearchError) as ctx:
            buscar_camara("Centro", session=MagicMock())

        self.assertEqual(ctx.exception.cantidad, 0)
        self.assertEqual(ctx.exception.nombre_raw, "Centro")

    def test_nombre_vacio_raises_ambiguous(self) -> None:
        """Un nombre de dos chars (token < 3) lanza AmbiguousSearchError sin consultar DB."""
        from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError, buscar_camara

        with self.assertRaises(AmbiguousSearchError) as ctx:
            buscar_camara("VL", session=MagicMock())

        self.assertEqual(ctx.exception.cantidad, 0)

    def test_multiples_candidatos_raises_ambiguous(self) -> None:
        """Cuando todos los intentos devuelven >1 candidato, se lanza AmbiguousSearchError."""
        from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError, buscar_camara

        cam1 = self._make_camara(1, "Cra Vicente Lopez Norte 100")
        cam2 = self._make_camara(2, "Cra Vicente Lopez Sur 200")
        cam3 = self._make_camara(3, "Cra Vicente Lopez Este 300")

        with (
            patch("modules.slack_baneo_notifier.camara_search._buscar_ilike_lista",
                  return_value=[cam1, cam2, cam3]),
            patch("modules.slack_baneo_notifier.camara_search._buscar_tokens_lista",
                  return_value=[cam1, cam2, cam3]),
            self.assertRaises(AmbiguousSearchError) as ctx,
        ):
            buscar_camara("Vicente Lopez", session=MagicMock())

        self.assertEqual(ctx.exception.cantidad, 3)
        self.assertIn(ctx.exception.nombre_raw, "Vicente Lopez")
        self.assertEqual(len(ctx.exception.candidatos), 3)

    def test_multiples_candidatos_limitados_a_3(self) -> None:
        """candidatos en AmbiguousSearchError se limita a 3 nombres (cap de producto 2026-08-23,
        antes era 5 — ver core/services/cromo/camara_botella_busqueda.py)."""
        from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError, buscar_camara

        cams = [self._make_camara(i, f"Cra Test Zona {i}") for i in range(1, 8)]

        with (
            patch("modules.slack_baneo_notifier.camara_search._buscar_ilike_lista",
                  return_value=cams),
            patch("modules.slack_baneo_notifier.camara_search._buscar_tokens_lista",
                  return_value=cams),
            self.assertRaises(AmbiguousSearchError) as ctx,
        ):
            buscar_camara("Test Zona", session=MagicMock())

        self.assertLessEqual(len(ctx.exception.candidatos), 3)

    def test_un_candidato_no_raises(self) -> None:
        """Con exactamente 1 candidato después de los filtros, no se lanza la excepción."""
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        cam = self._make_camara(1, "Cra Mitre 440 CF")

        with (
            patch("modules.slack_baneo_notifier.camara_search._buscar_ilike_lista",
                  return_value=[cam]),
            patch("modules.slack_baneo_notifier.camara_search._buscar_tokens_lista",
                  return_value=[]),
        ):
            resultado, _ = buscar_camara("Cra Mitre 440", session=MagicMock())

        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.nombre, "Cra Mitre 440 CF")

    def test_nombre_con_numero_no_aplica_heuristica_corta(self) -> None:
        """Un token + número no dispara la heurística (el número es información suficiente)."""
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        # "Bot 2" → tokens_sig = ["bot"] (1 token), pero numeros_requeridos = {"2"}
        # → la pre-heurística NO debe dispararse
        with (
            patch("modules.slack_baneo_notifier.camara_search._buscar_ilike_lista",
                  return_value=[]),
            patch("modules.slack_baneo_notifier.camara_search._buscar_tokens_lista",
                  return_value=[]),
        ):
            resultado, _ = buscar_camara("Bot 2", session=MagicMock())

        self.assertIsNone(resultado)

    # ── Tests del listener ante ambigüedad ────────────────────────────────────

    def test_listener_responde_warning_nombre_generico(self) -> None:
        """Cuando buscar_camara lanza AmbiguousSearchError(cantidad=0), listener responde warning."""
        from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError

        listener = self._make_listener()
        client_mock = MagicMock()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                  return_value="Norte"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                  side_effect=AmbiguousSearchError("Norte", 0, [])),
        ):
            listener._handle_message(self._make_event(text="Norte"), client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn(":warning:", texto)
        self.assertIn("Norte", texto)
        self.assertIn("genérico", texto)

    def test_listener_responde_warning_multiples_candidatos(self) -> None:
        """Cuando buscar_camara lanza AmbiguousSearchError(cantidad>0), listener responde warning."""
        from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError

        listener = self._make_listener()
        client_mock = MagicMock()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                  return_value="Vicente Lopez"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                  side_effect=AmbiguousSearchError(
                      "Vicente Lopez", 8,
                      ["Cra A Vicente Lopez", "Cra B Vicente Lopez"]
                  )),
        ):
            listener._handle_message(
                self._make_event(text="Cámara: Vicente Lopez"),
                client_mock,
            )

        client_mock.chat_postMessage.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn(":warning:", texto)
        self.assertIn("Vicente Lopez", texto)
        self.assertIn("8", texto)

    def test_listener_responde_candidatos_como_vinetas_y_puede_continuar(self) -> None:
        """Tarea 2 (2026-08-23): la rama de múltiples candidatos debe listar `exc.candidatos` como
        viñetas de texto plano y agregar la frase 'Podés continuar con el ingreso con normalidad'
        (antes sólo la rama de "no match" lo decía explícitamente)."""
        from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError

        listener = self._make_listener()
        client_mock = MagicMock()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                  return_value="Vicente Lopez"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                  side_effect=AmbiguousSearchError(
                      "Vicente Lopez", 2,
                      ["Cra A Vicente Lopez", "Cra B Vicente Lopez"]
                  )),
        ):
            listener._handle_message(
                self._make_event(text="Cámara: Vicente Lopez"),
                client_mock,
            )

        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("• Cra A Vicente Lopez", texto)
        self.assertIn("• Cra B Vicente Lopez", texto)
        self.assertIn("Podés continuar con el ingreso con normalidad", texto)

    def test_listener_nombre_generico_tambien_dice_puede_continuar(self) -> None:
        """La rama cantidad==0 (nombre demasiado genérico) también debe agregar la frase 'Podés
        continuar' (Tarea 2, 2026-08-23) — antes sólo lo decía la rama de "no match" completo."""
        from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError

        listener = self._make_listener()
        client_mock = MagicMock()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                  return_value="Norte"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                  side_effect=AmbiguousSearchError("Norte", 0, [])),
        ):
            listener._handle_message(self._make_event(text="Norte"), client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("Podés continuar con el ingreso con normalidad", texto)

    def test_listener_no_autoregistra_en_ambiguedad(self) -> None:
        """Con AmbiguousSearchError, el listener NO escribe en DB (no auto-registro)."""
        from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal",
                  return_value=session_mock),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                  return_value="Vicente Lopez"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                  side_effect=AmbiguousSearchError("Vicente Lopez", 5, [])),
        ):
            listener._handle_message(
                self._make_event(text="Cámara: Vicente Lopez"),
                client_mock,
            )

        # No debe haber escritura (add/commit) en la sesión
        session_mock.add.assert_not_called()
        session_mock.commit.assert_not_called()

    def test_multibot_no_se_confunde_con_ambiguedad(self) -> None:
        """'Botella 1 y 2' es multi-bot, no ambigüedad — se procesan como dos cámaras."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        cam = MagicMock()
        cam.id = 1
        cam.nombre = "Cra Mitre 300"
        cam.estado = CamaraEstado.LIBRE
        contexto_libre = CamaraEstadoContexto(
            camara_id=1, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                  return_value="Cra Mitre 300 Botella 1 y 2"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                  return_value=_resultado_camara(cam, "cra mitre 300")) as mock_buscar,
            patch("modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                  return_value=contexto_libre),
            patch("modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                  return_value=None),
        ):
            listener._handle_message(
                self._make_event(text="Cra Mitre 300 Botella 1 y 2"),
                client_mock,
            )

        # Se deben hacer 2 búsquedas (una por botella) — no warning
        self.assertEqual(mock_buscar.call_count, 2)
        client_mock.chat_postMessage.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertNotIn(":warning:", texto)


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

    def test_registra_ingreso_sin_match_en_vez_de_autoregistrar_camara(self) -> None:
        """Cuando buscar_camara retorna None, el listener registra un `IngresoSinMatch` (para
        revisión manual/mejora del regex) — ya NO crea una `Camara` PENDIENTE_REVISION (2026-08-11,
        Cromo es la fuente de verdad, ese flujo quedó retirado)."""
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
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo", return_value=_resultado_camara(None, "cra inexistente xyz 9999")),
        ):
            # El listener usa session = SessionLocal() directamente (no context manager)
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(event, client_mock)

        # Se registra el caso (IngresoSinMatch), nunca una Camara.
        session_mock.add.assert_called_once()
        registrado = session_mock.add.call_args[0][0]
        self.assertEqual(registrado.origen, "slack")
        self.assertEqual(registrado.texto_original, "CRA Inexistente XYZ 9999")
        self.assertEqual(registrado.contexto, "C123")
        # thread_ts (Tarea 2, 2026-08-23) — acá el evento no trae "thread_ts" propio, por lo que
        # cae al "ts" del mensaje raíz (mismo criterio que ya usaba _handle_message para
        # chat_postMessage).
        self.assertEqual(registrado.thread_ts, "1234567890.000001")
        session_mock.commit.assert_called_once()

        # El técnico nunca ve un rechazo — puede continuar con el ingreso igual.
        client_mock.chat_postMessage.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("Podés continuar con el ingreso", texto)


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

    def test_punto_tras_numero_se_elimina(self) -> None:
        """Regresión: '301.' debe quedar '301' — el punto post-dígito no es decimal."""
        resultado = self.detectar("Bartolomé Mitre 301. Botella 1 y 2. CF")
        assert resultado is not None
        for s in resultado:
            self.assertNotIn("301.", s, f"Punto tras número en: {s!r}")
        self.assertIn("301", resultado[0])
        self.assertIn("301", resultado[1])

    def test_caso_real_campo_camara_con_coma(self) -> None:
        """Regresión: 'Cámara, ... Botella 1 y 2' — la palabra 'Cámara' no contamina la base."""
        resultado = self.detectar("Cámara, Bartolomé Mitre 301. Botella 1 y 2. CF")
        # detectar_multi_bot actúa sobre el nombre_raw ya extraído; si llega con
        # "Cámara," el sinonimo camara→cra lo maneja, pero la base no debe incluir
        # "Cámara" sin transformar.
        self.assertIsNotNone(resultado)
        assert resultado is not None
        for s in resultado:
            self.assertNotIn("301.", s, f"Punto tras número en: {s!r}")


# ─── Tests del filtro de ruido operativo ───────────────────────────────────────


class TestLimpiarRuidoOperativo(unittest.TestCase):
    """Prueba limpiar_ruido_operativo() — descarte de sufijos operativos."""

    def setUp(self) -> None:
        from modules.slack_baneo_notifier.camara_search import limpiar_ruido_operativo
        self.limpiar = limpiar_ruido_operativo

    def test_cuadrilla_con_guion(self) -> None:
        """Caso real: '- CUADRILLA DE HIDROCONS' se descarta."""
        self.assertEqual(
            self.limpiar("Cra Quesada 2396 CF - CUADRILLA DE HIDROCONS"),
            "Cra Quesada 2396 CF",
        )

    def test_movil_con_guion(self) -> None:
        """'- Móvil 4' se descarta."""
        self.assertEqual(self.limpiar("Camara 1 - Móvil 4"), "Camara 1")

    def test_movil_sin_acento(self) -> None:
        """'- Movil 4' (sin tilde) también se descarta."""
        self.assertEqual(self.limpiar("Cra Mitre 440 - Movil 7"), "Cra Mitre 440")

    def test_contratista_con_barra(self) -> None:
        """Separador '/' también se reconoce."""
        self.assertEqual(self.limpiar("Cra Mitre 440 / Contratista XYZ"), "Cra Mitre 440")

    def test_equipo_con_pipe(self) -> None:
        """Separador '|' también se reconoce."""
        self.assertEqual(self.limpiar("Cra Quesada 2396 CF | EQUIPO A"), "Cra Quesada 2396 CF")

    def test_localidad_con_guion_se_preserva(self) -> None:
        """Regresión: 'Poste Lavalle - Campana' NO se corta — Campana no es stopword."""
        self.assertEqual(
            self.limpiar("Poste Lavalle - Campana"),
            "Poste Lavalle - Campana",
        )

    def test_sin_ruido_retorna_intacto(self) -> None:
        """Sin separador ni ruido, el string queda intacto."""
        self.assertEqual(self.limpiar("Cra Mitre 440"), "Cra Mitre 440")

    def test_tecnico_con_guion(self) -> None:
        """Stopword 'Técnico' también se descarta."""
        self.assertEqual(self.limpiar("Cam Zona Norte - Técnico Juan"), "Cam Zona Norte")

    def test_texto_vacio(self) -> None:
        """String vacío retorna vacío."""
        self.assertEqual(self.limpiar(""), "")


# ─── Tests de baneo manual sin incidente de red ────────────────────────────────


class TestBaneoManualSinIncidente(unittest.TestCase):
    """Prueba la jerarquía de validación cuando el GRUPO (cámara + botellas hermanas) tiene un
    miembro BANEADO manualmente (sin IncidenteBaneo activo) — Tarea 5 (2026-09-04): el chequeo ahora
    reusa `get_camara_estado_contexto()` en vez de mirar sólo el `estado`/incidentes de la fila
    puntual resuelta, así que estos tests mockean `get_camara_estado_contexto` (no ya
    `_obtener_incidentes_activos_camara`, retirada — ver `camara_estado_service.CamaraEstadoContexto`
    para el shape exacto)."""

    def _make_listener(self) -> Any:
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event(self, text: str = "Cámara: Cam Test") -> dict:
        return {"text": text, "channel": "C123", "ts": "1234567890.000001"}

    def _make_camara(self, id_: int, nombre: str, estado: Any) -> Any:
        camara = MagicMock()
        camara.id = id_
        camara.nombre = nombre
        camara.estado = estado
        camara.camara_padre = None
        camara.botellas = []
        return camara

    def _contexto(self, camara_id: int, *, incidentes_activos=None) -> Any:
        from core.services.camara_estado_service import CamaraEstadoContexto
        from db.models.infra import CamaraEstado

        incidentes_activos = incidentes_activos or []
        return CamaraEstadoContexto(
            camara_id=camara_id,
            estado_actual=CamaraEstado.BANEADA,
            estado_sugerido=CamaraEstado.BANEADA,
            tiene_baneo_activo=True,
            tiene_ingreso_activo=False,
            inconsistente=False,
            incidentes_activos=incidentes_activos,
            ticket_baneo=None,
        )

    def test_baneada_manual_sin_incidente_bloquea(self) -> None:
        """Grupo BANEADO sin incidente activo → :no_entry: con motivo de auditoría."""
        from db.models.infra import CamaraEstado

        camara_mock = self._make_camara(10, "Cam Baneada Manual", CamaraEstado.BANEADA)
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Baneada Manual")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Baneada Manual"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "baneada manual"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=self._contexto(10),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                return_value="Fibra cortada en nodo norte",
            ),
        ):
            listener._handle_message(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn(":no_entry:", texto)
        self.assertIn("Cam Baneada Manual", texto)
        self.assertIn("Fibra cortada en nodo norte", texto)
        self.assertNotIn("ATENCIÓN", texto)

    def test_baneada_manual_sin_motivo_auditoria(self) -> None:
        """Grupo BANEADO, `obtener_ultimo_motivo_baneo_manual` retorna None → fallback 'sin motivo
        registrado'."""
        from db.models.infra import CamaraEstado

        camara_mock = self._make_camara(11, "Cam Baneada Sin Audit", CamaraEstado.BANEADA)
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Baneada Sin Audit")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Baneada Sin Audit"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "baneada sin audit"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=self._contexto(11),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                return_value=None,
            ),
        ):
            listener._handle_message(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn(":no_entry:", texto)
        self.assertIn("sin motivo registrado", texto)

    def test_jerarquia_incidente_tiene_prioridad(self) -> None:
        """Grupo BANEADO con IncidenteBaneo activo → 🚨 ATENCIÓN (nivel 1 gana sobre manual)."""
        from core.services.camara_estado_service import IncidenteActivoResumen
        from db.models.infra import CamaraEstado

        camara_mock = self._make_camara(12, "Cam Con Incidente", CamaraEstado.BANEADA)
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Con Incidente")
        incidente = IncidenteActivoResumen(
            id=55, ticket_asociado="TKT-555", servicio_protegido_id="SVC-01",
            ruta_protegida_id=None, fecha_inicio=None, motivo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Con Incidente"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "con incidente"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=self._contexto(12, incidentes_activos=[incidente]),
            ),
            patch("modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual") as mock_motivo,
        ):
            listener._handle_message(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("ATENCIÓN", texto)
        self.assertIn("#55", texto)
        # La función de auditoría no debe haberse llamado cuando hay incidente activo
        mock_motivo.assert_not_called()

    def test_baneo_de_botella_hermana_bloquea_ingreso_a_la_camara_raiz(self) -> None:
        """Bug real que motivó esta tarea: pedir ingreso a la cámara RAÍZ (estado propio LIBRE)
        mientras una Botella hermana está BANEADA debe bloquear igual — antes el listener sólo miraba
        el `estado` de la fila puntual resuelta, nunca el grupo. Caso degenerado (grupo de 1 solo
        miembro, el propio `camara_mock`) para asegurar que el `next(..., camara)` con fallback no
        rompe cuando no hay hermanas — el caso MULTI-miembro real está cubierto por
        `test_baneo_de_botella_hermana_multi_miembro_identifica_a_la_hermana`, abajo."""
        from db.models.infra import CamaraEstado

        camara_mock = self._make_camara(13, "Cam Raiz Libre", CamaraEstado.LIBRE)
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Raiz Libre")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Raiz Libre"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "raiz libre"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                # tiene_baneo_activo=True aunque la propia fila (`estado_actual`) siga LIBRE — lo
                # aporta una Botella hermana, ya contemplado por Task 3.
                return_value=self._contexto(13),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                return_value="Botella hermana baneada",
            ),
        ):
            listener._handle_message(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn(":no_entry:", texto)

    def test_baneo_de_botella_hermana_multi_miembro_identifica_a_la_hermana(self) -> None:
        """Cobertura real del bug (revisión post-Tarea 5, 2026-09-04): grupo de 2+ miembros donde el
        miembro BANEADO no es la cámara raíz consultada, sino una Botella hermana con id/nombre
        propios en `camara.botellas`. `_evaluar_estado_acceso_camara` debe identificar a la HERMANA
        (no caer al fallback `camara` del `next(..., camara)`) — tanto en el texto de respuesta
        (`detalle_miembro`, "del mismo grupo") como en el `id` pasado a
        `obtener_ultimo_motivo_baneo_manual`. El test anterior (grupo de 1 solo miembro,
        `camara.botellas=[]` vía `_make_camara`) no puede distinguir esto: el `next()` sólo tiene el
        fallback `camara` para elegir, así que `miembro_baneado is camara` siempre, incluso si el
        código tuviera el bug de nunca resolver la hermana real."""
        from db.models.infra import CamaraEstado

        camara_mock = self._make_camara(13, "Cam Raiz Libre", CamaraEstado.LIBRE)
        botella_hermana_mock = self._make_camara(99, "Bot 2 Cam Raiz Libre", CamaraEstado.BANEADA)
        camara_mock.botellas = [botella_hermana_mock]
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Raiz Libre")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_cls,
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Raiz Libre"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "raiz libre"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                # tiene_baneo_activo=True aunque la propia fila (`estado_actual`) siga LIBRE — lo
                # aporta la Botella hermana `botella_hermana_mock`, ya contemplado por Task 3. El
                # contexto en sí es opaco a QUIÉN del grupo está baneado — eso lo resuelve
                # `_evaluar_estado_acceso_camara` iterando `miembros_del_grupo(camara)`.
                return_value=self._contexto(13),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                return_value="Botella hermana baneada",
            ) as mock_motivo,
        ):
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn(":no_entry:", texto)
        self.assertIn("Cam Raiz Libre", texto)
        # El miembro efectivamente baneado es la Botella hermana (id=99, nombre propio) — no la
        # cámara raíz consultada (id=13) ni el fallback genérico del `next(..., camara)`.
        self.assertIn("Bot 2 Cam Raiz Libre", texto)
        self.assertIn("del mismo grupo", texto)
        mock_motivo.assert_called_once_with(session_mock, 99)

    def test_libre_no_afectado(self) -> None:
        """Grupo LIBRE (sin baneo) → ✅ OK — la nueva rama no interfiere. (regresión)"""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        camara_mock = self._make_camara(14, "Cam Libre", CamaraEstado.LIBRE)
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Libre")
        contexto_libre = CamaraEstadoContexto(
            camara_id=14, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Libre"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "libre"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                return_value=contexto_libre,
            ),
        ):
            listener._handle_message(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("✅", texto)
        self.assertNotIn(":no_entry:", texto)
        self.assertNotIn("ATENCIÓN", texto)


# ─── Tests de exclusión de Nodos ───────────────────────────────────────────────


class TestExclusionNodo(unittest.TestCase):
    """Prueba que el listener ignora mensajes cuyo nombre extraído corresponde a un Nodo."""

    def _make_listener(self) -> Any:
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event(self, text: str = "Nodo Test", channel: str = "C123") -> dict:
        return {"text": text, "channel": channel, "ts": "1234567890.000001"}

    def test_ignora_nodo_simple(self) -> None:
        """Nombre extraído 'Nodo Vte Lopez' → el bot no responde ni consulta DB."""
        listener = self._make_listener()
        client_mock = MagicMock()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Nodo Vte Lopez"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo") as mock_buscar,
        ):
            listener._handle_message(self._make_event(text="Nodo Vte Lopez"), client_mock)

        client_mock.chat_postMessage.assert_not_called()
        mock_buscar.assert_not_called()

    def test_ignora_nodo_con_descripcion_operativa(self) -> None:
        """'Nodo Vte Lopez - cuadrilla de empalmes' → ignorado sin acceso a DB."""
        listener = self._make_listener()
        client_mock = MagicMock()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                  return_value="Nodo Vte Lopez - cuadrilla de empalmes"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo") as mock_buscar,
        ):
            listener._handle_message(
                self._make_event(text="Buenas tardes Nodo Vte Lopez - cuadrilla de empalmes"),
                client_mock,
            )

        client_mock.chat_postMessage.assert_not_called()
        mock_buscar.assert_not_called()

    def test_ignora_nodos_plural(self) -> None:
        """'nodos zona sur' (plural, minúsculas) → ignorado (case-insensitive)."""
        listener = self._make_listener()
        client_mock = MagicMock()

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                  return_value="nodos zona sur"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo") as mock_buscar,
        ):
            listener._handle_message(
                self._make_event(text="Ingreso a nodos zona sur"),
                client_mock,
            )

        client_mock.chat_postMessage.assert_not_called()
        mock_buscar.assert_not_called()

    def test_camara_no_afectada_por_filtro_nodo(self) -> None:
        """Nombre extraído de cámara normal → sigue procesándose (regresión)."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = MagicMock()
        camara_mock.id = 1
        camara_mock.nombre = "Cam Mitre 440"
        camara_mock.estado = CamaraEstado.LIBRE
        contexto_libre = CamaraEstadoContexto(
            camara_id=1, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                  return_value="Cam Mitre 440"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                  return_value=_resultado_camara(camara_mock, "cam mitre 440")) as mock_buscar,
            patch("modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                  return_value=contexto_libre),
            patch("modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                  return_value=None),
        ):
            listener._handle_message(
                self._make_event(text="Cámara: Cam Mitre 440"),
                client_mock,
            )

        mock_buscar.assert_called_once()
        client_mock.chat_postMessage.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("✅", texto)

    def test_workflow_con_label_nodo_camara_no_ignorado(self) -> None:
        """Workflow con ETIQUETA 'Nodo/Camara/botella' y VALOR de cámara → no ignorado."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = MagicMock()
        camara_mock.id = 2
        camara_mock.nombre = "Bot. estacion Alem linea B CF"
        camara_mock.estado = CamaraEstado.LIBRE
        contexto_libre = CamaraEstadoContexto(
            camara_id=2, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            # extraer_nombre_camara extrae el VALOR (no la etiqueta del Workflow)
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                  return_value="Bot. estacion Alem linea B CF"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                  return_value=_resultado_camara(camara_mock, "bot estacion alem linea b cf")) as mock_buscar,
            patch("modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                  return_value=contexto_libre),
            patch("modules.slack_baneo_notifier.listener.obtener_ultimo_motivo_baneo_manual",
                  return_value=None),
        ):
            listener._handle_message(
                self._make_event(
                    text="*Nombre: Nodo/Camara/botella*\nBot. estacion Alem linea B CF\n"
                ),
                client_mock,
            )

        mock_buscar.assert_called_once()
        client_mock.chat_postMessage.assert_called_once()


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

        # buscar_camara_o_botella_cromo: primera llamada → cam1, segunda → cam2
        buscar_side = [
            _resultado_camara(cam1, "cra bartolome mitre 301"),
            _resultado_camara(cam2, "bot 2 cra bartolome mitre 301"),
        ]

        with patch(
            "modules.slack_baneo_notifier.listener.IngresoListener._get_config",
            return_value=config_mock,
        ):
            with patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
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
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(cam, "cra mitre 440"),
            ) as mock_buscar:
                with patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_sess:
                    mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock())
                    mock_sess.return_value.__exit__ = MagicMock(return_value=False)
                    listener._handle_message(
                        self._evento("Cámara: Cra Mitre 440"),
                        client_mock,
                    )

        self.assertEqual(mock_buscar.call_count, 1)


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


# ─── Tests del mecanismo de "hilo esperando ID de empalme" ─────────────────────


class TestSeguimientoEmpalme(unittest.TestCase):
    """Prueba `_procesar_seguimiento_empalme` / la integración en `_handle_message` (Tarea 2,
    2026-08-23): un técnico responde en el hilo de un caso `IngresoSinMatch` pendiente con el ID de
    empalme más cercano."""

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
            tiene_baneo_activo=False, tiene_ingreso_activo=False, inconsistente=False,
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
        """Texto que no matchea el regex de seguimiento: ni siquiera se consulta si hay un caso
        pendiente — sigue el flujo normal sin más (puede ser cualquier otro mensaje del canal)."""
        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()

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

        session_mock.query.assert_not_called()
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


if __name__ == "__main__":
    unittest.main()
