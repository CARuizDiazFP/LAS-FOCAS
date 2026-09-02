# Nombre de archivo: config.py
# Ubicación de archivo: core/services/prov/config.py
# Descripción: Configuración desde entorno/secrets para el cliente de la API interna PROV, con validación al arranque

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from core.config import get_secret

_TIMEOUT_DEFAULT = 30.0
_RATE_LIMIT_DEFAULT = 5.0


class ProvConfigError(RuntimeError):
    """Configuración de PROV incompleta o inválida."""


@dataclass(slots=True)
class ProvConfig:
    """Configuración validada de acceso a la API PROV (`API_Contexto_Servicio`)."""

    base_url: str
    user: str
    password: str
    timeout: float
    rate_limit_per_second: float


def _construir_config() -> ProvConfig:
    base_url = os.getenv("PROV_BASE_URL", "").strip()
    user = get_secret("api_prov_user_v1", "PROV_USER").strip()
    password = get_secret("api_prov_pass_v1", "PROV_PASSWORD").strip()

    faltantes = [
        nombre
        for nombre, valor in (
            ("PROV_BASE_URL", base_url),
            ("api_prov_user_v1 (o PROV_USER)", user),
            ("api_prov_pass_v1 (o PROV_PASSWORD)", password),
        )
        if not valor
    ]
    if faltantes:
        raise ProvConfigError("Configuración de PROV incompleta. Definir: " + ", ".join(faltantes))

    try:
        timeout = float(os.getenv("PROV_TIMEOUT", str(_TIMEOUT_DEFAULT)))
    except ValueError as exc:
        raise ProvConfigError("PROV_TIMEOUT debe ser numérico") from exc

    try:
        rate_limit_per_second = float(os.getenv("PROV_RATE_LIMIT_PER_SECOND", str(_RATE_LIMIT_DEFAULT)))
    except ValueError as exc:
        raise ProvConfigError("PROV_RATE_LIMIT_PER_SECOND debe ser numérico") from exc
    if rate_limit_per_second <= 0:
        raise ProvConfigError("PROV_RATE_LIMIT_PER_SECOND debe ser mayor a 0")

    return ProvConfig(
        base_url=base_url,
        user=user,
        password=password,
        timeout=timeout,
        rate_limit_per_second=rate_limit_per_second,
    )


@lru_cache(maxsize=1)
def get_prov_config() -> ProvConfig:
    """Lee y valida la configuración de PROV desde variables de entorno/secrets (cacheada)."""
    return _construir_config()


__all__ = ["ProvConfig", "ProvConfigError", "get_prov_config"]
