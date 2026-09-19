# Nombre de archivo: soporte_postgres_real.py
# Ubicación de archivo: tests/soporte_postgres_real.py
# Descripción: Guard compartido de los tests de integración que necesitan un Postgres real alcanzable

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
"""

from __future__ import annotations

import os
from functools import lru_cache

import pytest

# El Postgres de dev está publicado en 127.0.0.1:5433 (el 5432 es el de producción, ver
# `deploy/docker-compose.dev.yml`). La contraseña se lee del Docker Secret file, nunca se escribe.
COMO_HABILITARLOS = (
    "POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_DB=focas_dev POSTGRES_USER=FOCALBOT "
    'POSTGRES_PASSWORD="$(cat .secrets/Dev_db_password_v1.txt)" pytest'
)


@lru_cache(maxsize=1)
def hay_postgres_real() -> bool:
    """`True` si `db.session.SessionLocal` abre conexión y contesta un `SELECT 1`.

    Cacheado: se intenta una sola vez por proceso, en la colección del primer archivo que importe
    el guard. El caso que importa (host que no resuelve, o puerto cerrado) falla de inmediato, así
    que no hace falta un timeout explícito.
    """
    from sqlalchemy import text

    from db.session import SessionLocal

    try:
        with SessionLocal() as sesion:
            sesion.execute(text("SELECT 1"))
    except Exception:  # cualquier fallo de conexión/auth/esquema es "no hay DB usable"
        return False
    return True


def _condicion_y_razon() -> tuple[bool, str]:
    if os.getenv("CI") == "true":
        # Corto antes de intentar conectar: en CI no hay servicio y no tiene sentido el intento.
        return True, "requiere Postgres real alcanzable; el workflow de CI no tiene ese servicio configurado"
    if not hay_postgres_real():
        return True, (
            "requiere Postgres real alcanzable y no hay ninguno respondiendo. "
            f"Para correrlos de verdad: {COMO_HABILITARLOS}"
        )
    return False, ""


_saltear, _razon = _condicion_y_razon()

#: Marcador para `pytestmark` de cada archivo de integración.
requiere_postgres_real = pytest.mark.skipif(_saltear, reason=_razon)

__all__ = ["COMO_HABILITARLOS", "hay_postgres_real", "requiere_postgres_real"]
