# Nombre de archivo: base.py
# Ubicación de archivo: db/base.py
# Descripción: Declaración de la base SQLAlchemy compartida por los modelos

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import declarative_base

# Los índices de `index=True` se llaman como los crean las migraciones: ix_<tabla>_<columnas>. Sin
# esto SQLAlchemy usa ix_<esquema>_<tabla>_<columna> (ix_app_...) y el autogenerate propondría
# renombrar decenas de índices reales. Los nombres explícitos no se ven afectados.
Base = declarative_base(metadata=MetaData(naming_convention={"ix": "ix_%(table_name)s_%(column_0_N_name)s"}))
