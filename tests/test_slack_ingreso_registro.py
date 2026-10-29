# Nombre de archivo: test_slack_ingreso_registro.py
# Ubicación de archivo: tests/test_slack_ingreso_registro.py
# Descripción: Tests del listener de ingresos de Slack: registro de Ingreso/Egreso y baneo manual sin incidente

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

os.environ.setdefault("TESTING", "true")

from core.services.cromo.camara_botella_busqueda import ResultadoBusquedaExtendida
from tests.soporte_slack_ingreso import _resultado_camara


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
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False, inconsistente=False,
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
            slack_user_id="U0AUB6CRE4A",
            momento=None,
            thread_ts="1234567890.000001",
            canal_id="C123",
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
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False, inconsistente=False,
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
            slack_user_id="U0AUB6CRE4A",
            momento=None,
            thread_ts="1234567890.000001",
            canal_id="C123",
        )
        client_mock.chat_postMessage.assert_called_once()

    def test_registra_movimiento_propaga_thread_ts_y_canal_de_una_respuesta_en_hilo(self) -> None:
        """El wiring de Tarea 3 (2026-09-23) debe leer `thread_ts`/`channel` del evento REAL, no un
        valor fijo: acá se usa un canal y un hilo (`thread_ts` de una respuesta dentro de un hilo,
        distinto del `ts` propio del mensaje) deliberadamente distintos de los defaults de
        `_make_event`, para que la aserción sólo pase si el valor viaja desde el evento de Slack
        hasta `registrar_movimiento_ingreso`."""
        from db.models.infra import CamaraEstado
        from core.services.camara_estado_service import CamaraEstadoContexto

        listener = self._make_listener()
        client_mock = MagicMock()
        camara_mock = self._make_camara()
        camara_mock.estado = CamaraEstado.LIBRE
        contexto_libre = CamaraEstadoContexto(
            camara_id=camara_mock.id, estado_actual=CamaraEstado.LIBRE, estado_sugerido=CamaraEstado.LIBRE,
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False, inconsistente=False,
            incidentes_activos=[], ticket_baneo=None,
        )
        evento = {
            "text": self.TEXTO_CON_INGRESO,
            "channel": "C_OTRO_CANAL",
            "ts": "1111.000111",
            "thread_ts": "2222.000222",
        }

        with (
            patch.object(listener, "_get_config", return_value=("", True, [], False)),
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
            patch("modules.slack_baneo_notifier.listener.registrar_movimiento_ingreso") as mock_registrar,
        ):
            session_mock = MagicMock()
            mock_session_cls.return_value = session_mock
            listener._handle_message(evento, client_mock)

        mock_registrar.assert_called_once_with(
            session_mock,
            camara=camara_mock,
            botella=None,
            tipo_movimiento="Ingreso",
            tecnico_nombre="Rider Fernández",
            slack_user_id="U0AUB6CRE4A",
            momento=None,
            thread_ts="2222.000222",
            canal_id="C_OTRO_CANAL",
        )

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
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False, inconsistente=False,
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
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False, inconsistente=False,
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
            tiene_baneo_activo=True, tiene_incidente_activo=True, tiene_ingreso_activo=False, inconsistente=False,
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
            session_mock,
            camara=camara_mock,
            botella=None,
            tecnico_nombre="Rider Fernández",
            momento=None,
            thread_ts="1234567890.000001",
            canal_id="C123",
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
            tiene_baneo_activo=True, tiene_incidente_activo=True, tiene_ingreso_activo=False, inconsistente=False,
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
            tecnico_nombre="Rider Fernández", slack_user_id="U0AUB6CRE4A", momento=None,
            thread_ts="1234567890.000001", canal_id="C123",
        )
        mock_intento.assert_not_called()


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
            tiene_incidente_activo=True,
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
            tiene_baneo_activo=False, tiene_incidente_activo=False, tiene_ingreso_activo=False, inconsistente=False,
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

    def test_get_camara_estado_contexto_lanza_excepcion_fail_open_no_bloquea(self) -> None:
        """Hallazgo real (I3, revisión final 2026-09-04): la función que reemplazó
        `_obtener_incidentes_activos_camara` (retirada, tenía su propio `try/except Exception:
        return []`) perdió ese fail-open — sin guard, un error de `get_camara_estado_contexto` (DB
        caída, lazy-load) se propagaba hasta el `except Exception` de `_handle_message`, que NO
        postea ninguna respuesta en Slack (peor que antes, que sí respondía ✅). Debe caer al mismo
        camino "no bloqueado, OK" que `contexto is None`, y la respuesta de Slack se debe postear
        igual."""
        from db.models.infra import CamaraEstado

        camara_mock = self._make_camara(12, "Cam Contexto Roto", CamaraEstado.LIBRE)
        listener = self._make_listener()
        client_mock = MagicMock()
        event = self._make_event(text="Cámara: Contexto Roto")

        with (
            patch.object(listener, "_get_config", return_value=("C123", True, [], False)),
            patch("modules.slack_baneo_notifier.listener.SessionLocal"),
            patch("modules.slack_baneo_notifier.listener.extraer_nombre_camara", return_value="Contexto Roto"),
            patch(
                "modules.slack_baneo_notifier.listener.buscar_camara_o_botella_cromo",
                return_value=_resultado_camara(camara_mock, "contexto roto"),
            ),
            patch(
                "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
                side_effect=RuntimeError("DB caída"),
            ),
        ):
            listener._handle_message(event, client_mock)

        # La respuesta se postea igual — nunca se propaga la excepción hasta silenciar el mensaje.
        client_mock.chat_postMessage.assert_called_once()
        texto = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
        self.assertIn("✅", texto)
        self.assertNotIn(":no_entry:", texto)
        self.assertNotIn("ATENCIÓN", texto)

    def test_evaluar_estado_acceso_camara_directo_ante_excepcion_no_bloquea(self) -> None:
        """Cobertura directa (sin pasar por `_handle_message`) de `_evaluar_estado_acceso_camara`:
        confirma explícitamente que el resultado tiene `bloqueado=False` cuando
        `get_camara_estado_contexto` lanza."""
        from db.models.infra import CamaraEstado

        camara_mock = self._make_camara(13, "Cam Directa Rota", CamaraEstado.LIBRE)
        listener = self._make_listener()
        session_mock = MagicMock()

        with patch(
            "modules.slack_baneo_notifier.listener.get_camara_estado_contexto",
            side_effect=RuntimeError("DB caída"),
        ):
            resultado = listener._evaluar_estado_acceso_camara(camara_mock, session_mock)

        self.assertFalse(resultado.bloqueado)
        self.assertIn("✅", resultado.texto)
