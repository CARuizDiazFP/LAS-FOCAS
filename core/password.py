# Nombre de archivo: password.py
# Ubicación de archivo: core/password.py
# Descripción: Utilidades de hashing/verificación de contraseñas usando bcrypt nativo

from __future__ import annotations

import logging
from typing import Optional

import bcrypt

LOGGER = logging.getLogger(__name__)

_BCRYPT_MAX_BYTES = 72
_BCRYPT_DEFAULT_COST = 12


def _normalize_length(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) <= _BCRYPT_MAX_BYTES:
        return password
    LOGGER.warning(
        "Password supera %s bytes; se truncará para compatibilidad con bcrypt",
        _BCRYPT_MAX_BYTES,
    )
    return encoded[:_BCRYPT_MAX_BYTES].decode("utf-8", errors="ignore")


def _to_bytes(password: str) -> bytes:
    return _normalize_length(password).encode("utf-8")


def hash_password(password: str, *, rounds: int = _BCRYPT_DEFAULT_COST) -> str:
    """Genera un hash bcrypt usando únicamente la librería `bcrypt`."""

    pw_bytes = _to_bytes(password)
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verifica la contraseña contra un hash bcrypt."""

    try:
        result = bcrypt.checkpw(_to_bytes(password), hashed.encode("utf-8"))
    except ValueError as exc:
        LOGGER.warning("Hash bcrypt inválido: %s", exc)
        return False
    return bool(result)


def _extract_cost(hashed: str) -> Optional[int]:
    parts = hashed.split("$")
    if len(parts) < 4:
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


def needs_rehash(hashed: str, *, desired_rounds: int = _BCRYPT_DEFAULT_COST) -> bool:
    """Indica si el hash requiere regenerarse con mayor costo."""

    current = _extract_cost(hashed)
    if current is None:
        return True
    return current < desired_rounds


__all__ = ["hash_password", "verify_password", "needs_rehash"]
