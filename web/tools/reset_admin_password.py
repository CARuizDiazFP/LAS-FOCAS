# Nombre de archivo: reset_admin_password.py
# Ubicación de archivo: web/tools/reset_admin_password.py
# Descripción: Script utilitario para resetear la contraseña del usuario 'admin' en app.web_users

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
import traceback

import psycopg  # type: ignore

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from core.password import hash_password, verify_password


def build_dsn() -> str:
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "lasfocas")
    user = os.getenv("POSTGRES_USER", "lasfocas")
    pwd = os.getenv("POSTGRES_PASSWORD", "")
    return f"dbname={db} user={user} password={pwd} host={host} port={port}"

def reset(password: str, username: str = "admin") -> None:
    dsn = build_dsn()
    try:
        new_hash = hash_password(password)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] No se pudo generar el hash: {exc}")
        traceback.print_exc()
        sys.exit(2)
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
            try:
                ok = verify_password(password, stored_hash)
            except Exception as exc:  # noqa: BLE001
                print(f"[ERROR] No se pudo verificar el hash: {exc}")
                traceback.print_exc()
                sys.exit(3)
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
