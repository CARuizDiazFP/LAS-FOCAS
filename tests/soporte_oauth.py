# Nombre de archivo: soporte_oauth.py
# Ubicación de archivo: tests/soporte_oauth.py
# Descripción: Soporte compartido de los tests OAuth2 M2M: secreto de firma, clientes y sesión async falsa

from __future__ import annotations

from typing import AsyncGenerator, Iterable, Optional

import pytest

from core.password import hash_password
from db.models.api_clients import ApiClient

SECRETO_TEST = "s3cr3to-de-test-para-firmar-jwt-de-al-menos-32-bytes"
CLIENT_SECRET = "el-secreto-del-cliente-NOC"


@pytest.fixture(autouse=True)
def secreto_firma(monkeypatch: pytest.MonkeyPatch) -> str:
    """Sin /run/secrets en el entorno de test, `get_secret` cae a la variable de entorno."""

    monkeypatch.setenv("OAUTH_JWT_SECRET", SECRETO_TEST)
    monkeypatch.delenv("OAUTH_TOKEN_TTL_SECONDS", raising=False)
    return SECRETO_TEST


def hacer_cliente(
    client_id: str = "lf_noc",
    *,
    secreto: str = CLIENT_SECRET,
    activo: bool = True,
    scopes: Iterable[str] = ("servicios:read",),
) -> ApiClient:
    # rounds=4: el costo real (12) hace lentísima la suite sin cambiar lo que se prueba.
    return ApiClient(
        client_id=client_id,
        client_secret_hash=hash_password(secreto, rounds=4),
        nombre_area="NOC",
        activo=activo,
        scopes=list(scopes),
    )


class _Resultado:
    def __init__(self, valor: Optional[ApiClient]) -> None:
        self._valor = valor

    def scalar_one_or_none(self) -> Optional[ApiClient]:
        return self._valor


class SesionFalsa:
    """Responde los `SELECT ApiClient WHERE client_id = :x` buscando en un dict en memoria."""

    def __init__(self, *clientes: ApiClient) -> None:
        self.clientes = {c.client_id: c for c in clientes}
        self.commits = 0

    async def execute(self, stmt, *_args, **_kwargs) -> _Resultado:
        params = stmt.compile().params
        valores = [v for v in params.values() if isinstance(v, str)]
        return _Resultado(next((self.clientes[v] for v in valores if v in self.clientes), None))

    async def commit(self) -> None:
        self.commits += 1


def override_con(sesion: SesionFalsa):
    async def _dep() -> AsyncGenerator[SesionFalsa, None]:
        yield sesion

    return _dep
