# Nombre de archivo: test_password.py
# Ubicación de archivo: tests/test_password.py
# Descripción: Pruebas del hashing versionado y compatibilidad legacy de contraseñas

from __future__ import annotations

import bcrypt

from core.password import hash_password, needs_rehash, verify_password


def _legacy_hash(password: str, *, rounds: int = 4) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("utf-8")


def test_hash_password_genera_formato_versionado() -> None:
    hashed = hash_password("secreto", rounds=4)

    assert hashed.startswith("$lasfocas-sha256-bcrypt$v1$")
    assert verify_password("secreto", hashed) is True
    assert verify_password("otro", hashed) is False


def test_password_larga_no_se_trunca_silenciosamente() -> None:
    base = "a" * 72
    password_a = f"{base}A"
    password_b = f"{base}B"

    hashed = hash_password(password_a, rounds=4)

    assert verify_password(password_a, hashed) is True
    assert verify_password(password_b, hashed) is False


def test_verify_password_soporta_hash_bcrypt_legacy_corto() -> None:
    hashed = _legacy_hash("legacy")

    assert verify_password("legacy", hashed) is True
    assert verify_password("otro", hashed) is False


def test_verify_password_legacy_largo_no_aplica_truncado() -> None:
    legacy_hash = _legacy_hash("a" * 72)

    assert verify_password(("a" * 72) + "b", legacy_hash) is False


def test_needs_rehash_detecta_legacy_y_coste_bajo() -> None:
    legacy = _legacy_hash("legacy")
    nuevo_bajo = hash_password("secreto", rounds=4)
    nuevo_ok = hash_password("secreto", rounds=4)

    assert needs_rehash(legacy, desired_rounds=4) is True
    assert needs_rehash(nuevo_bajo, desired_rounds=12) is True
    assert needs_rehash(nuevo_ok, desired_rounds=4) is False
