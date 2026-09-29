# Nombre de archivo: oauth.py
# Ubicación de archivo: api/app/oauth.py
# Descripción: OAuth2 client_credentials (M2M) de la API v1: emisión/validación de JWT y dependencia require_oauth_token

"""Autenticación máquina-a-máquina para integraciones interáreas (`/api/v1/*`).

LAS-FOCAS emite sus propios tokens (no hay IdP externo): un área se autentica con
`client_id`/`client_secret` contra `POST /api/v1/oauth/token` y recibe un JWT HS256 de 7 días que
presenta como `Authorization: Bearer` en los endpoints v1.

Es un mecanismo **separado** de `api/app/security.py::require_api_key`: la API key interna no sirve
en `/api/v1` y el JWT no sirve en las rutas internas. Las dos viajan como `Bearer`, así que mezclarlas
en una misma dependencia obligaría a adivinar qué es cada credencial.

Reglas de seguridad que este módulo garantiza:
- Algoritmo fijo `HS256` al decodificar (un token con `alg=none` o con otro algoritmo se rechaza).
- `aud`, `iss`, `exp`, `iat` y `sub` obligatorios.
- Secreto de firma ausente o corto (< 32 bytes) → 503, falla cerrado.
- El cliente se revalida contra la base en cada request: desactivarlo corta sus tokens vigentes.
- Nunca se loguea el `client_secret`, el header `Authorization` ni el token.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Awaitable, Callable, Optional, Sequence

import jwt
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_secret
from core.password import hash_password, verify_password
from db.models.api_clients import ApiClient
from db.session import get_async_db

logger = logging.getLogger(__name__)

ALGORITMO = "HS256"
ISSUER = "las-focas"
AUDIENCE = "las-focas-api-v1"
TTL_DEFAULT_SEGUNDOS = 7 * 24 * 3600
LARGO_MINIMO_SECRETO = 32

SCOPE_SERVICIOS_BOTELLAS = "servicios:botellas:read"

_BEARER = HTTPBearer(auto_error=False)


class OAuthNoConfigurado(RuntimeError):
    """El secreto de firma no está disponible o es demasiado corto."""


class TokenInvalido(ValueError):
    """Token ausente, mal formado, vencido o con firma/claims inválidos."""


@dataclass(frozen=True)
class ClienteAutenticado:
    """Cliente M2M ya validado, expuesto en `request.state.oauth_client`."""

    client_id: str
    nombre_area: str
    scopes: tuple[str, ...]


def _secreto_firma() -> str:
    secreto = get_secret("oauth_jwt_secret_v1", "OAUTH_JWT_SECRET").strip()
    if len(secreto.encode("utf-8")) < LARGO_MINIMO_SECRETO:
        raise OAuthNoConfigurado("oauth_jwt_secret_v1 ausente o menor a 32 bytes")
    return secreto


def ttl_token_segundos() -> int:
    """TTL del access token. 7 días por defecto, ajustable con `OAUTH_TOKEN_TTL_SECONDS`."""

    crudo = os.getenv("OAUTH_TOKEN_TTL_SECONDS", "").strip()
    if not crudo:
        return TTL_DEFAULT_SEGUNDOS
    try:
        valor = int(crudo)
    except ValueError:
        logger.warning("action=oauth_config evento=ttl_invalido valor=%r usando=%s", crudo, TTL_DEFAULT_SEGUNDOS)
        return TTL_DEFAULT_SEGUNDOS
    if valor <= 0:
        logger.warning("action=oauth_config evento=ttl_no_positivo valor=%s usando=%s", valor, TTL_DEFAULT_SEGUNDOS)
        return TTL_DEFAULT_SEGUNDOS
    return valor


def emitir_token(
    client_id: str,
    scopes: Sequence[str],
    *,
    ahora: Optional[datetime] = None,
    ttl_segundos: Optional[int] = None,
) -> tuple[str, int]:
    """Firma un access token para `client_id`. Devuelve `(token, expires_in)`."""

    emitido = ahora or datetime.now(timezone.utc)
    ttl = ttl_segundos if ttl_segundos is not None else ttl_token_segundos()
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": client_id,
        "scope": " ".join(scopes),
        "iat": int(emitido.timestamp()),
        "exp": int((emitido + timedelta(seconds=ttl)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, _secreto_firma(), algorithm=ALGORITMO), ttl


def decodificar_token(token: str) -> dict[str, Any]:
    """Valida firma, algoritmo, vigencia y claims. Lanza `TokenInvalido` ante cualquier falla."""

    secreto = _secreto_firma()
    try:
        claims = jwt.decode(
            token,
            secreto,
            algorithms=[ALGORITMO],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenInvalido("token vencido") from exc
    except jwt.PyJWTError as exc:
        raise TokenInvalido("token inválido") from exc
    if not isinstance(claims.get("sub"), str) or not isinstance(claims.get("scope", ""), str):
        raise TokenInvalido("claims con tipo inválido")
    return claims


@lru_cache(maxsize=1)
def _hash_señuelo() -> str:
    """Hash descartable para igualar el costo de bcrypt cuando el `client_id` no existe."""

    return hash_password(secrets.token_urlsafe(32))


async def autenticar_cliente(session: AsyncSession, client_id: str, client_secret: str) -> Optional[ApiClient]:
    """Devuelve el cliente si las credenciales son válidas y está activo; si no, `None`.

    Siempre ejecuta un bcrypt (contra el hash real o contra un señuelo) para que el tiempo de
    respuesta no revele qué `client_id` existen. bcrypt es CPU-bound (~250 ms): corre en un thread
    para no bloquear el event loop.
    """

    cliente = (
        await session.execute(select(ApiClient).where(ApiClient.client_id == client_id))
    ).scalar_one_or_none()
    hash_a_verificar = cliente.client_secret_hash if cliente is not None else _hash_señuelo()
    valido = await asyncio.to_thread(verify_password, client_secret, hash_a_verificar)
    if cliente is None or not valido or not cliente.activo:
        return None
    return cliente


def _no_autorizado(descripcion: str) -> HTTPException:
    # La descripción va sólo en el cuerpo: los headers HTTP son latin-1/ASCII y el texto en español
    # ("inválido") rompía la respuesta con UnicodeDecodeError.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=descripcion,
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )


def require_oauth_token(*scopes_requeridos: str) -> Callable[..., Awaitable[ClienteAutenticado]]:
    """Factory de dependencia: exige un JWT válido con todos los `scopes_requeridos`.

    Uso: `Depends(require_oauth_token(SCOPE_SERVICIOS_BOTELLAS))`.
    """

    requeridos = frozenset(scopes_requeridos)

    async def _dependencia(
        request: Request,
        bearer: HTTPAuthorizationCredentials | None = Security(_BEARER),
        db: AsyncSession = Depends(get_async_db),
    ) -> ClienteAutenticado:
        try:
            if bearer is None or bearer.scheme.lower() != "bearer" or not bearer.credentials.strip():
                raise _no_autorizado("Token requerido")
            try:
                claims = decodificar_token(bearer.credentials.strip())
            except TokenInvalido as exc:
                raise _no_autorizado(str(exc)) from exc
        except OAuthNoConfigurado as exc:
            logger.error("action=oauth_validar resultado=no_configurado")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OAuth no configurado") from exc

        client_id = claims["sub"]
        cliente = (
            await db.execute(select(ApiClient).where(ApiClient.client_id == client_id))
        ).scalar_one_or_none()
        if cliente is None or not cliente.activo:
            logger.warning("action=oauth_validar client_id=%s resultado=cliente_inactivo_o_inexistente", client_id)
            raise _no_autorizado("Cliente revocado")

        scopes_token = frozenset(claims.get("scope", "").split())
        # El scope efectivo es la intersección: si al cliente le quitaron un scope después de emitir
        # el token, el token deja de servir para ese scope sin esperar a que venza.
        efectivos = scopes_token & frozenset(cliente.scopes or ())
        if not requeridos <= efectivos:
            logger.warning(
                "action=oauth_validar client_id=%s resultado=scope_insuficiente requeridos=%s",
                client_id,
                ",".join(sorted(requeridos)),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Scope insuficiente",
                headers={
                    "WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{" ".join(sorted(requeridos))}"'
                },
            )

        autenticado = ClienteAutenticado(
            client_id=cliente.client_id,
            nombre_area=cliente.nombre_area,
            scopes=tuple(sorted(efectivos)),
        )
        request.state.oauth_client = autenticado
        return autenticado

    return _dependencia
