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
   en tests/soporte_slack_ingreso.py); los que ejercitan camara_search.buscar_camara() en forma
   aislada no cambian.
 - exclusión de Nodos y handler multi-bot.

El resto del listener está partido por tema (2026-10-29): test_slack_ingreso_registro.py (Ingreso/Egreso
y baneo manual), test_slack_ingreso_filtros.py (ambigüedad, limpieza, filtros y multi-bot),
test_slack_ingreso_seguimiento.py (empalme, ID de Fontaine, Revalidar ingreso) y
test_slack_ingreso_correccion.py (Forzar ingreso/egreso, fecha pendiente, orden de handlers).
"""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

os.environ.setdefault("TESTING", "true")

from tests.soporte_slack_ingreso import _resultado_camara


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

    def test_workflow_valor_con_salto_de_linea_erroneo_se_une(self) -> None:
        """Regresión (prod, ticket MKT 122293, 2026-09-07): el técnico pegó el nombre con un
        salto de línea accidental en el medio ('e:' en una línea, la dirección real en la
        siguiente). El salto de línea es un error de copiado del técnico, no un separador de
        campo del Workflow — debe unirse en una sola línea en vez de truncar en el primer '\\n'
        (lo que antes producía sólo 'e:', disparando el falso 'nombre demasiado genérico')."""
        texto = (
            "*Nombre: Nodo/Camara/botella*\n"
            "e:\n"
            "Cra Curupayti 2951 CF - CURUPAYTI 2964 - Capital Federal - Capital Federal\n"
            "*Ingreso o Egreso*\nEgreso\n"
        )
        result = self.extraer(texto)
        # Desde 2026-09-28 además se descarta la primera línea residual ("e:"/"me:"): antes quedaba
        # pegada adelante del nombre y el caso real "me: Cra Acevedo 396 CF" no matcheaba.
        self.assertEqual(
            result,
            "Cra Curupayti 2951 CF - CURUPAYTI 2964 - Capital Federal - Capital Federal",
        )


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

    @patch("core.services.camara_busqueda_nombre.func")
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

    @patch("core.services.camara_busqueda_nombre.func")
    def test_no_encontrada_retorna_none(self, mock_func: MagicMock) -> None:
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        session = MagicMock()

        with (
            patch("core.services.camara_busqueda_nombre._buscar_ilike_lista", return_value=[]),
            patch("core.services.camara_busqueda_nombre._buscar_tokens_lista", return_value=[]),
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

    def test_prefijo_antes_del_guion_se_intenta_primero(self) -> None:
        """Regresión (prod, ticket MKT 122293, 2026-09-07): el técnico pegó el título completo
        que muestra Cromo para la Botella ('Cra Curupayti 2951 CF - CURUPAYTI 2964 - Capital
        Federal - Capital Federal' — Nombre + Calle/Altura/Localidad/Provincia concatenados).
        buscar_camara() debe resolver con sólo el prefijo antes del primer guión, sin que el
        resto (atributos de Cromo, con OTRO número — 2964 — que rompería el filtro de números
        si se usara el string completo) contamine la búsqueda."""
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        camara_mock = self._make_camara(42, "Cra Curupayti 2951 CF")

        def ilike_lista_side_effect(patron: str, session: Any) -> Any:
            # Sólo matchea el prefijo limpio; si algo del resto de Cromo (2964, capital
            # federal) llega a este patrón, el fix no está funcionando.
            if "2964" in patron or "capital" in patron:
                return []
            return [camara_mock]

        with (
            patch(
                "core.services.camara_busqueda_nombre._buscar_ilike_lista",
                side_effect=ilike_lista_side_effect,
            ),
            patch("core.services.camara_busqueda_nombre._buscar_tokens_lista", return_value=[]),
        ):
            camara, nombre_norm = buscar_camara(
                "Cra Curupayti 2951 CF - CURUPAYTI 2964 - Capital Federal - Capital Federal",
                session=MagicMock(),
            )

        self.assertIsNotNone(camara)
        self.assertEqual(camara.nombre, "Cra Curupayti 2951 CF")

    def test_end_to_end_mensaje_real_prod_ticket_122293(self) -> None:
        """End-to-end (extraer_nombre_camara + buscar_camara) con el mensaje real de producción
        (ticket MKT 122293, 2026-09-07): salto de línea accidental ('e:' + Enter) seguido del
        título completo que muestra Cromo para la Botella. Ambos fixes encadenados deben resolver
        a la cámara real."""
        from modules.slack_baneo_notifier.camara_search import buscar_camara, extraer_nombre_camara

        texto_mensaje = (
            "*Nombre: Nodo/Camara/botella*\n"
            "e:\n"
            "Cra Curupayti 2951 CF - CURUPAYTI 2964 - Capital Federal - Capital Federal\n"
            "*Ingreso o Egreso*\nEgreso\n"
        )
        nombre_extraido = extraer_nombre_camara(texto_mensaje)

        camara_mock = self._make_camara(44, "Cra Curupayti 2951 CF")

        def ilike_lista_side_effect(patron: str, session: Any) -> Any:
            if "2964" in patron or "capital" in patron:
                return []
            return [camara_mock]

        with (
            patch(
                "core.services.camara_busqueda_nombre._buscar_ilike_lista",
                side_effect=ilike_lista_side_effect,
            ),
            patch("core.services.camara_busqueda_nombre._buscar_tokens_lista", return_value=[]),
        ):
            camara, nombre_norm = buscar_camara(nombre_extraido, session=MagicMock())

        self.assertIsNotNone(camara)
        self.assertEqual(camara.nombre, "Cra Curupayti 2951 CF")

    def test_prefijo_sin_match_cae_al_nombre_completo(self) -> None:
        """Si el prefijo antes del guión no alcanza para encontrar nada, se reintenta con el
        string completo — preserva 'Poste Lavalle - Campana', donde la localidad después del
        guión es parte legítima y necesaria del nombre real (no un atributo de Cromo pegado de
        más)."""
        from modules.slack_baneo_notifier.camara_search import buscar_camara

        camara_mock = self._make_camara(43, "Poste Lavalle - Campana")

        def ilike_lista_side_effect(patron: str, session: Any) -> Any:
            # El prefijo solo ("poste lavalle") no encuentra nada; sólo el string completo
            # (con "campana") matchea.
            if "campana" in patron:
                return [camara_mock]
            return []

        with (
            patch(
                "core.services.camara_busqueda_nombre._buscar_ilike_lista",
                side_effect=ilike_lista_side_effect,
            ),
            patch("core.services.camara_busqueda_nombre._buscar_tokens_lista", return_value=[]),
        ):
            camara, nombre_norm = buscar_camara("Poste Lavalle - Campana", session=MagicMock())

        self.assertIsNotNone(camara)
        self.assertEqual(camara.nombre, "Poste Lavalle - Campana")

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
            patch("core.services.camara_busqueda_nombre._buscar_ilike_lista", side_effect=ilike_lista_side_effect),
            patch("core.services.camara_busqueda_nombre._buscar_tokens_lista", return_value=[]),
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
        # 2026-10-23: "informa y solicita escribir la cámara dentro del mismo hilo".
        self.assertIn(
            "Escribí la cámara correcta en este hilo (o el operador puede responder con el Fontaine ID).",
            texto_respuesta,
        )

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
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False, inconsistente=False,
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
            tiene_baneo_activo=True, tiene_incidente_activo=True, tiene_ingreso_activo=False, inconsistente=False,
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
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False, inconsistente=False,
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
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False, inconsistente=False,
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

if __name__ == "__main__":
    unittest.main()
