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
class Settings:
    infra: InfraSettings

    def __init__(self) -> None:
        self.infra = InfraSettings(
            sheet_id=getenv("INFRA_SHEET_ID"),
            sheet_name=getenv("INFRA_SHEET_NAME", "Camaras"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
