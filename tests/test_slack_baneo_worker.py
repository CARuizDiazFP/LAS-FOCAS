# Nombre de archivo: test_slack_baneo_worker.py
# Ubicación de archivo: tests/test_slack_baneo_worker.py
# Descripción: Tests unitarios para el worker de notificaciones de baneos a Slack

from __future__ import annotations

import io
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

from db.models.infra import Camara, CamaraEstado
from db.models.servicios import ConfigServicios


class TestGenerarExcelBaneadas(unittest.TestCase):
    """Tests para la generación del Excel de cámaras baneadas."""

    def _make_camara(self, id_: int, nombre: str, fontine_id: str | None = None) -> MagicMock:
        cam = MagicMock(spec=Camara)
        cam.id = id_
        cam.fontine_id = fontine_id
        cam.nombre = nombre
        cam.direccion = f"Calle {nombre}"
        cam.latitud = -34.0 + id_ * 0.01
        cam.longitud = -58.0 + id_ * 0.01
        cam.estado = CamaraEstado.BANEADA
        cam.last_update = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)
        return cam

    def test_genera_excel_con_camaras(self) -> None:
        from modules.slack_baneo_notifier.notifier import generar_excel_baneadas

        mock_session = MagicMock()
        camaras = [self._make_camara(1, "Cam A", "F-001"), self._make_camara(2, "Cam B")]
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = camaras

        cantidad, buf, nombre = generar_excel_baneadas(mock_session)

        self.assertEqual(cantidad, 2)
        self.assertIsNotNone(buf)
        self.assertIsInstance(buf, io.BytesIO)
        self.assertTrue(nombre.startswith("camaras_baneadas_"))
        self.assertTrue(nombre.endswith(".xlsx"))
        # Verificar que el Excel tiene contenido
        self.assertGreater(buf.tell() or len(buf.getvalue()), 0)

    def test_devuelve_none_sin_camaras(self) -> None:
        from modules.slack_baneo_notifier.notifier import generar_excel_baneadas

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        cantidad, buf, nombre = generar_excel_baneadas(mock_session)

        self.assertEqual(cantidad, 0)
        self.assertIsNone(buf)
        self.assertTrue(nombre.endswith(".xlsx"))


class TestEnviarReporteBaneos(unittest.TestCase):
    """Tests para el envío de reportes a Slack."""

    @patch("modules.slack_baneo_notifier.notifier.WebClient")
    @patch("modules.slack_baneo_notifier.notifier.generar_excel_baneadas")
    def test_envia_mensaje_sin_camaras(
        self, mock_generar: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        from modules.slack_baneo_notifier.notifier import enviar_reporte_baneos

        mock_generar.return_value = (0, None, "camaras_baneadas_20260417_1200.xlsx")
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_session = MagicMock()
        error = enviar_reporte_baneos(["#test"], "xoxb-test-token", mock_session)

        self.assertIsNone(error)
        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args
        self.assertEqual(call_kwargs.kwargs.get("channel") or call_kwargs[1].get("channel"), "#test")

    @patch("modules.slack_baneo_notifier.notifier.WebClient")
    @patch("modules.slack_baneo_notifier.notifier.generar_excel_baneadas")
    def test_envia_excel_con_camaras(
        self, mock_generar: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        from modules.slack_baneo_notifier.notifier import enviar_reporte_baneos

        excel_buf = io.BytesIO(b"fake-excel-content")
        mock_generar.return_value = (3, excel_buf, "camaras_baneadas_20260417_1200.xlsx")
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_session = MagicMock()
        error = enviar_reporte_baneos(["#canal1", "#canal2"], "xoxb-test-token", mock_session)

        self.assertIsNone(error)
        self.assertEqual(mock_client.files_upload_v2.call_count, 2)

    @patch("modules.slack_baneo_notifier.notifier.WebClient")
    @patch("modules.slack_baneo_notifier.notifier.generar_excel_baneadas")
    def test_sin_token_devuelve_error(
        self, mock_generar: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        from modules.slack_baneo_notifier.notifier import enviar_reporte_baneos

        mock_session = MagicMock()
        error = enviar_reporte_baneos(["#test"], "", mock_session)

        self.assertIsNotNone(error)
        self.assertIn("SLACK_BOT_TOKEN", error)
        mock_client_cls.assert_not_called()

    @patch("modules.slack_baneo_notifier.notifier.WebClient")
    @patch("modules.slack_baneo_notifier.notifier.generar_excel_baneadas")
    def test_error_slack_no_crashea(
        self, mock_generar: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        from slack_sdk.errors import SlackApiError
        from modules.slack_baneo_notifier.notifier import enviar_reporte_baneos

        mock_generar.return_value = (0, None, "camaras_baneadas_20260417_1200.xlsx")
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.__getitem__ = lambda self, key: {"error": "channel_not_found"}[key]
        mock_client.chat_postMessage.side_effect = SlackApiError(
            message="channel_not_found",
            response=mock_response,
        )

        mock_session = MagicMock()
        error = enviar_reporte_baneos(["#inexistente"], "xoxb-test-token", mock_session)

        self.assertIsNotNone(error)
        self.assertIn("channel_not_found", error)


class TestConfigServiciosModel(unittest.TestCase):
    """Tests para el modelo ConfigServicios."""

    def test_modelo_tiene_campos_requeridos(self) -> None:
        config = ConfigServicios()
        config.nombre_servicio = "test_service"
        config.intervalo_horas = 6
        config.slack_channels = "#test"
        config.activo = True

        self.assertEqual(config.nombre_servicio, "test_service")
        self.assertEqual(config.intervalo_horas, 6)
        self.assertEqual(config.slack_channels, "#test")
        self.assertTrue(config.activo)
        self.assertIsNone(config.ultima_ejecucion)
        self.assertIsNone(config.ultimo_error)


class TestWorkerConfig(unittest.TestCase):
    """Tests para las constantes del worker."""

    def test_constantes_definidas(self) -> None:
        from modules.slack_baneo_notifier.config import (
            NOMBRE_SERVICIO,
            INTERVALO_HORAS_DEFAULT,
            HEALTH_PORT,
            JOB_ID,
        )

        self.assertEqual(NOMBRE_SERVICIO, "slack_baneo_notifier")
        self.assertEqual(INTERVALO_HORAS_DEFAULT, 4)
        self.assertEqual(HEALTH_PORT, 8095)
        self.assertIsInstance(JOB_ID, str)


class TestWorkerHotReload(unittest.TestCase):
    """Tests para la recarga en caliente de configuración del worker."""

    @patch("modules.slack_baneo_notifier.worker._leer_config")
    def test_sincroniza_intervalo_y_reprograma_scheduler(self, mock_leer_config: MagicMock) -> None:
        from modules.slack_baneo_notifier import worker

        config = ConfigServicios()
        config.intervalo_horas = 24
        config.activo = True
        mock_leer_config.return_value = config

        scheduler = MagicMock()
        worker._worker_status["intervalo_horas"] = 4

        resultado = worker._sincronizar_configuracion_worker(scheduler)

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["intervalo_horas"], 24)
        self.assertEqual(worker._worker_status["intervalo_horas"], 24)
        scheduler.reschedule_job.assert_called_once()
        trigger = scheduler.reschedule_job.call_args.kwargs["trigger"]
        self.assertEqual(trigger.interval.total_seconds(), 24 * 3600)

    @patch("modules.slack_baneo_notifier.worker._leer_config")
    def test_sincroniza_estado_sin_scheduler(self, mock_leer_config: MagicMock) -> None:
        from modules.slack_baneo_notifier import worker

        config = ConfigServicios()
        config.intervalo_horas = 12
        config.activo = False
        mock_leer_config.return_value = config

        worker._worker_status["intervalo_horas"] = 4
        resultado = worker._sincronizar_configuracion_worker(None)

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["intervalo_horas"], 12)
        self.assertFalse(resultado["activo"])


if __name__ == "__main__":
    unittest.main()
