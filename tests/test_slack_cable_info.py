# Nombre de archivo: test_slack_cable_info.py
# Ubicación de archivo: tests/test_slack_cable_info.py
# Descripción: Tests de los comandos "Info cable"/"Verificar cable"/"Servicios" (con y sin buffer) — parser, lookup y handlers app_mention

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("TESTING", "true")

from core.services.cromo.verificador import (
    ResultadoServiciosUnicos,
    ResultadoTubo,
    ServicioEncontrado,
    ServicioUnico,
)
from modules.slack_baneo_notifier.cable_info import (
    _linea_frescura_prov,
    buscar_cable_por_n_id_o_nombre,
    buscar_cable_por_nombre,
    construir_respuesta_ambiguo,
    construir_respuesta_buffer_no_encontrado,
    construir_respuesta_info_buffer,
    construir_respuesta_info_cable,
    construir_respuesta_no_encontrado,
    construir_respuesta_servicios_buffer,
    construir_respuesta_servicios_cable,
    construir_respuesta_verificar_buffer,
    contar_buffers_cable,
    extraer_comando_cable_buffer,
    extraer_comando_info_cable,
    extraer_comando_servicios_buffer,
    extraer_comando_servicios_cable,
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

    def test_quita_negrita_slack_del_nombre(self) -> None:
        """Bug real 2026-08-25, reproducido con el payload crudo real de Slack (canal
        #baneo-de-camaras-prueba, mensaje 1787653453.531689): el usuario escribe el código en
        *negrita* (uso normal de Slack) — `*F-VDP-JUR*` llega literal en `event["text"]`, sin que
        Slack lo "renderice" antes. Sin este fix, `nombre` queda "*F-VDP-JUR*" (asteriscos incluidos)
        y el lookup exacto contra `cromo_cables.nombre` nunca matchea nada, aunque el cable exista."""
        self.assertEqual(extraer_comando_info_cable("info cable *F-VDP-JUR*"), "F-VDP-JUR")

    def test_quita_otros_caracteres_de_formato_slack(self) -> None:
        self.assertEqual(extraer_comando_info_cable("info cable _F-VDP-JUR_"), "F-VDP-JUR")
        self.assertEqual(extraer_comando_info_cable("info cable `F-VDP-JUR`"), "F-VDP-JUR")
        self.assertEqual(extraer_comando_info_cable("info cable ~F-VDP-JUR~"), "F-VDP-JUR")


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


class TestBuscarCablePorNIdONombre(unittest.TestCase):
    """Bug real 2026-08-25: `buscar_cable_por_nombre` sólo matchea por `nombre` — cuando el bot pide
    "especificá por n_id" (`construir_respuesta_ambiguo`) y el usuario retoma el comando con el n_id
    sugerido, la búsqueda por nombre no encuentra nada (ningún cable se llama literalmente "10260935")
    y responde "no encontré el cable", aunque exista. Verificado con datos reales de
    `lasfocasdev-postgres`: "F-LEM-11-A" tiene 2 cables vigentes (n_id 10260935 y 9498169)."""

    def test_texto_numerico_busca_por_n_id_no_por_nombre(self) -> None:
        session = MagicMock()
        cable_fake = SimpleNamespace(n_id=10260935, nombre="F-LEM-11-A")
        session.query.return_value.filter.return_value.first.return_value = cable_fake

        resultado = buscar_cable_por_n_id_o_nombre(session, "10260935")

        self.assertEqual(resultado, [cable_fake])
        session.query.return_value.filter.return_value.all.assert_not_called()

    def test_texto_numerico_sin_match_devuelve_lista_vacia(self) -> None:
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        self.assertEqual(buscar_cable_por_n_id_o_nombre(session, "999999999"), [])

    def test_texto_no_numerico_cae_a_busqueda_por_nombre(self) -> None:
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = ["cable_fake"]

        resultado = buscar_cable_por_n_id_o_nombre(session, "F-LEM-11-A")

        self.assertEqual(resultado, ["cable_fake"])

    def test_texto_numerico_con_espacios_se_recorta(self) -> None:
        session = MagicMock()
        cable_fake = SimpleNamespace(n_id=9498169, nombre="F-LEM-11-A")
        session.query.return_value.filter.return_value.first.return_value = cable_fake

        resultado = buscar_cable_por_n_id_o_nombre(session, "  9498169  ")

        self.assertEqual(resultado, [cable_fake])


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
                "modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre",
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
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[]),
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
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=cables_fake),
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

    def test_quita_negrita_slack_del_nombre_y_buffer(self) -> None:
        """Bug real 2026-08-25, reproducido con el payload crudo real de Slack (mensaje
        1787657001.749649): `*F-VDP-JUR b1*` — el `*` final rompe el ancla `$` del regex de buffer
        (nunca matcheaba, caía a `extraer_comando_info_cable`, que se comía "b1*" y el "*" inicial
        como si fueran parte del nombre)."""
        self.assertEqual(
            extraer_comando_cable_buffer("info cable *F-VDP-JUR b1*"),
            ("info", "F-VDP-JUR", 1),
        )

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
        """Formato nuevo (ticket 2026-08-25): pelos con servicio muestran
        Tipo — Línea — Cliente — Descripción (Estado); libres/sin match muestran sólo
        "Libre — Descripción" (o "Libre" a secas si no hay descripción cruda)."""
        cable = SimpleNamespace(nombre="F-VFL-IND")
        tubo = SimpleNamespace(orden=0, nombre_color="AZ")
        servicio = ServicioEncontrado(
            servicio_id=1, servicio_id_externo="2001", numero_primer_servicio="2001",
            nombre_cliente="Cliente Real", cliente=None, estado_servicio="ACTIVO", categoria=1,
            tipo_servicio="FO", pelo_n_id=1, servicio_numero_match="2001", metodo="EXACTO",
        )
        pelo_matcheado = SimpleNamespace(
            n_id=1, numero_pelo="1", color="AZ", servicio_raw="FO 2001 - Cliente Real", servicios=[servicio]
        )
        pelo_libre = SimpleNamespace(n_id=2, numero_pelo="2", color="AZ", servicio_raw=None, servicios=[])
        pelo_indeterminado = SimpleNamespace(
            n_id=3, numero_pelo="3", color="AZ", servicio_raw="algo sin parsear", servicios=[]
        )

        texto = construir_respuesta_info_buffer(cable, tubo, [pelo_matcheado, pelo_libre, pelo_indeterminado])

        self.assertIn(
            "Pelo 1 (AZ): FO — 2001 — Cliente Real — FO 2001 - Cliente Real (ACTIVO)", texto
        )
        self.assertIn("Pelo 2 (AZ): Libre", texto)
        self.assertNotIn("Pelo 2 (AZ): Libre —", texto)  # sin descripción, sin guión colgando
        self.assertIn("Pelo 3 (AZ): Libre — algo sin parsear", texto)

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
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[cable_fake]),
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
        pelo_fake = SimpleNamespace(n_id=1, numero_pelo="1", color="AZ", servicio_raw=None, servicios=[])

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[cable_fake]),
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
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[cable_fake]),
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
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[]),
            patch("modules.slack_baneo_notifier.listener.resolver_tubo_por_numero") as mock_resolver,
        ):
            listener._handle_app_mention(event, client_mock)

        mock_resolver.assert_not_called()
        self.assertIn("No encontré", client_mock.chat_postMessage.call_args.kwargs["text"])


def _servicio_unico(
    servicio_id: int,
    servicio_id_externo: str,
    pelos_n_ids: list[int],
    numeros_en_pelo: list[str] | None = None,
) -> ServicioUnico:
    return ServicioUnico(
        servicio_id=servicio_id,
        servicio_id_externo=servicio_id_externo,
        numero_primer_servicio=servicio_id_externo,
        nombre_cliente="Cliente Real",
        cliente=None,
        estado_servicio="ACTIVO",
        tipo_servicio="FO",
        pelos_n_ids=pelos_n_ids,
        cantidad_pelos=len(pelos_n_ids),
        numeros_en_pelo=numeros_en_pelo if numeros_en_pelo is not None else [servicio_id_externo],
        metodos=["EXACTO"],
    )


class TestLineaFrescuraProv(unittest.TestCase):
    """Fix final (Important C) — cobertura cero de una decisión vinculante: `grep -rn
    "refrescando" tests/` sólo encontraba `assertNotIn` (el caso `refrescando=False`, default).
    Vaciar el sufijo en `_linea_frescura_prov` ("mutá la corrección") dejaba la suite entera en
    verde porque el caso POSITIVO (`refrescando=True`) nunca se ejercitaba. Este test cubre
    directamente la promesa: "prometer un refresco que no ocurre sería mentirle al técnico"."""

    def test_refrescando_true_agrega_sufijo(self) -> None:
        servicios = [_servicio_unico(1, "133345", [10]), _servicio_unico(2, "140002", [11])]
        linea = _linea_frescura_prov(servicios, vencidos={1}, refrescando=True)
        assert linea is not None
        self.assertIn("— refrescando…", linea)
        self.assertEqual(linea, "🕒 1 con validación PROV vencida — refrescando…")

    def test_refrescando_false_no_agrega_sufijo(self) -> None:
        servicios = [_servicio_unico(1, "133345", [10])]
        linea = _linea_frescura_prov(servicios, vencidos={1}, refrescando=False)
        assert linea is not None
        self.assertNotIn("refrescando", linea)


class TestVerboServiciosLibre(unittest.TestCase):
    """Precondición del brief (Task 8): antes de agregar el comando nuevo, confirmar que el verbo
    "Servicios" no matchea ya ninguno de los parsers existentes — si matcheara, el comando nuevo
    quedaría inalcanzable detrás de uno viejo."""

    def test_no_matchea_info_cable(self) -> None:
        self.assertIsNone(extraer_comando_info_cable("Servicios F-VFL-IND"))

    def test_no_matchea_cable_buffer(self) -> None:
        self.assertIsNone(extraer_comando_cable_buffer("Servicios F-VFL-IND B1"))


class TestExtraerComandoServiciosCable(unittest.TestCase):
    def test_matchea_comando_simple(self) -> None:
        self.assertEqual(extraer_comando_servicios_cable("Servicios F-VFL-IND"), "F-VFL-IND")

    def test_matchea_con_palabra_cable(self) -> None:
        self.assertEqual(extraer_comando_servicios_cable("Servicios cable F-VFL-IND"), "F-VFL-IND")

    def test_case_insensitive(self) -> None:
        self.assertEqual(extraer_comando_servicios_cable("servicios f-vfl-ind"), "f-vfl-ind")

    def test_quita_negrita_slack_del_nombre(self) -> None:
        self.assertEqual(extraer_comando_servicios_cable("Servicios *F-VFL-IND*"), "F-VFL-IND")

    def test_no_matchea_texto_sin_relacion(self) -> None:
        self.assertIsNone(extraer_comando_servicios_cable("Info cable F-VFL-IND"))

    def test_no_matchea_verbo_en_medio_de_la_frase(self) -> None:
        """El regex exige "servicios" al comienzo (`^`) — no interpreta cualquier mención que
        contenga la palabra en otro lugar del texto."""
        self.assertIsNone(extraer_comando_servicios_cable("dame los servicios de F-VFL-IND"))

    def test_texto_vacio_no_matchea(self) -> None:
        self.assertIsNone(extraer_comando_servicios_cable(""))


class TestExtraerComandoServiciosBuffer(unittest.TestCase):
    def test_matchea_con_b_pegado(self) -> None:
        self.assertEqual(extraer_comando_servicios_buffer("Servicios F-VFL-IND B1"), ("F-VFL-IND", 1))

    def test_matchea_con_buffer_completo(self) -> None:
        self.assertEqual(
            extraer_comando_servicios_buffer("Servicios cable F-VFL-IND Buffer 2"), ("F-VFL-IND", 2)
        )

    def test_case_insensitive(self) -> None:
        self.assertEqual(extraer_comando_servicios_buffer("SERVICIOS f-vfl-ind b1"), ("f-vfl-ind", 1))

    def test_no_matchea_sin_sufijo_buffer(self) -> None:
        self.assertIsNone(extraer_comando_servicios_buffer("Servicios F-VFL-IND"))

    def test_quita_negrita_slack(self) -> None:
        self.assertEqual(extraer_comando_servicios_buffer("Servicios *F-VFL-IND B1*"), ("F-VFL-IND", 1))

    def test_precedencia_sobre_el_parser_goloso(self) -> None:
        """Si `extraer_comando_servicios_cable` se probara ANTES que este, se comería "B1" como
        parte del nombre del cable — por eso el listener prueba el de buffer primero (mismo motivo
        que `extraer_comando_cable_buffer` vs. `extraer_comando_info_cable`)."""
        texto = "Servicios F-VFL-IND B1"
        self.assertEqual(extraer_comando_servicios_buffer(texto), ("F-VFL-IND", 1))
        self.assertEqual(extraer_comando_servicios_cable(texto), "F-VFL-IND B1")


class TestConstruirRespuestaServiciosCable(unittest.TestCase):
    def test_sin_servicios(self) -> None:
        cable = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        resultado = ResultadoServiciosUnicos(cable_n_id=99, tubo_n_id=None, servicios=[])

        texto = construir_respuesta_servicios_cable(cable, MagicMock(), resultado, vencidos=set())

        self.assertIn("Sin servicios matcheados en este cable", texto)

    def test_agrupa_por_buffer_sin_query_por_servicio_y_sin_ids_repetidos(self) -> None:
        """El cable de control real (`FO-FL-1003`, n_id 6610203) tiene 118 servicios únicos — la
        agrupación no puede costar una query por servicio. Dos consultas batch (pelo→tubo,
        tubo→orden/color de TODO el cable) alcanzan."""
        cable = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        servicios = [
            _servicio_unico(1, "133345", [10]),
            _servicio_unico(2, "140002", [11]),
            _servicio_unico(3, "145002", [20], numeros_en_pelo=["122214"]),
        ]
        resultado = ResultadoServiciosUnicos(cable_n_id=99, tubo_n_id=None, servicios=servicios)
        session = MagicMock()
        session.execute.return_value.all.side_effect = [
            [(10, 100), (11, 100), (20, 200)],  # pelo_n_id -> tubo_n_id
            [(100, 0, "AZ"), (200, 1, "NR")],  # tubo_n_id -> (orden, nombre_color)
        ]

        texto = construir_respuesta_servicios_cable(cable, session, resultado, vencidos={2})

        self.assertEqual(session.execute.call_count, 2)
        self.assertIn("3 ID(s) únicos", texto)
        self.assertIn("B1 (AZ): 133345, 140002", texto)
        self.assertIn("B2 (NR): 145002", texto)
        self.assertIn("En el pelo figura otro número: 145002 (el pelo dice 122214)", texto)
        self.assertIn("🕒 1 con validación PROV vencida", texto)
        self.assertNotIn("refrescando", texto)
        # Cada ID aparece en exactamente UN grupo de buffer (nunca duplicado entre B1/B2); "145002"
        # aparece una segunda vez, legítimamente, en la línea de discrepancia de número.
        lineas_buffer = [l for l in texto.split("\n") if l.startswith("B1") or l.startswith("B2")]
        self.assertEqual(len(lineas_buffer), 2)
        ids_por_linea = [l.split(": ", 1)[1] for l in lineas_buffer]
        todos_los_ids_listados = ", ".join(ids_por_linea).split(", ")
        self.assertEqual(len(todos_los_ids_listados), len(set(todos_los_ids_listados)))
        self.assertEqual(sorted(todos_los_ids_listados), ["133345", "140002", "145002"])

    def test_no_hay_linea_de_frescura_si_ningun_vencido(self) -> None:
        cable = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        servicios = [_servicio_unico(1, "133345", [10])]
        resultado = ResultadoServiciosUnicos(cable_n_id=99, tubo_n_id=None, servicios=servicios)
        session = MagicMock()
        session.execute.return_value.all.side_effect = [[(10, 100)], [(100, 0, "AZ")]]

        texto = construir_respuesta_servicios_cable(cable, session, resultado, vencidos=set())

        self.assertNotIn("🕒", texto)

    def test_servicio_representado_por_su_primer_pelo_no_se_duplica_entre_buffers(self) -> None:
        """Un servicio con pelos en más de un tubo (caso raro) se cuenta UNA sola vez, bajo el
        buffer de su primer pelo (`pelos_n_ids[0]`, ya ordenado ascendente) — nunca se listaría dos
        veces bajo dos buffers distintos."""
        cable = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        servicio = _servicio_unico(1, "133345", [10, 20])
        resultado = ResultadoServiciosUnicos(cable_n_id=99, tubo_n_id=None, servicios=[servicio])
        session = MagicMock()
        session.execute.return_value.all.side_effect = [
            [(10, 100), (20, 200)],
            [(100, 0, "AZ"), (200, 1, "NR")],
        ]

        texto = construir_respuesta_servicios_cable(cable, session, resultado, vencidos=set())

        self.assertEqual(texto.count("133345"), 1)
        self.assertIn("B1 (AZ): 133345", texto)
        self.assertNotIn("B2", texto)

    def test_pelo_sin_tubo_resuelto_cae_en_grupo_sin_buffer(self) -> None:
        cable = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        servicio = _servicio_unico(1, "133345", [999])  # 999 no aparece en ningún mapa
        resultado = ResultadoServiciosUnicos(cable_n_id=99, tubo_n_id=None, servicios=[servicio])
        session = MagicMock()
        session.execute.return_value.all.side_effect = [[], []]

        texto = construir_respuesta_servicios_cable(cable, session, resultado, vencidos=set())

        self.assertIn("Sin buffer identificado: 133345", texto)


class TestConstruirRespuestaServiciosBuffer(unittest.TestCase):
    def test_sin_servicios(self) -> None:
        cable = SimpleNamespace(nombre="F-VFL-IND")
        tubo = SimpleNamespace(orden=0, nombre_color="AZ")
        resultado = ResultadoServiciosUnicos(cable_n_id=None, tubo_n_id=1, servicios=[])

        texto = construir_respuesta_servicios_buffer(cable, tubo, resultado, vencidos=set())

        self.assertIn("B1", texto)
        self.assertIn("Sin servicios matcheados en este buffer", texto)

    def test_ids_unicos_sin_repetir_con_discrepancia_y_frescura(self) -> None:
        cable = SimpleNamespace(nombre="F-VFL-IND")
        tubo = SimpleNamespace(orden=0, nombre_color="AZ")
        servicios = [
            _servicio_unico(1, "133345", [10]),
            _servicio_unico(2, "140002", [11], numeros_en_pelo=["122214", "140002"]),
        ]
        resultado = ResultadoServiciosUnicos(cable_n_id=None, tubo_n_id=1, servicios=servicios)

        texto = construir_respuesta_servicios_buffer(cable, tubo, resultado, vencidos={2})

        lineas = texto.split("\n")
        self.assertIn("2 ID(s) únicos", lineas[0])
        self.assertEqual(lineas[1], "133345, 140002")
        self.assertIn("En el pelo figura otro número: 140002 (el pelo dice 122214)", texto)
        self.assertIn("🕒 1 con validación PROV vencida", texto)
        self.assertNotIn("refrescando", texto)


class TestMarcadorFrescuraInfoBuffer(unittest.TestCase):
    """Step 4 del brief: "Info cable X BN" marca (sin cambiar su función ni disparar refresco) los
    pelos cuyo servicio matcheado tiene la sincronización PROV vencida."""

    def _pelo_con_servicio(self, servicio_id: int) -> SimpleNamespace:
        servicio = ServicioEncontrado(
            servicio_id=servicio_id, servicio_id_externo="2001", numero_primer_servicio="2001",
            nombre_cliente="Cliente Real", cliente=None, estado_servicio="ACTIVO", categoria=1,
            tipo_servicio="FO", pelo_n_id=1, servicio_numero_match="2001", metodo="EXACTO",
        )
        return SimpleNamespace(
            n_id=1, numero_pelo="1", color="AZ", servicio_raw="FO 2001 - Cliente Real", servicios=[servicio]
        )

    def test_marca_con_reloj_el_pelo_vencido(self) -> None:
        cable = SimpleNamespace(nombre="F-VFL-IND")
        tubo = SimpleNamespace(orden=0, nombre_color="AZ")
        pelo = self._pelo_con_servicio(servicio_id=7)

        texto = construir_respuesta_info_buffer(cable, tubo, [pelo], vencidos={7})

        self.assertIn("🕒", texto)

    def test_no_marca_si_no_esta_vencido(self) -> None:
        cable = SimpleNamespace(nombre="F-VFL-IND")
        tubo = SimpleNamespace(orden=0, nombre_color="AZ")
        pelo = self._pelo_con_servicio(servicio_id=7)

        texto = construir_respuesta_info_buffer(cable, tubo, [pelo], vencidos=set())

        self.assertNotIn("🕒", texto)

    def test_compatibilidad_hacia_atras_sin_pasar_vencidos(self) -> None:
        """Los callers existentes (y los tests viejos de esta suite) siguen llamando con 3
        posicionales — el parámetro nuevo tiene que ser opcional para no romper ese contrato."""
        cable = SimpleNamespace(nombre="F-VFL-IND")
        tubo = SimpleNamespace(orden=0, nombre_color="AZ")
        pelo = self._pelo_con_servicio(servicio_id=7)

        texto = construir_respuesta_info_buffer(cable, tubo, [pelo])

        self.assertNotIn("🕒", texto)

    def test_no_marca_pelos_libres(self) -> None:
        cable = SimpleNamespace(nombre="F-VFL-IND")
        tubo = SimpleNamespace(orden=0, nombre_color="AZ")
        pelo_libre = SimpleNamespace(n_id=2, numero_pelo="2", color="AZ", servicio_raw=None, servicios=[])

        texto = construir_respuesta_info_buffer(cable, tubo, [pelo_libre], vencidos={999})

        self.assertNotIn("🕒", texto)


class TestHandleServiciosCable(unittest.TestCase):
    def _make_listener(self):
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event(self, text: str, channel: str = "C123", ts: str = "1.1") -> dict:
        return {"text": text, "channel": channel, "ts": ts}

    def test_responde_ids_unicos_agrupados_por_buffer(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Servicios F-VFL-IND")
        cable_fake = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        servicios = [
            _servicio_unico(1, "133345", [10]),
            _servicio_unico(2, "140002", [11]),
            _servicio_unico(3, "145002", [20], numeros_en_pelo=["122214"]),
        ]
        resultado = ResultadoServiciosUnicos(cable_n_id=99, tubo_n_id=None, servicios=servicios)

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_local,
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[cable_fake]),
            patch("modules.slack_baneo_notifier.listener.servicios_unicos_por_cable_sync", return_value=resultado),
            patch("modules.slack_baneo_notifier.listener.servicios_vencidos_sync", return_value={2}),
        ):
            session_mock = mock_session_local.return_value
            session_mock.execute.return_value.all.side_effect = [
                [(10, 100), (11, 100), (20, 200)],
                [(100, 0, "AZ"), (200, 1, "NR")],
            ]
            listener._handle_app_mention(event, client_mock)

        client_mock.chat_postMessage.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("3 ID(s) únicos", texto)
        self.assertIn("B1 (AZ): 133345, 140002", texto)
        self.assertIn("B2 (NR): 145002", texto)
        self.assertIn("En el pelo figura otro número: 145002 (el pelo dice 122214)", texto)
        self.assertIn("🕒 1 con validación PROV vencida", texto)
        self.assertNotIn("refrescando", texto)
        lineas_buffer = [l for l in texto.split("\n") if l.startswith("B1") or l.startswith("B2")]
        self.assertEqual(len(lineas_buffer), 2)
        ids_por_linea = [l.split(": ", 1)[1] for l in lineas_buffer]
        todos_los_ids_listados = ", ".join(ids_por_linea).split(", ")
        self.assertEqual(len(todos_los_ids_listados), len(set(todos_los_ids_listados)))
        self.assertEqual(sorted(todos_los_ids_listados), ["133345", "140002", "145002"])

    def test_refrescando_true_aparece_en_el_mensaje(self) -> None:
        """Fix final (Important C), nivel "cableado del listener" — mutar `refrescando=False` a
        mano en la llamada de `_handle_servicios_cable` a `construir_respuesta_servicios_cable`
        dejaba la suite entera en verde (280 passed, 0 fallas): ningún test verificaba que un
        `_disparar_refresco_prov` exitoso (`refrescando=True`) realmente llegue al mensaje
        posteado en el hilo."""
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Servicios F-VFL-IND")
        cable_fake = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        servicios = [_servicio_unico(1, "133345", [10])]
        resultado = ResultadoServiciosUnicos(cable_n_id=99, tubo_n_id=None, servicios=servicios)

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal") as mock_session_local,
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[cable_fake]),
            patch("modules.slack_baneo_notifier.listener.servicios_unicos_por_cable_sync", return_value=resultado),
            patch("modules.slack_baneo_notifier.listener.servicios_vencidos_sync", return_value={1}),
            patch.object(listener, "_disparar_refresco_prov", return_value=(True, None)),
        ):
            session_mock = mock_session_local.return_value
            session_mock.execute.return_value.all.side_effect = [[(10, 100)], [(100, 0, "AZ")]]
            listener._handle_app_mention(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("— refrescando…", texto)

    def test_cable_no_encontrado(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Servicios F-INEXISTENTE")

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[]),
        ):
            listener._handle_app_mention(event, client_mock)

        self.assertIn("No encontré", client_mock.chat_postMessage.call_args.kwargs["text"])

    def test_cable_ambiguo(self) -> None:
        """Caso real conocido: "F-ALV-2335" tiene 2 cables vigentes con el mismo nombre."""
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Servicios F-ALV-2335")
        cables_fake = [SimpleNamespace(n_id=1), SimpleNamespace(n_id=2)]

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=cables_fake),
        ):
            listener._handle_app_mention(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("1", texto)
        self.assertIn("2", texto)

    def test_negrita_slack_en_el_nombre(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Servicios *F-VFL-IND*")
        cable_fake = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        resultado = ResultadoServiciosUnicos(cable_n_id=99, tubo_n_id=None, servicios=[])

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[cable_fake]
            ) as mock_buscar,
            patch("modules.slack_baneo_notifier.listener.servicios_unicos_por_cable_sync", return_value=resultado),
        ):
            listener._handle_app_mention(event, client_mock)

        self.assertEqual(mock_buscar.call_args.args[1], "F-VFL-IND")


class TestHandleServiciosBuffer(unittest.TestCase):
    def _make_listener(self):
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event(self, text: str, channel: str = "C123", ts: str = "1.1") -> dict:
        return {"text": text, "channel": channel, "ts": ts}

    def test_precedencia_buffer_antes_que_cable_entero(self) -> None:
        """"Servicios <cable> B<N>" debe resolverse como comando de BUFFER, no como el comando de
        cable entero (que se comería "B1" como parte del nombre si se probara primero)."""
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Servicios F-VFL-IND B1")
        cable_fake = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        tubo_fake = SimpleNamespace(n_id=1, orden=0, nombre_color="AZ")
        resultado = ResultadoServiciosUnicos(cable_n_id=None, tubo_n_id=1, servicios=[])

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[cable_fake]),
            patch(
                "modules.slack_baneo_notifier.listener.resolver_tubo_por_numero", return_value=tubo_fake
            ) as mock_resolver_tubo,
            patch("modules.slack_baneo_notifier.listener.servicios_unicos_por_tubo_sync", return_value=resultado),
            patch("modules.slack_baneo_notifier.listener.servicios_unicos_por_cable_sync") as mock_cable_sync,
            patch("modules.slack_baneo_notifier.listener.servicios_vencidos_sync", return_value=set()),
        ):
            listener._handle_app_mention(event, client_mock)

        mock_resolver_tubo.assert_called_once()
        mock_cable_sync.assert_not_called()
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("Buffer *B1*", texto)

    def test_refrescando_true_aparece_en_el_mensaje(self) -> None:
        """Fix final (Important C), nivel "cableado del listener" — gemelo de
        `TestHandleServiciosCable.test_refrescando_true_aparece_en_el_mensaje` para la llamada de
        `_handle_servicios_buffer` a `construir_respuesta_servicios_buffer`: mutar `refrescando=False`
        a mano acá también dejaba la suite entera en verde."""
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Servicios F-VFL-IND B1")
        cable_fake = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        tubo_fake = SimpleNamespace(n_id=1, orden=0, nombre_color="AZ")
        servicios = [_servicio_unico(1, "133345", [10])]
        resultado = ResultadoServiciosUnicos(cable_n_id=None, tubo_n_id=1, servicios=servicios)

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[cable_fake]),
            patch("modules.slack_baneo_notifier.listener.resolver_tubo_por_numero", return_value=tubo_fake),
            patch("modules.slack_baneo_notifier.listener.servicios_unicos_por_tubo_sync", return_value=resultado),
            patch("modules.slack_baneo_notifier.listener.servicios_vencidos_sync", return_value={1}),
            patch.object(listener, "_disparar_refresco_prov", return_value=(True, None)),
        ):
            listener._handle_app_mention(event, client_mock)

        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("— refrescando…", texto)

    def test_buffer_inexistente_responde_aviso(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Servicios F-VFL-IND B9")
        cable_fake = SimpleNamespace(n_id=99, nombre="F-VFL-IND")

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[cable_fake]),
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
        event = self._make_event("Servicios F-INEXISTENTE B1")

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[]),
            patch("modules.slack_baneo_notifier.listener.resolver_tubo_por_numero") as mock_resolver,
        ):
            listener._handle_app_mention(event, client_mock)

        mock_resolver.assert_not_called()
        self.assertIn("No encontré", client_mock.chat_postMessage.call_args.kwargs["text"])


class TestInfoCableBufferConsultaFrescura(unittest.TestCase):
    """El marcador de frescura de "Info cable X BN" (Step 4) es un batch nuevo acoplado sólo a esa
    rama del handler — "Verificar cable X BN" (comportamiento exacto conservado, ver brief) no debe
    disparar ninguna consulta de frescura."""

    def _make_listener(self):
        from modules.slack_baneo_notifier.listener import IngresoListener
        return IngresoListener(bot_token="xoxb-test", app_token="xapp-test")

    def _make_event(self, text: str, channel: str = "C123", ts: str = "1.1") -> dict:
        return {"text": text, "channel": channel, "ts": ts}

    def test_info_cable_buffer_marca_pelos_vencidos(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Info cable F-VFL-IND B1")
        cable_fake = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        tubo_fake = SimpleNamespace(n_id=1, orden=0, nombre_color="AZ")
        servicio = ServicioEncontrado(
            servicio_id=7, servicio_id_externo="2001", numero_primer_servicio="2001",
            nombre_cliente="Cliente Real", cliente=None, estado_servicio="ACTIVO", categoria=1,
            tipo_servicio="FO", pelo_n_id=1, servicio_numero_match="2001", metodo="EXACTO",
        )
        pelo_fake = SimpleNamespace(
            n_id=1, numero_pelo="1", color="AZ", servicio_raw="FO 2001 - Cliente Real", servicios=[servicio]
        )

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[cable_fake]),
            patch("modules.slack_baneo_notifier.listener.resolver_tubo_por_numero", return_value=tubo_fake),
            patch("modules.slack_baneo_notifier.listener.pelos_de_tubo_sync", return_value=[pelo_fake]),
            patch(
                "modules.slack_baneo_notifier.listener.servicios_vencidos_sync", return_value={7}
            ) as mock_vencidos,
        ):
            listener._handle_app_mention(event, client_mock)

        mock_vencidos.assert_called_once()
        self.assertEqual(mock_vencidos.call_args.args[1], {7})
        texto = client_mock.chat_postMessage.call_args.kwargs["text"]
        self.assertIn("🕒", texto)

    def test_verificar_cable_buffer_no_consulta_frescura(self) -> None:
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event("Verificar cable F-VFL-IND B1")
        cable_fake = SimpleNamespace(n_id=99, nombre="F-VFL-IND")
        tubo_fake = SimpleNamespace(n_id=1, orden=0, nombre_color="AZ")
        resultado_fake = ResultadoTubo(tubo_n_id=1, cable_n_id=99, orden=0, nombre_color="AZ", servicios=[])

        with (
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.buscar_cable_por_n_id_o_nombre", return_value=[cable_fake]),
            patch("modules.slack_baneo_notifier.listener.resolver_tubo_por_numero", return_value=tubo_fake),
            patch("modules.slack_baneo_notifier.listener.servicios_por_tubo_sync", return_value=resultado_fake),
            patch("modules.slack_baneo_notifier.listener.servicios_vencidos_sync") as mock_vencidos,
        ):
            listener._handle_app_mention(event, client_mock)

        mock_vencidos.assert_not_called()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
