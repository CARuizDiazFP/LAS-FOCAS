# Nombre de archivo: password.py
# Ubicación de archivo: core/password.py
# Descripción: Utilidades de hashing/verificación de contraseñas usando bcrypt nativo

from __future__ import annotations

import hashlib
import logging
from typing import Optional

import bcrypt

LOGGER = logging.getLogger(__name__)

_BCRYPT_MAX_BYTES = 72
_BCRYPT_DEFAULT_COST = 12
_HASH_PREFIX = "$lasfocas-sha256-bcrypt$v1$"


def _prehash_password(password: str) -> bytes:
    """Deriva una entrada corta y estable para bcrypt sin truncar la contraseña."""

    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")


def _legacy_to_bytes(password: str) -> bytes | None:
    encoded = password.encode("utf-8")
    if len(encoded) > _BCRYPT_MAX_BYTES:
        return None
    return encoded


def _is_lasfocas_hash(hashed: str) -> bool:
    return hashed.startswith(_HASH_PREFIX)


def _inner_hash(hashed: str) -> str:
    if _is_lasfocas_hash(hashed):
        return hashed.removeprefix(_HASH_PREFIX)
    return hashed


def hash_password(password: str, *, rounds: int = _BCRYPT_DEFAULT_COST) -> str:
    """Genera un hash versionado: SHA-256 de la contraseña completa + bcrypt."""

    pw_bytes = _prehash_password(password)
    salt = bcrypt.gensalt(rounds=rounds)
    bcrypt_hash = bcrypt.hashpw(pw_bytes, salt).decode("utf-8")
    return f"{_HASH_PREFIX}{bcrypt_hash}"


def verify_password(password: str, hashed: str) -> bool:
    """Verifica una contraseña contra hashes nuevos y bcrypt legacy."""

    try:
        if _is_lasfocas_hash(hashed):
            result = bcrypt.checkpw(
                _prehash_password(password),
                _inner_hash(hashed).encode("utf-8"),
            )
        else:
            legacy_bytes = _legacy_to_bytes(password)
            if legacy_bytes is None:
                return False
            result = bcrypt.checkpw(legacy_bytes, hashed.encode("utf-8"))
    except ValueError as exc:
        LOGGER.warning("Hash bcrypt inválido: %s", exc)
        return False
    return bool(result)


def _extract_cost(hashed: str) -> Optional[int]:
    parts = _inner_hash(hashed).split("$")
    if len(parts) < 4:
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


def needs_rehash(hashed: str, *, desired_rounds: int = _BCRYPT_DEFAULT_COST) -> bool:
    """Indica si el hash requiere regenerarse con mayor costo."""

    if not _is_lasfocas_hash(hashed):
        return True
    current = _extract_cost(hashed)
    if current is None:
        return True
    return current < desired_rounds


__all__ = ["hash_password", "verify_password", "needs_rehash"]
