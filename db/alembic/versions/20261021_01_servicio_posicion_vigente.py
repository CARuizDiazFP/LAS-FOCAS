# Nombre de archivo: 20261021_01_servicio_posicion_vigente.py
# Ubicación de archivo: db/alembic/versions/20261021_01_servicio_posicion_vigente.py
# Descripción: Tabla app.servicio_posicion_vigente (posición de ODF por conector que un operador declara
# como la vigente de un Servicio, con la foto del conector y el retiro automático o manual)

"""servicio_posicion_vigente

Revision ID: 20261021_01
Revises: 20261020_01
Create Date: 2026-10-21

Cambios:
- Nueva tabla ``app.servicio_posicion_vigente``: el conector de ODF que un admin declara como la
  posición por la que hoy va el Servicio (caso real: 93150 sigue por O-1252871-1:1/2 aunque sus pelos
  lleven la etiqueta ``FO 44649`` de un servicio de Baja). El tracking siembra desde ``pelo_n_id``.
  ``conector_n_id`` es referencia blanda a ``cromo_odf_conectores.n_id`` (Cromo puede reingerir); la
  fila guarda una foto (ODF, bandeja, número de conector y pelo) para poder avisar aunque el conector
  desaparezca.
- ``pelos_candidatos BIGINT[]``: todos los pelos del conector al declarar (``pelo_n_id`` más los de
  ``tp[]``). La ingesta puede cambiar cuál elige como ``pelo_n_id`` cuando entra el cable de un
  tercero: sólo es ``PELO_CAMBIO`` si el pelo actual no está entre estos.
- Retirar es ``vigente=false`` con fecha, autor (``'auto'`` o el usuario) y motivo; la fila se
  conserva (historial). ``CHECK`` de motivo (``MANUAL``, ``SIN_PELO``, ``PELO_CAMBIO``,
  ``PELO_DANADO``, ``CABLE_SIN_USO``, ``CONECTOR_INEXISTENTE``) y de coherencia (una fila retirada
  tiene fecha y motivo). ``UNIQUE(servicio_id, conector_n_id)`` vale sólo entre las vigentes
  (índice único parcial), igual que ``servicio_odf_confirmada``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261021_01"
down_revision = "20261020_01"
branch_labels = None
depends_on = None

_MOTIVOS = (
    "MANUAL",
    "SIN_PELO",
    "PELO_CAMBIO",
    "PELO_DANADO",
    "CABLE_SIN_USO",
    "CONECTOR_INEXISTENTE",
)


def upgrade() -> None:
    op.create_table(
        "servicio_posicion_vigente",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "servicio_id",
            sa.Integer(),
            sa.ForeignKey("app.servicios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conector_n_id", sa.BigInteger(), nullable=False),
        sa.Column("odf_n_id", sa.BigInteger(), nullable=False),
        sa.Column("bandeja_n_id", sa.BigInteger(), nullable=True),
        sa.Column("bandeja_nombre", sa.Text(), nullable=True),
        sa.Column("numero_conector", sa.Text(), nullable=True),
        sa.Column("pelo_n_id", sa.BigInteger(), nullable=False),
        sa.Column("pelos_candidatos", postgresql.ARRAY(sa.BigInteger()), nullable=True),
        sa.Column("declarado_por", sa.String(length=128), nullable=False),
        sa.Column(
            "declarado_en",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("vigente", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("retirado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retirado_por", sa.String(length=128), nullable=True),
        sa.Column("motivo_retiro", sa.Text(), nullable=True),
        sa.Column("detalle_retiro", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "motivo_retiro IS NULL OR motivo_retiro IN ("
            + ", ".join(f"'{m}'" for m in _MOTIVOS)
            + ")",
            name="ck_servicio_posicion_vigente_motivo",
        ),
        sa.CheckConstraint(
            "vigente OR (retirado_en IS NOT NULL AND motivo_retiro IS NOT NULL)",
            name="ck_servicio_posicion_vigente_retiro_coherente",
        ),
        schema="app",
    )
    op.create_index(
        "ux_servicio_posicion_vigente_vigente",
        "servicio_posicion_vigente",
        ["servicio_id", "conector_n_id"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("vigente"),
    )
    op.create_index(
        "ix_servicio_posicion_vigente_servicio",
        "servicio_posicion_vigente",
        ["servicio_id"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_servicio_posicion_vigente_servicio", table_name="servicio_posicion_vigente", schema="app"
    )
    op.drop_index(
        "ux_servicio_posicion_vigente_vigente", table_name="servicio_posicion_vigente", schema="app"
    )
    op.drop_table("servicio_posicion_vigente", schema="app")
