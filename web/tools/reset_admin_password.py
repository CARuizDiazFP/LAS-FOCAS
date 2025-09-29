# Nombre de archivo: reset_admin_password.py
# Ubicación de archivo: web/tools/reset_admin_password.py
# Descripción: Script utilitario para resetear la contraseña del usuario 'admin' en app.web_users

from __future__ import annotations

import argparse
import os
import sys
from passlib.hash import bcrypt  # type: ignore
import traceback
import psycopg  # type: ignore


def build_dsn() -> str:
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "lasfocas")
    user = os.getenv("POSTGRES_USER", "lasfocas")
    pwd = os.getenv("POSTGRES_PASSWORD", "")
    return f"dbname={db} user={user} password={pwd} host={host} port={port}"


def _hash_password(password: str) -> str:
    """Genera un hash bcrypt confiable.

    Maneja:
    - Falla del backend interno de passlib (caso AttributeError __about__).
    - Mensaje engañoso de longitud (>72 bytes) para passwords cortas debido a backend roto.
    - Fuerza truncado manual a 72 bytes si excede el límite real de bcrypt.
    """
    if len(password.encode("utf-8")) > 72:
        # Bcrypt sólo usa 72 bytes; truncamos explícitamente para evitar inconsistencias silenciosas.
        print("[WARN] Password >72 bytes. Se truncará a 72 bytes para hashing.")
        password = password.encode("utf-8")[:72].decode("utf-8", errors="ignore")
    try:
        return bcrypt.hash(password)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] passlib bcrypt.hash falló: {exc.__class__.__name__}: {exc}")
        traceback.print_exc()
        # Intentar fallback directo usando librería 'bcrypt' instalada.
        try:
            import bcrypt as _bc  # type: ignore

            salt = _bc.gensalt(rounds=12)
            h = _bc.hashpw(password.encode("utf-8"), salt)
            return h.decode("utf-8")
        except Exception as exc2:  # noqa: BLE001
            print(f"[ERROR] Fallback directo a bcrypt también falló: {exc2}")
            traceback.print_exc()
            sys.exit(2)


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verifica password contra hash almacenado con doble estrategia."""
    try:
        return bcrypt.verify(password, stored_hash)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] passlib bcrypt.verify falló: {exc.__class__.__name__}: {exc}")
        traceback.print_exc()
        try:
            import bcrypt as _bc  # type: ignore

            res = _bc.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
            return bool(res)
        except Exception as exc2:  # noqa: BLE001
            print(f"[ERROR] Fallback directo a bcrypt.verify también falló: {exc2}")
            traceback.print_exc()
            sys.exit(3)


def reset(password: str, username: str = "admin") -> None:
    dsn = build_dsn()
    new_hash = _hash_password(password)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM app.web_users WHERE username=%s", (username,))
            if not cur.fetchone():
                print(f"[ERROR] Usuario '{username}' no existe.")
                sys.exit(1)
            cur.execute(
                "UPDATE app.web_users SET password_hash=%s WHERE username=%s",
                (new_hash, username),
            )
            conn.commit()
    print(f"[OK] Contraseña de '{username}' actualizada. Longitud hash={len(new_hash)}")


def verify(password: str, username: str = "admin") -> None:
    dsn = build_dsn()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM app.web_users WHERE username=%s", (username,))
            row = cur.fetchone()
            if not row:
                print(f"[ERROR] Usuario '{username}' no existe.")
                sys.exit(1)
            stored_hash = row[0]
            ok = _verify_password(password, stored_hash)
            print(f"[INFO] verify(password) -> {ok}. Hash={stored_hash}")


def main():
    parser = argparse.ArgumentParser(description="Resetear o verificar password admin")
    parser.add_argument("--password", required=True, help="Nueva contraseña o contraseña a verificar")
    parser.add_argument("--mode", choices=["reset", "verify"], default="verify")
    parser.add_argument("--user", default="admin")
    args = parser.parse_args()
    if args.mode == "reset":
        reset(args.password, args.user)
    else:
        verify(args.password, args.user)


if __name__ == "__main__":  # pragma: no cover
    main()
