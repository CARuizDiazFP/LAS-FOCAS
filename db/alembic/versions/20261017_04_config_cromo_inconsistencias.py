# Nombre de archivo: 20261017_04_config_cromo_inconsistencias.py
# Ubicación de archivo: db/alembic/versions/20261017_04_config_cromo_inconsistencias.py
# Descripción: Fila "Cromo Inconsistencias" en app.config_servicios (aviso de casos nuevos a Slack), inactiva y sin canales

"""Config del aviso de inconsistencias de Cromo

Revision ID: 20261017_04
Revises: 20261017_03
Create Date: 2026-10-17

Cambios:
- Fila ``Cromo Inconsistencias`` en ``app.config_servicios``, **inactiva** y con ``slack_channels``
  vacío. El ``cromo_worker`` sólo manda el mensaje a Slack (con el XLSX de los casos nuevos) si la
  fila está activa y tiene canales: para activarlo se carga el canal y se enciende desde el viewer de Inconsistencias Cromo
  (``GET/POST /api/admin/infra/inconsistencias-cromo/aviso-slack``).
  Sin fila o inactiva, el aviso por WebSocket admin se publica igual.
- Idempotente (``WHERE NOT EXISTS``). El ``downgrade()`` borra la fila.
"""

from __future__ import annotations

from alembic import op

revision = "20261017_04"
down_revision = "20261017_03"
branch_labels = None
depends_on = None

_NOMBRE = "Cromo Inconsistencias"


def upgrade() -> None:
    op.execute(
        "INSERT INTO app.config_servicios (nombre_servicio, intervalo_horas, slack_channels, activo) "
        f"SELECT '{_NOMBRE}', 0, '', false "
        f"WHERE NOT EXISTS (SELECT 1 FROM app.config_servicios WHERE nombre_servicio = '{_NOMBRE}')"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM app.config_servicios WHERE nombre_servicio = '{_NOMBRE}'")
