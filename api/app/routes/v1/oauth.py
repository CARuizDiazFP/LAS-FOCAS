# Nombre de archivo: oauth.py
# Ubicación de archivo: api/app/routes/v1/oauth.py
# Descripción: Token endpoint OAuth2 client_credentials (RFC 6749 §4.4) de la API v1

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Form, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.oauth import OAuthNoConfigurado, autenticar_cliente, emitir_token
from db.session import get_async_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/oauth", tags=["v1"])

_BASIC = HTTPBasic(auto_error=False)
_SIN_CACHE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    scope: str


class OAuthErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str
    error_description: str


def _error(status_code: int, error: str, descripcion: str, *, basic: bool = False) -> JSONResponse:
    headers = dict(_SIN_CACHE)
    if basic:
        headers["WWW-Authenticate"] = 'Basic realm="las-focas-api-v1"'
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "error_description": descripcion},
        headers=headers,
    )


@router.post(
    "/token",
    response_model=TokenResponse,
    responses={400: {"model": OAuthErrorResponse}, 401: {"model": OAuthErrorResponse}},
)
async def emitir_access_token(
    grant_type: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
    scope: Optional[str] = Form(None),
    basic: HTTPBasicCredentials | None = Security(_BASIC),
    db: AsyncSession = Depends(get_async_db),
):
    """Emite un access token para un cliente M2M (`grant_type=client_credentials`).

    Credenciales por HTTP Basic (recomendado por RFC 6749 §2.3.1) **o** en el cuerpo del form,
    nunca por las dos vías a la vez.
    """

    if grant_type is None:
        return _error(400, "invalid_request", "Falta grant_type")
    if grant_type != "client_credentials":
        return _error(400, "unsupported_grant_type", "Sólo se admite client_credentials")

    if basic is not None and client_secret:
        return _error(400, "invalid_request", "Usar un único método de autenticación de cliente")
    if basic is not None:
        # RFC 6749 §2.3.1: client_id y client_secret van form-urlencoded dentro de Basic.
        cid, secreto = unquote(basic.username), unquote(basic.password)
        if client_id and client_id != cid:
            return _error(400, "invalid_request", "client_id del cuerpo no coincide con Basic")
    else:
        cid, secreto = client_id or "", client_secret or ""

    if not cid or not secreto:
        return _error(401, "invalid_client", "Credenciales de cliente requeridas", basic=True)

    cliente = await autenticar_cliente(db, cid, secreto)
    if cliente is None:
        logger.warning("action=oauth_token client_id=%s resultado=invalid_client", cid)
        return _error(401, "invalid_client", "Credenciales de cliente inválidas", basic=True)

    permitidos = list(cliente.scopes or [])
    pedidos = scope.split() if scope and scope.strip() else permitidos
    if not set(pedidos) <= set(permitidos):
        logger.warning("action=oauth_token client_id=%s resultado=invalid_scope", cid)
        return _error(400, "invalid_scope", "Scope no autorizado para este cliente")

    try:
        token, expires_in = emitir_token(cliente.client_id, pedidos)
    except OAuthNoConfigurado:
        logger.error("action=oauth_token resultado=no_configurado")
        return _error(503, "temporarily_unavailable", "OAuth no configurado")

    cliente.ultimo_uso_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info("action=oauth_token client_id=%s resultado=ok scope=%s", cid, " ".join(pedidos))
    return JSONResponse(
        content=TokenResponse(access_token=token, expires_in=expires_in, scope=" ".join(pedidos)).model_dump(),
        headers=_SIN_CACHE,
    )
