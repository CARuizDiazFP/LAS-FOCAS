# Nombre de archivo: script.py.mako
# Ubicación de archivo: db/alembic/script.py.mako
# Descripción: Plantilla base para nuevas revisiones de Alembic en LAS-FOCAS

"""${message}"""

import sqlalchemy as sa
from alembic import op

revision = ${repr(revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
