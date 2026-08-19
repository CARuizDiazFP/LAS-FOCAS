# Nombre de archivo: test_slack_cable_info.py
# Ubicación de archivo: tests/test_slack_cable_info.py
# Descripción: Tests de los comandos "Info cable"/"Verificar cable" (con y sin buffer) — parser, lookup y handlers app_mention

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("TESTING", "true")

from core.services.cromo.verificador import ResultadoTubo, ServicioEncontrado
from modules.slack_baneo_notifier.cable_info import (
    buscar_cable_por_nombre,
    construir_respuesta_ambiguo,
    construir_respuesta_buffer_no_encontrado,
    construir_respuesta_info_buffer,
    construir_respuesta_info_cable,
    construir_respuesta_no_encontrado,
    construir_respuesta_verificar_buffer,
    contar_buffers_cable,
    extraer_comando_cable_buffer,
    extraer_comando_info_cable,
    resolver_tubo_por_numero,
)


class TestExtraerComandoInfoCable(unittest.TestCase):
    def test_matchea_comando_simple(self) -> None:
        self.assertEqual(extraer_comando_info_cable("Info cable F-VFL-IND"), "F-VFL-IND")

    def test_case_insensitive(self) -> None:
        self.assertEqual(extraer_comando_info_cable("info CABLE f-vfl-ind"), "f-vfl-ind")

    def test_recorta_puntuacion_final(self) -> None:
        self.assertEqual(extraer_comando_info_cable("Info cable F-VFL-IND."), "F-VFL-IND")

    def test_normaliza_espacios_multiples(self) -> None:
        self.assertEqual(extraer_comando_info_cable("Info   cable   F-VFL-IND"), "F-VFL-IND")

    def test_no_matchea_texto_sin_relacion(self) -> None:
        self.assertIsNone(extraer_comando_info_cable("Hola, ¿cómo estás?"))

    def test_no_matchea_verificar_cable(self) -> None:
        """El comando "Verificar cable" es distinto (no implementado todavía) — no debe confundirse."""
        self.assertIsNone(extraer_comando_info_cable("Verificar cable F-VFL-IND BN"))

    def test_texto_vacio_no_matchea(self) -> None:
        self.assertIsNone(extraer_comando_info_cable(""))


class TestBuscarCableYRespuestas(unittest.TestCase):
    def test_buscar_cable_usa_match_exacto_case_insensitive(self) -> None:
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = ["cable_fake"]

        resultado = buscar_cable_por_nombre(session, "f-vfl-ind")

        self.assertEqual(resultado, ["cable_fake"])
        session.query.assert_called_once()

    def test_respuesta_no_encontrado(self) -> None:
        texto = construir_respuesta_no_encontrado("F-INEXISTENTE")
        self.assertIn("F-INEXISTENTE", texto)
        self.assertIn("No encontré", texto)

    def test_respuesta_ambiguo_lista_n_ids(self) -> None:
        cables = [SimpleNamespace(n_id=1), SimpleNamespace(n_id=2)]
        texto = construir_respuesta_ambiguo("F-ALV-2335", cables)
        self.assertIn("F-ALV-2335", texto)
        self.assertIn("1", texto)
        self.assertIn("2", texto)

    def test_construir_respuesta_info_cable_resuelve_extremos_via_botellas(self) -> None:
        """Caso real (n_id 6613293, "F-VFL-IND"): extremo_b_nombre crudo viene vacío — debe
        resolverse vía CromoBotella.nombre por extremo_b_n_id, no quedar en blanco."""
        cable = SimpleNamespace(
            n_id=6613293,
            nombre="F-VFL-IND",
            capacidad="72-BRUG",
            propietario="Metrotel",
            jerarquia="Troncal",
            extremo_a_n_id=6636147,
            extremo_a_nombre="441: Cra M de Justo e Independencia CF Bot 2",
            extremo_b_n_id=6639268,
            extremo_b_nombre="",
        )
        session = MagicMock()
        # _resolver_nombre_extremo resuelve extremo A y luego extremo B, en ese orden — dos
        # llamadas secuenciales a session.query(...).filter(...).scalar().
        session.query.return_value.filter.return_value.scalar.side_effect = [
            "Cra M de Justo e Independencia CF Bot 2",
            "Cra Alicia Moreau de Justo 1210 CF",
        ]

        respuesta = construir_respuesta_info_cable(cable, session)

        self.assertIn("F-VFL-IND", respuesta)
        self.assertIn("72-BRUG", respuesta)
        self.assertIn("Metrotel", respuesta)
        self.assertIn("Troncal", respuesta)
        self.assertIn("Cra M de Justo e Independencia CF Bot 2", respuesta)
        self.assertIn("Cra Alicia Moreau de Justo 1210 CF", respuesta)


class TestHandleAppMention(unittest.TestCase):
    def _make_listener(self):
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event(self, text: str, channel: str = "C123", ts: str = "1.1") -> dict:
        return {"text": text, "channel": channel, "ts": ts}

    def test_ignora_mencion_sin_comando_reconocido(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("<@U0BOT123> hola, ¿cómo estás?")

        listener._handle_app_mention(event, client_mock)

        client_mock.chat_postMessage.assert_not_called()

    def test_recorta_mention_prefix_y_responde_info_cable(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("<@U0BOT123> Info cable F-VFL-IND")
        cable_fake = SimpleNamespace(
            n_id=1, nombre="F-VFL-IND", capacidad="72-BRUG", propietario="Metrotel",
            jerarquia="Troncal", extremo_a_n_id=None, extremo_a_nombre="A", extremo_b_n_id=None,
            extremo_b_nombre="B",
        )

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_cable_por_nombre",
                return_value=[cable_fake],
            ),
        ):
            listener._handle_app_mention(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()
        kwargs = client_mock.chat_postMessage.call_args.kwargs
        self.assertEqual(kwargs["channel"], "C123")
        self.assertIn("F-VFL-IND", kwargs["text"])

    def test_responde_no_encontrado_si_cero_matches(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Info cable F-INEXISTENTE")

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_nombre", return_value=[]),
        ):
            listener._handle_app_mention(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()
        self.assertIn("No encontré", client_mock.chat_postMessage.call_args.kwargs["text"])

    def test_responde_ambiguo_si_dos_matches(self) -> None:
        """Caso real conocido: "F-ALV-2335" tiene 2 cables vigentes con el mismo nombre."""
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Info cable F-ALV-2335")
        cables_fake = [SimpleNamespace(n_id=1), SimpleNamespace(n_id=2)]

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_nombre", return_value=cables_fake),
        ):
            listener._handle_app_mention(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("1", texto)
        self.assertIn("2", texto)


class TestExtraerComandoCableBuffer(unittest.TestCase):
    def test_matchea_verificar_con_b_pegado(self) -> None:
        self.assertEqual(
            extraer_comando_cable_buffer("Verificar cable F-VFL-IND B1"),
            ("verificar", "F-VFL-IND", 1),
        )

    def test_matchea_info_con_b_con_espacio(self) -> None:
        self.assertEqual(
            extraer_comando_cable_buffer("Info cable F-VFL-IND B 2"),
            ("info", "F-VFL-IND", 2),
        )

    def test_matchea_con_buffer_completo(self) -> None:
        self.assertEqual(
            extraer_comando_cable_buffer("Info cable F-VFL-IND Buffer 3"),
            ("info", "F-VFL-IND", 3),
        )

    def test_case_insensitive_y_normaliza_verbo(self) -> None:
        self.assertEqual(
            extraer_comando_cable_buffer("INFO CABLE f-vfl-ind buffer1"),
            ("info", "f-vfl-ind", 1),
        )

    def test_no_matchea_sin_sufijo_buffer(self) -> None:
        """"Info cable X" sin B<N> no es un comando de buffer — lo maneja extraer_comando_info_cable."""
        self.assertIsNone(extraer_comando_cable_buffer("Info cable F-VFL-IND"))

    def test_no_matchea_bn_literal_sin_numero(self) -> None:
        """El "BN" genérico de la spec original no es un comando parseable — hace falta el número real."""
        self.assertIsNone(extraer_comando_cable_buffer("Verificar cable F-VFL-IND BN"))

    def test_no_matchea_texto_sin_relacion(self) -> None:
        self.assertIsNone(extraer_comando_cable_buffer("hola, ¿cómo estás?"))


class TestResolverTuboYContarBuffers(unittest.TestCase):
    def test_resolver_tubo_resta_uno_al_numero_humano(self) -> None:
        """B1 (conteo humano) debe consultar orden=0 (conteo real en la DB)."""
        session = MagicMock()
        tubo_fake = SimpleNamespace(n_id=1, orden=0)
        session.query.return_value.filter.return_value.first.return_value = tubo_fake

        resultado = resolver_tubo_por_numero(session, cable_n_id=99, numero_buffer=1)

        self.assertIs(resultado, tubo_fake)

    def test_contar_buffers_cable(self) -> None:
        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = 6

        self.assertEqual(contar_buffers_cable(session, cable_n_id=99), 6)

    def test_contar_buffers_cable_none_da_cero(self) -> None:
        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = None

        self.assertEqual(contar_buffers_cable(session, cable_n_id=99), 0)


class TestRespuestasBuffer(unittest.TestCase):
    def test_respuesta_buffer_no_encontrado_con_buffers_disponibles(self) -> None:
        texto = construir_respuesta_buffer_no_encontrado("F-VFL-IND", 9, 6)
        self.assertIn("F-VFL-IND", texto)
        self.assertIn("9", texto)
        self.assertIn("6", texto)

    def test_respuesta_buffer_no_encontrado_sin_buffers(self) -> None:
        texto = construir_respuesta_buffer_no_encontrado("F-SIN-TUBOS", 1, 0)
        self.assertIn("no tiene buffers registrados", texto)

    def test_respuesta_verificar_buffer_sin_servicios(self) -> None:
        cable = SimpleNamespace(nombre="F-VFL-IND")
        tubo = SimpleNamespace(orden=0, nombre_color="AZ")
        resultado = ResultadoTubo(tubo_n_id=1, cable_n_id=99, orden=0, nombre_color="AZ", servicios=[])

        texto = construir_respuesta_verificar_buffer(cable, tubo, resultado)

        self.assertIn("B1", texto)
        self.assertIn("AZ", texto)
        self.assertIn("Sin servicios", texto)

    def test_respuesta_verificar_buffer_con_servicios(self) -> None:
        cable = SimpleNamespace(nombre="F-VFL-IND")
        tubo = SimpleNamespace(orden=2, nombre_color="VR")
        servicio = ServicioEncontrado(
            servicio_id=1, servicio_id_externo="2001", numero_primer_servicio="2001",
            nombre_cliente="Cliente Real", cliente=None, estado_servicio="ACTIVO", categoria=1,
            tipo_servicio="FO", pelo_n_id=555, servicio_numero_match="2001", metodo="EXACTO",
        )
        resultado = ResultadoTubo(tubo_n_id=1, cable_n_id=99, orden=2, nombre_color="VR", servicios=[servicio])

        texto = construir_respuesta_verificar_buffer(cable, tubo, resultado)

        self.assertIn("B3", texto)
        self.assertIn("2001", texto)
        self.assertIn("Cliente Real", texto)
        self.assertIn("ACTIVO", texto)

    def test_respuesta_info_buffer_distingue_libre_indeterminado_y_match(self) -> None:
        cable = SimpleNamespace(nombre="F-VFL-IND")
        tubo = SimpleNamespace(orden=0, nombre_color="AZ")
        servicio = ServicioEncontrado(
            servicio_id=1, servicio_id_externo="2001", numero_primer_servicio="2001",
            nombre_cliente="Cliente Real", cliente=None, estado_servicio="ACTIVO", categoria=1,
            tipo_servicio="FO", pelo_n_id=1, servicio_numero_match="2001", metodo="EXACTO",
        )
        pelo_matcheado = SimpleNamespace(n_id=1, numero_pelo="1", servicio_raw="FO 2001", servicios=[servicio])
        pelo_libre = SimpleNamespace(n_id=2, numero_pelo="2", servicio_raw=None, servicios=[])
        pelo_indeterminado = SimpleNamespace(
            n_id=3, numero_pelo="3", servicio_raw="algo sin parsear", servicios=[]
        )

        texto = construir_respuesta_info_buffer(cable, tubo, [pelo_matcheado, pelo_libre, pelo_indeterminado])

        self.assertIn("2001", texto)
        self.assertIn("Cliente Real", texto)
        self.assertIn("Pelo 2: Libre", texto)
        self.assertIn('No se identifica cliente/cable — "algo sin parsear"', texto)

    def test_respuesta_info_buffer_sin_pelos(self) -> None:
        cable = SimpleNamespace(nombre="F-VFL-IND")
        tubo = SimpleNamespace(orden=0, nombre_color="AZ")

        texto = construir_respuesta_info_buffer(cable, tubo, [])

        self.assertIn("Sin pelos registrados", texto)


class TestHandleCableBuffer(unittest.TestCase):
    def _make_listener(self):
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event(self, text: str, channel: str = "C123", ts: str = "1.1") -> dict:
        return {"text": text, "channel": channel, "ts": ts}

    def test_verificar_cable_buffer_responde_con_servicios(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Verificar cable F-VFL-IND B1")
        cable_fake = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        tubo_fake = SimpleNamespace(n_id=1, orden=0, nombre_color="AZ")
        resultado_fake = ResultadoTubo(tubo_n_id=1, cable_n_id=99, orden=0, nombre_color="AZ", servicios=[])

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_nombre", return_value=[cable_fake]),
            patch("modules.slack_baneo_notifier.listener.resolver_tubo_por_numero", return_value=tubo_fake),
            patch("modules.slack_baneo_notifier.listener.servicios_por_tubo_sync", return_value=resultado_fake),
        ):
            listener._handle_app_mention(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("F-VFL-IND", texto)
        self.assertIn("B1", texto)

    def test_info_cable_buffer_responde_con_pelos(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Info cable F-VFL-IND B1")
        cable_fake = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        tubo_fake = SimpleNamespace(n_id=1, orden=0, nombre_color="AZ")
        pelo_fake = SimpleNamespace(n_id=1, numero_pelo="1", servicio_raw=None, servicios=[])

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_nombre", return_value=[cable_fake]),
            patch("modules.slack_baneo_notifier.listener.resolver_tubo_por_numero", return_value=tubo_fake),
            patch("modules.slack_baneo_notifier.listener.pelos_de_tubo_sync", return_value=[pelo_fake]),
        ):
            listener._handle_app_mention(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("F-VFL-IND", texto)
        self.assertIn("Libre", texto)

    def test_buffer_inexistente_responde_aviso(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Info cable F-VFL-IND B9")
        cable_fake = SimpleNamespace(n_id=99, nombre="F-VFL-IND")

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_nombre", return_value=[cable_fake]),
            patch("modules.slack_baneo_notifier.listener.resolver_tubo_por_numero", return_value=None),
            patch("modules.slack_baneo_notifier.listener.contar_buffers_cable", return_value=6),
        ):
            listener._handle_app_mention(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("no tiene un buffer B9", texto)
        self.assertIn("6", texto)

    def test_cable_no_encontrado_no_llega_a_buscar_buffer(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Verificar cable F-INEXISTENTE B1")

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_nombre", return_value=[]),
            patch("modules.slack_baneo_notifier.listener.resolver_tubo_por_numero") as mock_resolver,
        ):
            listener._handle_app_mention(event, client_mock)

        mock_resolver.assert_not_called()
        self.assertIn("No encontré", client_mock.chat_postMessage.call_args.kwargs["text"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
