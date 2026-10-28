# Nombre de archivo: email_service.py
# Ubicación de archivo: core/services/email_service.py
# Descripción: Servicio de envío de correos electrónicos con soporte para adjuntos

from __future__ import annotations

import logging
import secrets
import smtplib
from dataclasses import dataclass
from email import encoders
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import List, Optional


from core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class EmailAttachment:
    """Representa un archivo adjunto."""

    filename: str
    content: bytes
    mime_type: str = "application/octet-stream"


@dataclass
class EmailResult:
    """Resultado del envío de correo."""

    success: bool
    message: str
    error: Optional[str] = None


def parte_mime_adjunto(adjunto: EmailAttachment) -> MIMEBase:
    """Arma la parte MIME de un adjunto con UN solo `Content-Type` (B6).

    Antes se creaba `MIMEApplication(datos)` y se le agregaba `Content-Type` con `add_header`, lo que
    dejaba dos cabeceras y los clientes tomaban `application/octet-stream`. Acá el tipo sale del
    constructor: `MIMEText` para `text/*`, `MIMEApplication` para `application/*` y `MIMEBase` con
    base64 para el resto.
    """
    tipo = adjunto.mime_type.split(";", 1)[0].strip().lower()
    principal, _, subtipo = tipo.partition("/")
    if not principal or not subtipo:
        principal, subtipo = "application", "octet-stream"
    if principal == "text":
        parte: MIMEBase = MIMEText(adjunto.content.decode("utf-8", errors="replace"), subtipo, "utf-8")
    elif principal == "application":
        parte = MIMEApplication(adjunto.content, _subtype=subtipo)
    else:
        parte = MIMEBase(principal, subtipo)
        parte.set_payload(adjunto.content)
        encoders.encode_base64(parte)
    parte.add_header("Content-Disposition", "attachment", filename=adjunto.filename)
    return parte


class EmailService:
    """Servicio para enviar correos electrónicos."""

    def __init__(self) -> None:
        self.settings = get_settings().smtp

    def is_configured(self) -> bool:
        """Verifica si el servicio de email está configurado."""
        return self.settings.enabled and bool(self.settings.host)

    def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        attachments: Optional[List[EmailAttachment]] = None,
        html_body: Optional[str] = None,
    ) -> EmailResult:
        """
        Envía un correo electrónico.

        Args:
            to: Lista de destinatarios principales
            subject: Asunto del correo
            body: Cuerpo del correo en texto plano
            cc: Lista de destinatarios en copia (opcional)
            attachments: Lista de adjuntos (opcional)
            html_body: Cuerpo del correo en HTML (opcional, alternativa a body)

        Returns:
            EmailResult con el resultado del envío
        """
        if not self.is_configured():
            logger.error("action=send_email error=smtp_not_configured")
            return EmailResult(
                success=False,
                message="Servicio de email no configurado",
                error="SMTP_HOST no está definido en las variables de entorno",
            )

        if not to:
            return EmailResult(
                success=False,
                message="No se especificaron destinatarios",
                error="Lista de destinatarios vacía",
            )

        try:
            # Crear mensaje
            msg = MIMEMultipart("mixed")
            msg["From"] = formataddr((self.settings.from_name, self.settings.from_email))
            msg["To"] = ", ".join(to)
            msg["Subject"] = subject

            if cc:
                msg["Cc"] = ", ".join(cc)

            # Cuerpo del mensaje (texto plano y/o HTML)
            if html_body:
                # Multipart alternative para texto plano y HTML
                alt_part = MIMEMultipart("alternative")
                alt_part.attach(MIMEText(body, "plain", "utf-8"))
                alt_part.attach(MIMEText(html_body, "html", "utf-8"))
                msg.attach(alt_part)
            else:
                msg.attach(MIMEText(body, "plain", "utf-8"))

            # Agregar adjuntos
            if attachments:
                for attachment in attachments:
                    msg.attach(parte_mime_adjunto(attachment))

            # Enviar
            all_recipients = to + (cc or [])

            with smtplib.SMTP(self.settings.host, self.settings.port, timeout=self.settings.timeout) as server:
                if self.settings.use_tls:
                    server.starttls()
                
                if self.settings.user and self.settings.password:
                    server.login(self.settings.user, self.settings.password)

                server.sendmail(
                    self.settings.from_email,
                    all_recipients,
                    msg.as_string(),
                )

            logger.info(
                "action=send_email to=%s cc=%s subject=%s attachments=%d success=true",
                len(to),
                len(cc or []),
                subject[:50],
                len(attachments or []),
            )

            return EmailResult(
                success=True,
                message=f"Correo enviado exitosamente a {len(all_recipients)} destinatario(s)",
            )

        except smtplib.SMTPAuthenticationError as exc:
            logger.error("action=send_email error=auth_failed detail=%s", exc)
            return EmailResult(
                success=False,
                message="Error de autenticación SMTP",
                error="Credenciales de correo inválidas",
            )
        except smtplib.SMTPRecipientsRefused as exc:
            ref = secrets.token_hex(4)
            logger.error("action=send_email error=recipients_refused detail=%s ref=%s", exc, ref)
            return EmailResult(
                success=False,
                message="Destinatarios rechazados",
                error=f"El servidor rechazó los destinatarios (ref {ref})",
            )
        except smtplib.SMTPException as exc:
            ref = secrets.token_hex(4)
            logger.error("action=send_email error=smtp_error detail=%s ref=%s", exc, ref)
            return EmailResult(
                success=False,
                message="Error al enviar correo",
                error=f"No se pudo enviar el email (ref {ref})",
            )
        except Exception as exc:
            ref = secrets.token_hex(4)
            logger.exception("action=send_email error=unexpected detail=%s ref=%s", exc, ref)
            return EmailResult(
                success=False,
                message="Error inesperado al enviar correo",
                error=f"No se pudo enviar el email (ref {ref})",
            )


# Singleton para uso global
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """Obtiene la instancia singleton del servicio de email."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
