# Nombre de archivo: soporte_postgres_real.py
# Ubicación de archivo: tests/soporte_postgres_real.py
# Descripción: Guard compartido de los tests de integración que necesitan un Postgres real alcanzable (y de dev/test, nunca prod)

"""Los tests de integración `*_real_db` (y los de rutas que pegan contra la DB) cubren cosas que un
mock no puede detectar nunca: inferencia de tipos de asyncpg, planes de ejecución, constraints
reales. A cambio necesitan un Postgres con el esquema `app.*` poblado.

Hasta 2026-09-19 el guard de estos archivos sólo salteaba con `CI=true`. En una máquina de
desarrollo el comando documentado en `AGENTS.md` (`pytest`, sin variables) apunta al host `postgres`
del compose, que no resuelve desde afuera de la red de Docker: los ~29 tests fallaban con
`failed to resolve host 'postgres'` y arrastraban otros ~65 a error. Todo ese rojo era ruido de
entorno, no regresiones — y tapaba los fallos reales que sí había debajo.

Este guard extiende la misma intención ("no falles donde no hay Postgres") al caso local: si no hay
una DB respondiendo, los tests se saltean con un motivo que dice cómo habilitarlos. Con las
variables puestas corren de verdad, sin cambios.

Desde 2026-10-26 además verifica *a qué* DB se conectó: 19 de estos archivos hacen `.commit()` real,
así que un entorno mal apuntado escribiría en producción. Si `current_database()` no está en la
allowlist de DBs de dev/test, los tests se saltean (nunca corren) diciendo qué DB encontraron.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

import pytest

# El Postgres de dev está publicado en 127.0.0.1:5433 (el 5432 es el de producción, ver
# `deploy/docker-compose.dev.yml`). La contraseña se lee del Docker Secret file, nunca se escribe.
COMO_HABILITARLOS = (
    "POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_DB=focas_dev POSTGRES_USER=FOCALBOT "
    'POSTGRES_PASSWORD="$(cat .secrets/Dev_db_password_v1.txt)" pytest'
)


#: DBs donde estos tests pueden escribir: la de dev (`POSTGRES_DB` de `deploy/env.dev.sample`) y una
#: de test dedicada. La de producción (`FOCALDB`, `deploy/env.sample`) queda afuera a propósito.
DBS_PERMITIDAS: frozenset[str] = frozenset({"focas_dev", "focas_test"})

#: Variable para sumar DBs a la allowlist (separadas por coma) sin tocar el código, p. ej. una
#: DB efímera de CI. Pensada para nombres de test: no agregues nunca la de producción.
VARIABLE_DBS_EXTRA = "TESTS_DB_PERMITIDAS"


def dbs_permitidas() -> frozenset[str]:
    extra = {n.strip() for n in os.getenv(VARIABLE_DBS_EXTRA, "").split(",") if n.strip()}
    return DBS_PERMITIDAS | extra


def motivo_db_no_permitida(nombre_db: str) -> Optional[str]:
    """`None` si `nombre_db` está en la allowlist; si no, el motivo del skip."""
    permitidas = dbs_permitidas()
    if nombre_db in permitidas:
        return None
    return (
        f"la conexión apunta a la DB {nombre_db!r}, que no está en la allowlist de dev/test "
        f"({', '.join(sorted(permitidas))}): estos tests hacen commit real y no se corren fuera de "
        f"dev. Si es una DB de test, sumala con {VARIABLE_DBS_EXTRA}=<nombre>"
    )


@lru_cache(maxsize=1)
def db_real_conectada() -> Optional[str]:
    """Nombre de la DB (`current_database()`) a la que conecta `db.session.SessionLocal`, o `None`.

    Cacheado: se intenta una sola vez por proceso, en la colección del primer archivo que importe
    el guard. El caso que importa (host que no resuelve, o puerto cerrado) falla de inmediato, así
    que no hace falta un timeout explícito.
    """
    from sqlalchemy import text

    from db.session import SessionLocal

    try:
        with SessionLocal() as sesion:
            return sesion.execute(text("SELECT current_database()")).scalar_one()
    except Exception:  # cualquier fallo de conexión/auth/esquema es "no hay DB usable"
        return None


def hay_postgres_real() -> bool:
    """`True` si hay un Postgres respondiendo (sea cual sea la DB)."""
    return db_real_conectada() is not None


def _condicion_y_razon() -> tuple[bool, str]:
    if os.getenv("CI") == "true":
        # Corto antes de intentar conectar: en CI no hay servicio y no tiene sentido el intento.
        return True, "requiere Postgres real alcanzable; el workflow de CI no tiene ese servicio configurado"
    nombre_db = db_real_conectada()
    if nombre_db is None:
        return True, (
            "requiere Postgres real alcanzable y no hay ninguno respondiendo. "
            f"Para correrlos de verdad: {COMO_HABILITARLOS}"
        )
    motivo = motivo_db_no_permitida(nombre_db)
    if motivo is not None:
        return True, motivo
    return False, ""


_saltear, _razon = _condicion_y_razon()

#: Marcador para `pytestmark` de cada archivo de integración.
requiere_postgres_real = pytest.mark.skipif(_saltear, reason=_razon)

__all__ = [
    "COMO_HABILITARLOS",
    "DBS_PERMITIDAS",
    "db_real_conectada",
    "dbs_permitidas",
    "hay_postgres_real",
    "motivo_db_no_permitida",
    "requiere_postgres_real",
]
