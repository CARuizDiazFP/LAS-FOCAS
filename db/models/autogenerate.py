# Nombre de archivo: autogenerate.py
# Ubicación de archivo: db/models/autogenerate.py
# Descripción: Alcance y opciones de comparación modelo↔base compartidos por db/alembic/env.py y scripts/check_drift_modelos.py

"""Qué compara el autogenerate de Alembic y con qué opciones.

`db/alembic/env.py` (``alembic revision --autogenerate`` / ``alembic check``) y
`scripts/check_drift_modelos.py` usan exactamente esta configuración, para que el chequeo de drift
mida lo mismo que va a proponer el autogenerate.

- Sólo el esquema ``app``: ``public`` tiene ``alembic_version`` y el enum ``punto_terminal_tipo``,
  nada que se modele.
- ``TABLAS_SIN_MODELO`` quedan afuera: existen en la base, las usa código con SQL crudo y no tienen
  modelo SQLAlchemy. La lista es explícita a propósito: una tabla nueva sin modelo tiene que
  aparecer como drift, no esconderse.
- Se comparan tipos y ``server_default`` (Alembic compara comentarios, nulabilidad, índices y
  constraints siempre).
"""

from __future__ import annotations

from typing import Any, Optional

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import Connection

from db.base import Base

# Registrar todos los modelos en Base.metadata: db.models no importa infra en su __init__.
import db.models  # noqa: F401
import db.models.infra  # noqa: F401

ESQUEMA = "app"

#: Tablas de ``app`` sin modelo SQLAlchemy (verificado contra dev el 2026-10-27). No se borran ni
#: se modelan acá: el autogenerate las ignora junto con sus índices.
TABLAS_SIN_MODELO: frozenset[str] = frozenset(
    {
        "chat_messages",
        "chat_sessions",
        "conversations",
        "example",
        "messages",
        "report_history",
        "web_users",
    }
)


def include_name(name: Optional[str], type_: str, parent_names: dict[str, Any]) -> bool:
    if type_ == "schema":
        return name == ESQUEMA
    return True


def include_object(obj: Any, name: Optional[str], type_: str, reflected: bool, compare_to: Any) -> bool:
    if type_ == "table" and reflected and compare_to is None and name in TABLAS_SIN_MODELO:
        return False
    return True


#: Opciones para ``context.configure`` / ``MigrationContext.configure``.
OPCIONES_COMPARACION: dict[str, Any] = {
    "include_schemas": True,
    "include_name": include_name,
    "include_object": include_object,
    "compare_type": True,
    "compare_server_default": True,
}

target_metadata = Base.metadata


def comparar_modelos(conn: Connection) -> list[Any]:
    """Diferencias modelo↔base (formato de ``compare_metadata``); lista vacía = sin drift."""
    contexto = MigrationContext.configure(conn, opts=OPCIONES_COMPARACION)
    return compare_metadata(contexto, target_metadata)
