## Nombre de archivo: script.py.mako
## Ubicación de archivo: db/alembic/script.py.mako
## Descripción: Plantilla base para nuevas revisiones de Alembic en LAS-FOCAS
## (las líneas "##" son comentarios de Mako y no se copian a la migración generada; completar el
## nombre real del archivo en el encabezado que sigue)
# Nombre de archivo: ${up_revision}_<slug>.py
# Ubicación de archivo: db/alembic/versions/${up_revision}_<slug>.py
# Descripción: ${message}

"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
