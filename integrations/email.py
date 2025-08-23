# Nombre de archivo: email.py
# Ubicación de archivo: integrations/email.py
# Descripción: Cliente SMTP para enviar correos electrónicos

import logging
import os
import smtplib
from email.message import EmailMessage
from core import get_secret

logger = logging.getLogger(__name__)


class EmailClient:
    """Envía correos mediante un servidor SMTP."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        sender: str | None = None,
        use_tls: bool = True,
    ) -> None:
        self.host = host or get_secret("SMTP_HOST") or ""
        self.port = port or int(os.getenv("SMTP_PORT", "587"))
        self.user = user or get_secret("SMTP_USER") or ""
        self.password = password or get_secret("SMTP_PASSWORD") or ""
        self.sender = sender or get_secret("SMTP_FROM") or self.user
        self.use_tls = use_tls

    def send_mail(self, to: str, subject: str, body: str) -> None:
        """Envía un correo electrónico."""
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        logger.info("service=email action=send_mail to=%s", to)

        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.user and self.password:
                smtp.login(self.user, self.password)
            smtp.send_message(message)
