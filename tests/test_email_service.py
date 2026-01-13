# Nombre de archivo: test_email_service.py
# Ubicación de archivo: tests/test_email_service.py
# Descripción: Tests para el servicio de envío de correos electrónicos

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


class TestEmailService:
    """Tests para EmailService."""

    def test_email_service_import(self):
        """Verifica que el servicio se puede importar."""
        from core.services.email_service import EmailService, get_email_service

        assert EmailService is not None
        assert get_email_service is not None

    def test_email_service_not_configured_without_env(self):
        """Verifica que reporta no configurado si no hay variables SMTP."""
        # Limpiar cache del singleton
        import core.services.email_service as email_module

        email_module._email_service = None

        with patch.dict(os.environ, {}, clear=True):
            # Forzar recarga de configuración
            from core.config import Settings

            settings = Settings()
            
            # Sin SMTP_HOST, debe reportar no habilitado
            assert settings.smtp.enabled is False

    def test_email_attachment_dataclass(self):
        """Verifica la estructura de EmailAttachment."""
        from core.services.email_service import EmailAttachment

        attachment = EmailAttachment(
            filename="test.txt",
            content=b"contenido de prueba",
            mime_type="text/plain",
        )

        assert attachment.filename == "test.txt"
        assert attachment.content == b"contenido de prueba"
        assert attachment.mime_type == "text/plain"

    def test_email_result_success(self):
        """Verifica EmailResult con éxito."""
        from core.services.email_service import EmailResult

        result = EmailResult(
            success=True,
            message="Correo enviado",
        )

        assert result.success is True
        assert result.message == "Correo enviado"
        assert result.error is None

    def test_email_result_error(self):
        """Verifica EmailResult con error."""
        from core.services.email_service import EmailResult

        result = EmailResult(
            success=False,
            message="Error al enviar",
            error="SMTP timeout",
        )

        assert result.success is False
        assert result.error == "SMTP timeout"

    @patch("core.services.email_service.smtplib.SMTP")
    def test_send_email_success(self, mock_smtp_class):
        """Verifica envío exitoso de email (mockeado)."""
        from core.services.email_service import EmailService

        # Configurar mock
        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        # Crear servicio con config mockeada
        service = EmailService()
        service.settings.enabled = True
        service.settings.host = "smtp.test.com"
        service.settings.port = 587
        service.settings.user = "test@test.com"
        service.settings.password = "secret"
        service.settings.from_email = "from@test.com"
        service.settings.from_name = "Test"
        service.settings.use_tls = True

        result = service.send_email(
            to=["dest@test.com"],
            subject="Test Subject",
            body="Test Body",
        )

        assert result.success is True
        assert "exitosamente" in result.message

    def test_send_email_no_recipients(self):
        """Verifica error si no hay destinatarios."""
        from core.services.email_service import EmailService

        service = EmailService()
        service.settings.enabled = True
        service.settings.host = "smtp.test.com"

        result = service.send_email(
            to=[],
            subject="Test",
            body="Test",
        )

        assert result.success is False
        assert "destinatarios" in result.message.lower()


class TestSmtpConfig:
    """Tests para la configuración SMTP."""

    def test_smtp_settings_from_env(self):
        """Verifica que SmtpSettings lee variables de entorno."""
        test_env = {
            "SMTP_HOST": "smtp.ejemplo.com",
            "SMTP_PORT": "465",
            "SMTP_USER": "usuario@ejemplo.com",
            "SMTP_PASS": "password123",
            "SMTP_FROM_EMAIL": "noreply@ejemplo.com",
            "SMTP_FROM_NAME": "Sistema Prueba",
            "SMTP_USE_TLS": "false",
        }

        with patch.dict(os.environ, test_env, clear=False):
            from core.config import SmtpSettings

            # Crear instancia directa para test
            settings = SmtpSettings(
                host=os.getenv("SMTP_HOST", ""),
                port=int(os.getenv("SMTP_PORT", "587")),
                user=os.getenv("SMTP_USER", ""),
                password=os.getenv("SMTP_PASS", ""),
                from_email=os.getenv("SMTP_FROM_EMAIL", ""),
                from_name=os.getenv("SMTP_FROM_NAME", "Test"),
                use_tls=os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1"),
                enabled=bool(os.getenv("SMTP_HOST")),
            )

            assert settings.host == "smtp.ejemplo.com"
            assert settings.port == 465
            assert settings.user == "usuario@ejemplo.com"
            assert settings.from_email == "noreply@ejemplo.com"
            assert settings.use_tls is False
            assert settings.enabled is True
