# Nombre de archivo: 20260917_01_cromo_tracking_cache.py
# Ubicación de archivo: db/alembic/versions/20260917_01_cromo_tracking_cache.py
# Descripción: Nueva tabla app.cromo_tracking_cache — caché de salida, con vencimiento, del
# tracking .txt de cada pelo, para que la descarga multipelo no pague N llamadas a Cromo.

"""Tabla cromo_tracking_cache (caché de trackings con TTL)

Revision ID: 20260917_01
Revises: 20260908_02
Create Date: 2026-09-17

Cambios:
- Nueva tabla ``app.cromo_tracking_cache``. Guarda el ``.txt`` **ya renderizado** por
  ``core/services/cromo/camino_optico_txt.py::renderizar_tracking_txt``, no el camino óptico: las
  tablas ``cromo_*`` de inventario siguen sin recibir nada derivado de ``/path``. Es un caché de
  salida con vencimiento, no dato de inventario.
- Motivo medido: una llamada a ``GET /network/fo/{pelo}/path`` tarda 4,6-14 s (dos corridas reales
  contra Cromo, 2026-09-17), y pasarle varios ids separados por coma **no** devuelve varios
  caminos — con 3 ids Cromo contestó un único nodo raíz. La descarga de N pelos son entonces N
  llamadas secuenciales: el servicio real 122347 (6 pelos) costaba ~30-85 s en frío. Con el caché,
  sólo la primera descarga del día paga ese costo.
- La PK es ``pelo_n_id`` (n_id de linaje del pelo), **sin FK dura** hacia ``app.cromo_pelos``:
  mismo criterio que el resto del namespace, donde las referencias entre entidades de Cromo son
  blandas para tolerar referencias colgadas. La clave es el pelo y no el servicio para que dos
  servicios que comparten pelo compartan la entrada.
- ``servicio_id`` sí lleva FK dura con ``ON DELETE CASCADE`` porque apunta a un maestro propio
  (``app.servicios``): si el servicio se borra, su tracking cacheado deja de tener sentido.
- Índice sobre ``generado_at`` para que la purga de vencidos no haga seq scan.
- El TTL (24 h por defecto) es de la capa de servicio, no del esquema: no hay constraint de
  frescura acá, la lectura descarta lo vencido y la escritura purga.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260917_01"
down_revision = "20260908_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cromo_tracking_cache",
        sa.Column("pelo_n_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "servicio_id",
            sa.Integer(),
            sa.ForeignKey("app.servicios.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("nombre_archivo", sa.String(length=256), nullable=False),
        sa.Column("contenido", sa.Text(), nullable=False),
        sa.Column("duracion_ms", sa.Integer(), nullable=True),
        sa.Column(
            "generado_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="app",
    )
    op.create_index(
        "ix_cromo_tracking_cache_servicio_id",
        "cromo_tracking_cache",
        ["servicio_id"],
        schema="app",
    )
    op.create_index(
        "ix_cromo_tracking_cache_generado_at",
        "cromo_tracking_cache",
        ["generado_at"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_cromo_tracking_cache_generado_at", table_name="cromo_tracking_cache", schema="app")
    op.drop_index("ix_cromo_tracking_cache_servicio_id", table_name="cromo_tracking_cache", schema="app")
    op.drop_table("cromo_tracking_cache", schema="app")
