# Nombre de archivo: api_clients.py
# Ubicación de archivo: scripts/api_clients.py
# Descripción: CLI para dar de alta, listar, desactivar y rotar clientes OAuth2 M2M (app.api_clients) de la API v1

"""Administración de clientes OAuth2 `client_credentials` de `/api/v1`.

Se corre dentro del contenedor de la API, que ya tiene la conexión y el secreto de la base:

    docker exec -it lasfocasdev-api python scripts/api_clients.py crear --area "NOC" \\
        --scopes servicios:botellas:read
    docker exec -it lasfocasdev-api python scripts/api_clients.py listar
    docker exec -it lasfocasdev-api python scripts/api_clients.py desactivar --client-id lf_...
    docker exec -it lasfocasdev-api python scripts/api_clients.py rotar-secret --client-id lf_...

El `client_secret` se imprime **una sola vez** por stdout al crear o rotar; en la base sólo queda
su hash. Nunca se pasa como argumento (quedaría en el historial del shell y en `ps`).
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path
from typing import Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:  # pragma: no cover - inicialización
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from core.password import hash_password  # noqa: E402
from db.models.api_clients import ApiClient  # noqa: E402

SCOPES_CONOCIDOS = frozenset({"servicios:botellas:read"})


def generar_client_id() -> str:
    return f"lf_{secrets.token_hex(8)}"


def generar_client_secret() -> str:
    return secrets.token_urlsafe(32)


def validar_scopes(scopes: Sequence[str]) -> list[str]:
    desconocidos = sorted(set(scopes) - SCOPES_CONOCIDOS)
    if desconocidos:
        raise SystemExit(f"Scopes desconocidos: {', '.join(desconocidos)}. Válidos: {', '.join(sorted(SCOPES_CONOCIDOS))}")
    return sorted(set(scopes))


def crear(session: Session, area: str, scopes: Sequence[str]) -> tuple[str, str]:
    client_id, secreto = generar_client_id(), generar_client_secret()
    session.add(
        ApiClient(
            client_id=client_id,
            client_secret_hash=hash_password(secreto),
            nombre_area=area.strip(),
            activo=True,
            scopes=validar_scopes(scopes),
        )
    )
    session.commit()
    return client_id, secreto


def _buscar(session: Session, client_id: str) -> ApiClient:
    cliente = session.execute(select(ApiClient).where(ApiClient.client_id == client_id)).scalar_one_or_none()
    if cliente is None:
        raise SystemExit(f"No existe el cliente {client_id}")
    return cliente


def desactivar(session: Session, client_id: str) -> None:
    _buscar(session, client_id).activo = False
    session.commit()


def rotar_secret(session: Session, client_id: str) -> str:
    cliente = _buscar(session, client_id)
    secreto = generar_client_secret()
    cliente.client_secret_hash = hash_password(secreto)
    session.commit()
    return secreto


def listar(session: Session) -> list[ApiClient]:
    return list(session.execute(select(ApiClient).order_by(ApiClient.id)).scalars())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="comando", required=True)
    p_crear = sub.add_parser("crear", help="Alta de un cliente; imprime el secret una sola vez")
    p_crear.add_argument("--area", required=True, help="Área corporativa dueña del cliente")
    p_crear.add_argument("--scopes", nargs="+", required=True, help="Scopes autorizados")
    sub.add_parser("listar", help="Lista clientes (nunca muestra secretos)")
    for nombre, ayuda in (("desactivar", "Revoca el acceso de inmediato"), ("rotar-secret", "Genera un secret nuevo")):
        p = sub.add_parser(nombre, help=ayuda)
        p.add_argument("--client-id", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    from db.session import SessionLocal

    with SessionLocal() as session:
        if args.comando == "crear":
            client_id, secreto = crear(session, args.area, args.scopes)
            print(f"client_id:     {client_id}")
            print(f"client_secret: {secreto}")
            print("Guardá el secret ahora: no se puede volver a mostrar.")
        elif args.comando == "listar":
            for c in listar(session):
                uso = c.ultimo_uso_at.isoformat() if c.ultimo_uso_at else "-"
                print(f"{c.client_id}\t{'activo' if c.activo else 'INACTIVO'}\t{c.nombre_area}\t{','.join(c.scopes or [])}\tultimo_uso={uso}")
        elif args.comando == "desactivar":
            desactivar(session, args.client_id)
            print(f"{args.client_id} desactivado: sus tokens vigentes dejan de funcionar ya.")
        elif args.comando == "rotar-secret":
            secreto = rotar_secret(session, args.client_id)
            print(f"client_secret: {secreto}")
            print("El secret anterior ya no emite tokens nuevos. Guardá este ahora.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
