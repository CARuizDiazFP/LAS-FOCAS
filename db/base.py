# Nombre de archivo: base.py
# Ubicación de archivo: db/base.py
# Descripción: Declaración de la base SQLAlchemy compartida por los modelos

from __future__ import annotations

from sqlalchemy.orm import declarative_base

Base = declarative_base()
