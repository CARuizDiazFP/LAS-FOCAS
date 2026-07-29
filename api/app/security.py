# Nombre de archivo: security.py
# Ubicación de archivo: api/app/security.py
# Descripción: Dependencias de seguridad para proteger la API core con API key

from __future__ import annotations

import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from core.config import get_secret

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_BEARER_AUTH = HTTPBearer(auto_error=False)


def _configured_api_key() -> str:
    return get_secret("api_key_v1", "LAS_FOCAS_API_KEY").strip()


async def require_api_key(
    bearer: HTTPAuthorizationCredentials | None = Security(_BEARER_AUTH),
    x_api_key: str | None = Security(_API_KEY_HEADER),
) -> None:
    """Valida la API key interna para endpoints sensibles."""

    expected = _configured_api_key()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key no configurada",
        )

    provided = ""
    if bearer and bearer.scheme.lower() == "bearer":
        provided = bearer.credentials.strip()
    elif x_api_key:
        provided = x_api_key.strip()

    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales requeridas",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Credenciales inválidas",
        )
