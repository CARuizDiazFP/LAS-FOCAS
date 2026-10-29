# Nombre de archivo: test_slack_ingreso_filtros.py
# Ubicación de archivo: tests/test_slack_ingreso_filtros.py
# Descripción: Tests del listener de ingresos de Slack: ambigüedad, limpieza, sinónimos, filtros de número/bot, multi-bot y ruido operativo

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

os.environ.setdefault("TESTING", "true")

from tests.soporte_slack_ingreso import _resultado_camara


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
            patch("core.services.camara_busqueda_nombre._buscar_ilike_lista",
                  return_value=[cam1, cam2, cam3]),
            patch("core.services.camara_busqueda_nombre._buscar_tokens_lista",
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
            patch("core.services.camara_busqueda_nombre._buscar_ilike_lista",
                  return_value=cams),
            patch("core.services.camara_busqueda_nombre._buscar_tokens_lista",
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
            patch("core.services.camara_busqueda_nombre._buscar_ilike_lista",
                  return_value=[cam]),
            patch("core.services.camara_busqueda_nombre._buscar_tokens_lista",
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
            patch("core.services.camara_busqueda_nombre._buscar_ilike_lista",
                  return_value=[]),
            patch("core.services.camara_busqueda_nombre._buscar_tokens_lista",
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
        self.assertIn("Escribí la cámara correcta en este hilo (o el operador puede responder con el Fontaine ID)", texto)

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
        self.assertIn("Escribí la cámara correcta en este hilo (o el operador puede responder con el Fontaine ID)", texto)

    def test_listener_registra_ingreso_sin_match_en_ambiguedad(self) -> None:
        """Regresión (2026-09-07, revierte el comportamiento anterior deliberadamente — ver
        docs/decisiones.md): con AmbiguousSearchError, el listener AHORA sí crea un
        `IngresoSinMatch` (igual que el caso "sin match"), para que el caso quede revalidable con
        "Revalidar ingreso" en el mismo hilo. Antes no persistía nada en absoluto."""
        from modules.slack_baneo_notifier.camara_search import AmbiguousSearchError

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        texto_evento = "Cámara: Vicente Lopez"

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
                self._make_event(text=texto_evento),
                client_mock,
            )

        session_mock.add.assert_called_once()
        caso = session_mock.add.call_args[0][0]
        self.assertEqual(caso.texto_original, "Vicente Lopez")
        self.assertEqual(caso.texto_mensaje, texto_evento)
        self.assertEqual(caso.origen, "slack")
        session_mock.commit.assert_called_once()

        texto_respuesta = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("Revalidar ingreso", texto_respuesta)

    def test_listener_numero_no_coincide_sugiere_y_registra_sin_match(self) -> None:
        """2026-10-23: número que no coincide → "No encontré X con ese número. ¿Quisiste decir…?",
        pide reescribir la cámara en el hilo y registra el `IngresoSinMatch` como un ambiguo. Nunca
        registra un movimiento en una de las sugeridas."""
        from modules.slack_baneo_notifier.camara_search import NumeroNoCoincideError

        listener = self._make_listener()
        client_mock = MagicMock()
        session_mock = MagicMock()
        texto_evento = "Cámara: Cra Mitre 404"

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal", return_value=session_mock),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara",
                  return_value="Cra Mitre 404"),
            patch("modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                  side_effect=NumeroNoCoincideError(
                      "Cra Mitre 404", 2, ["Cra Mitre 440", "Cra Mitre 399"])),
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
        ):
            listener._handle_message(self._make_event(text=texto_evento), client_mock)

        mock_registrar.assert_not_called()
        session_mock.add.assert_called_once()
        caso = session_mock.add.call_args[0][0]
        self.assertEqual(caso.texto_original, "Cra Mitre 404")
        self.assertEqual(caso.texto_mensaje, texto_evento)
        self.assertEqual(caso.thread_ts, "1234567890.000001")
        self.assertEqual(caso.origen, "slack")
        session_mock.commit.assert_called_once()

        client_mock.chat_postMessage.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("No encontré *Cra Mitre 404* con ese número", texto)
        self.assertIn("¿Quisiste decir", texto)
        self.assertIn("• Cra Mitre 440", texto)
        self.assertIn("• Cra Mitre 399", texto)
        self.assertIn("Escribí la cámara correcta en este hilo (o el operador puede responder con el Fontaine ID)", texto)
        self.assertNotIn("ambigua", texto)

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
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False, inconsistente=False,
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

        with patch("core.services.camara_busqueda_nombre._buscar_ilike_lista", return_value=[camara_mock]):
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
            "core.services.camara_busqueda_nombre._buscar_ilike_lista",
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
            "core.services.camara_busqueda_nombre._buscar_ilike_lista",
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
            "core.services.camara_busqueda_nombre._buscar_ilike_lista",
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
            "core.services.camara_busqueda_nombre._buscar_ilike_lista",
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
            "core.services.camara_busqueda_nombre._buscar_ilike_lista",
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
            patch("core.services.camara_busqueda_nombre._buscar_ilike_lista", side_effect=ilike_lista_side_effect),
            patch("core.services.camara_busqueda_nombre._buscar_tokens_lista", return_value=[]),
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
