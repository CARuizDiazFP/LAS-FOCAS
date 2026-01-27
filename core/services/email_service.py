# Nombre de archivo: email_service.py
# Ubicación de archivo: core/services/email_service.py
# Descripción: Servicio de envío de correos electrónicos con soporte para adjuntos

from __future__ import annotations

import io
import logging
import smtplib
from dataclasses import dataclass
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import List, Optional, Tuple

import pandas as pd

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
                    part = MIMEApplication(attachment.content)
                    part.add_header(
                        "Content-Disposition",
                        "attachment",
                        filename=attachment.filename,
                    )
                    part.add_header("Content-Type", attachment.mime_type)
                    msg.attach(part)

            # Enviar
            all_recipients = to + (cc or [])

            with smtplib.SMTP(self.settings.host, self.settings.port) as server:
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
            logger.error("action=send_email error=recipients_refused detail=%s", exc)
            return EmailResult(
                success=False,
                message="Destinatarios rechazados",
                error=f"El servidor rechazó los destinatarios: {exc}",
            )
        except smtplib.SMTPException as exc:
            logger.error("action=send_email error=smtp_error detail=%s", exc)
            return EmailResult(
                success=False,
                message="Error al enviar correo",
                error=str(exc),
            )
        except Exception as exc:
            logger.exception("action=send_email error=unexpected detail=%s", exc)
            return EmailResult(
                success=False,
                message="Error inesperado al enviar correo",
                error=str(exc),
            )

    # ------------------------------------------------------------------ #
    # Generación de EML para baneo
    # ------------------------------------------------------------------ #
    def generate_ban_eml(
        self,
        incidente,
        camaras_afectadas: List,
        html_body: str | None = None,
        subject: str | None = None,
        recipients: str | None = None,
    ) -> io.BytesIO:
        """Genera un archivo EML con resumen de baneo usando la lista explícita de cámaras."""

        # Asunto y remitente
        from_email = self.settings.from_email or "no-reply@las-focas.com"
        from_name = self.settings.from_name or "LAS-FOCAS"
        eml_subject = subject or f"AVISO DE BANEO - Ticket {incidente.ticket_asociado or incidente.id}"

        # Cuerpo HTML por defecto si no viene uno custom
        if not html_body:
            ticket = incidente.ticket_asociado or incidente.id
            html_body = (
                f"<p>Se informa baneo de cámaras para el ticket <strong>{ticket}</strong>.</p>"
                "<p>Se adjunta el detalle de cámaras afectadas.</p>"
            )

        # Construir el mensaje
        msg = MIMEMultipart("mixed")
        msg["From"] = formataddr((from_name, from_email))
        if recipients:
            msg["To"] = recipients
        msg["Subject"] = eml_subject

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # Excel con cámaras afectadas
        if camaras_afectadas:
            rows = []
            for cam in camaras_afectadas:
                servicios_ids = []
                try:
                    for emp in getattr(cam, "empalmes", []) or []:
                        for svc in getattr(emp, "servicios", []) or []:
                            sid = getattr(svc, "servicio_id", None)
                            if sid and sid not in servicios_ids:
                                servicios_ids.append(sid)
                except Exception:
                    pass

                rows.append(
                    {
                        "ID": getattr(cam, "id", None),
                        "Nombre": getattr(cam, "nombre", None),
                        "Dirección": getattr(cam, "direccion", None),
                        "Estado": getattr(getattr(cam, "estado", None), "value", getattr(cam, "estado", None)),
                        "Servicios": ", ".join(servicios_ids),
                        "Latitud": getattr(cam, "latitud", None),
                        "Longitud": getattr(cam, "longitud", None),
                    }
                )

            if rows:
                df = pd.DataFrame(rows)
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    df.to_excel(writer, sheet_name="Camaras_Baneadas", index=False)
                buffer.seek(0)

                excel_part = MIMEApplication(buffer.getvalue())
                filename = f"Camaras_Baneadas_{incidente.ticket_asociado or incidente.id}.xlsx"
                excel_part.add_header("Content-Disposition", "attachment", filename=filename)
                excel_part.add_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                msg.attach(excel_part)

        # Serializar a bytes
        eml_bytes = msg.as_bytes()
        return io.BytesIO(eml_bytes)


# Singleton para uso global
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """Obtiene la instancia singleton del servicio de email."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
