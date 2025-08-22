# Nombre de archivo: test_email_client.py
# Ubicación de archivo: tests/test_email_client.py
# Descripción: Pruebas para el cliente de Email

from email.message import EmailMessage
import smtplib

from integrations.email import EmailClient


class DummySMTP:
    def __init__(self, *args, **kwargs) -> None:
        self.sent_message: EmailMessage | None = None
        self.started_tls = False
        self.logged_in = False

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.logged_in = True
        self.user = user
        self.password = password

    def send_message(self, message: EmailMessage) -> None:
        self.sent_message = message

    def __enter__(self) -> "DummySMTP":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass


def test_send_mail(monkeypatch) -> None:
    """Verifica que el cliente envía correos con TLS y autenticación."""
    dummy = DummySMTP()

    def fake_smtp(host: str, port: int, timeout: int = 0) -> DummySMTP:
        assert host == "smtp.test"
        assert port == 587
        return dummy

    monkeypatch.setattr(smtplib, "SMTP", fake_smtp)

    client = EmailClient(
        host="smtp.test",
        port=587,
        user="user",
        password="pass",
        sender="sender@test",
    )
    client.send_mail("dest@test", "Asunto", "Cuerpo")

    assert dummy.started_tls is True
    assert dummy.logged_in is True
    assert dummy.sent_message is not None
    assert dummy.sent_message["To"] == "dest@test"
