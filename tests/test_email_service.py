# Nombre de archivo: test_email_service.py
# Ubicación de archivo: tests/test_email_service.py
# Descripción: Tests unitarios para el EmailService, incluyendo la generación de EML.

import io
import unittest
from email import message_from_bytes
from unittest.mock import MagicMock

import pandas as pd

from core.services.email_service import EmailService
from db.models.infra import Camara, CamaraEstado, IncidenteBaneo


class TestEmailService(unittest.TestCase):
    """Tests para los métodos de EmailService."""

    def setUp(self):
        """Configura los mocks necesarios para los tests."""
        self.email_service = EmailService()

        # Mock de IncidenteBaneo
        self.mock_incidente = MagicMock(spec=IncidenteBaneo)
        self.mock_incidente.ticket_asociado = "INC-TEST-123"
        self.mock_incidente.motivo = "Test de baneo"
        self.mock_incidente.servicio_protegido_id = "SVC-PROT-001"

        # Mock de Camara con relaciones anidadas para la generación del Excel
        mock_camara_1 = MagicMock(spec=Camara)
        mock_camara_1.id = 1
        mock_camara_1.nombre = "Camara Test 1"
        mock_camara_1.direccion = "Calle Falsa 123"
        mock_camara_1.estado = CamaraEstado.BANEADA
        mock_camara_1.fontine_id = "F-001"
        mock_camara_1.latitud = -34.0
        mock_camara_1.longitud = -58.0

        mock_servicio_1 = MagicMock()
        mock_servicio_1.servicio_id = "SVC-A"
        mock_empalme_1 = MagicMock()
        mock_empalme_1.servicios = [mock_servicio_1]
        mock_camara_1.empalmes = [mock_empalme_1]

        self.mock_camaras_afectadas = [mock_camara_1]

    def test_generate_ban_eml_with_custom_data(self):
        """
        Prueba la generación de EML con asunto, destinatarios y cuerpo HTML personalizados.
        """
        # Datos de entrada
        subject = "Asunto de prueba personalizado"
        recipients = "test1@example.com,test2@example.com"
        html_body = "<h1>Cuerpo del correo de prueba</h1><p>Este es un test.</p>"

        # Generar el EML
        eml_stream = self.email_service.generate_ban_eml(
            incidente=self.mock_incidente,
            camaras_afectadas=self.mock_camaras_afectadas,
            html_body=html_body,
            subject=subject,
            recipients=recipients,
        )

        self.assertIsInstance(eml_stream, io.BytesIO)
        eml_content = eml_stream.getvalue()
        self.assertTrue(len(eml_content) > 0)

        # Parsear el EML y verificar su contenido
        msg = message_from_bytes(eml_content)

        # 1. Verificar cabeceras
        self.assertEqual(msg["Subject"], subject)
        self.assertEqual(msg["To"], recipients)
        self.assertEqual(msg["From"], "no-reply@las-focas.com")

        # 2. Verificar cuerpo y adjuntos
        self.assertTrue(msg.is_multipart())
        found_html = False
        found_excel = False

        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            if "attachment" in content_disposition:
                # Es el adjunto Excel
                found_excel = True
                filename = part.get_filename()
                self.assertEqual(filename, "Camaras_Baneadas_INC-TEST-123.xlsx")

                # 3. Verificar contenido del Excel
                excel_data = part.get_payload(decode=True)
                df = pd.read_excel(io.BytesIO(excel_data), engine="openpyxl")

                self.assertEqual(len(df), 1)
                self.assertEqual(df.iloc[0]["ID"], 1)
                self.assertEqual(df.iloc[0]["Nombre"], "Camara Test 1")
                self.assertEqual(df.iloc[0]["Servicios"], "SVC-A")

            elif content_type == "text/html":
                # Es el cuerpo HTML
                found_html = True
                body_payload = part.get_payload(decode=True).decode("utf-8")
                self.assertEqual(body_payload, html_body)

        self.assertTrue(found_html, "No se encontró la parte del cuerpo HTML en el EML.")
        self.assertTrue(found_excel, "No se encontró el adjunto Excel en el EML.")

    def test_generate_ban_eml_with_defaults(self):
        """
        Prueba la generación de EML usando el asunto y cuerpo de texto por defecto.
        """
        eml_stream = self.email_service.generate_ban_eml(
            incidente=self.mock_incidente,
            camaras_afectadas=self.mock_camaras_afectadas,
        )
        msg = message_from_bytes(eml_stream.getvalue())

        self.assertEqual(msg["Subject"], "AVISO DE BANEO - Ticket INC-TEST-123")
        self.assertIsNone(msg["To"])
        self.assertIn("Se informa baneo de cámaras", msg.get_payload()[0].get_payload())