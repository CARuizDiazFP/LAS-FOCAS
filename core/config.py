# Nombre de archivo: config.py
# Ubicación de archivo: core/config.py
# Descripción: Configuración centralizada (entorno) para servicios internos LAS-FOCAS

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from os import getenv


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


@dataclass(slots=True)
class Settings:
    infra: InfraSettings
    smtp: SmtpSettings

    def __init__(self) -> None:
        self.infra = InfraSettings(
            sheet_id=getenv("INFRA_SHEET_ID"),
            sheet_name=getenv("INFRA_SHEET_NAME", "Camaras"),
        )
        self.smtp = SmtpSettings(
            host=getenv("SMTP_HOST", ""),
            port=int(getenv("SMTP_PORT", "587")),
            user=getenv("SMTP_USER", ""),
            password=getenv("SMTP_PASS", ""),
            from_email=getenv("SMTP_FROM_EMAIL", getenv("SMTP_USER", "")),
            from_name=getenv("SMTP_FROM_NAME", "LAS-FOCAS Notificaciones"),
            use_tls=getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes"),
            enabled=bool(getenv("SMTP_HOST")),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
