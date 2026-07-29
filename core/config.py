# Nombre de archivo: config.py
# Ubicación de archivo: core/config.py
# Descripción: Configuración centralizada (entorno) para servicios internos LAS-FOCAS

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def get_secret(secret_name: str, env_var: str | None = None, default: str = "") -> str:
    """Lee un secreto Docker y cae a variable de entorno durante la transición."""
    secret_path = Path("/run/secrets") / secret_name
    try:
        return secret_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return os.getenv(env_var or secret_name, default)
    except OSError:
        return os.getenv(env_var or secret_name, default)


@dataclass(slots=True)
class InfraSettings:
    sheet_id: str | None
    sheet_name: str


@dataclass(slots=True)
class SmtpSettings:
    """Configuración SMTP para envío de correos."""

    host: str
    port: int
    user: str
    password: str
    from_email: str
    from_name: str
    use_tls: bool
    enabled: bool
    timeout: int


@dataclass(slots=True)
class SlackSettings:
    """Configuración Slack para notificaciones automatizadas."""

    bot_token: str
    app_token: str
    enabled: bool


@dataclass(slots=True)
class Settings:
    infra: InfraSettings
    smtp: SmtpSettings
    slack: SlackSettings

    def __init__(self) -> None:
        self.infra = InfraSettings(
            sheet_id=os.getenv("INFRA_SHEET_ID"),
            sheet_name=os.getenv("INFRA_SHEET_NAME", "Camaras"),
        )
        smtp_host = os.getenv("SMTP_HOST", "")
        smtp_user = os.getenv("SMTP_USER", "")
        slack_bot_token = get_secret("slack_bot_token_v1", "SLACK_BOT_TOKEN")
        self.smtp = SmtpSettings(
            host=smtp_host,
            port=int(os.getenv("SMTP_PORT", "587")),
            user=smtp_user,
            password=get_secret("smtp_password_v1", "SMTP_PASS"),
            from_email=os.getenv("SMTP_FROM_EMAIL", smtp_user),
            from_name=os.getenv("SMTP_FROM_NAME", "LAS-FOCAS Notificaciones"),
            use_tls=os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes"),
            enabled=bool(smtp_host),
            timeout=int(os.getenv("SMTP_TIMEOUT", "15")),
        )
        self.slack = SlackSettings(
            bot_token=slack_bot_token,
            app_token=get_secret("slack_app_token_v1", "SLACK_APP_TOKEN"),
            enabled=bool(slack_bot_token),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
