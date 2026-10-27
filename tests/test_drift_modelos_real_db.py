# Nombre de archivo: test_drift_modelos_real_db.py
# Ubicación de archivo: tests/test_drift_modelos_real_db.py
# Descripción: Falla si vuelve a aparecer drift entre los modelos SQLAlchemy y la base de dev (mismo alcance que el autogenerate)

"""Con ``target_metadata`` encendido en `db/alembic/env.py`, cualquier drift modelo↔base termina en
un ``alembic revision --autogenerate`` que propone borrar o recrear objetos reales. Este test lo
detecta antes: corre ``compare_metadata`` (config de `db/models/autogenerate.py`) en una transacción
de sólo lectura contra la DB de dev y exige cero diferencias.

Si falla después de una migración nueva: o falta declarar el cambio en el modelo, o la DB de dev no
tiene aplicada la migración de la rama. El detalle clasificado sale de
``python scripts/check_drift_modelos.py --detalle``. Para una base nueva desde cero:
``scripts/check_drift_desde_cero.sh``.
"""

from __future__ import annotations

from sqlalchemy import text

from db.models.autogenerate import comparar_modelos
from scripts.check_drift_modelos import clasificar
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real


def test_modelos_sin_drift_contra_la_base():
    from db.session import engine

    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            diferencias = comparar_modelos(conn)
    assert clasificar(diferencias) == {}
