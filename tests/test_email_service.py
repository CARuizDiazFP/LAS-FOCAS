# Nombre de archivo: test_email_service.py
# Ubicación de archivo: tests/test_email_service.py
# Descripción: Tests unitarios para el EmailService, errores de envío SMTP sin texto interno.

import logging
import re
import smtplib

import pytest

from core.services.email_service import EmailService

_SECRETO_SMTP = "535 relay interno smtp-int.metrotel.local user=svc_mail"


@pytest.mark.parametrize(
    "exc",
    [
        smtplib.SMTPException(_SECRETO_SMTP),
        smtplib.SMTPRecipientsRefused({"a@b.c": (550, _SECRETO_SMTP.encode())}),
        RuntimeError(_SECRETO_SMTP),
    ],
)
def test_send_email_error_sin_texto_interno_y_con_ref_en_log(monkeypatch, caplog, exc):
    servicio = EmailService()
    monkeypatch.setattr(EmailService, "is_configured", lambda self: True)

    def _smtp_roto(*a, **k):
        raise exc

    monkeypatch.setattr(smtplib, "SMTP", _smtp_roto)
    with caplog.at_level(logging.ERROR):
        res = servicio.send_email(["a@b.c"], "s", "b")

    assert res.success is False
    assert "smtp-int" not in (res.error or "") and "svc_mail" not in (res.error or "")
    ref = re.search(r"ref ([0-9a-f]{8})", res.error).group(1)
    assert f"ref={ref}" in caplog.text
