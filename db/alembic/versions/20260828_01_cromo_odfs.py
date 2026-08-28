# Nombre de archivo: 20260828_01_cromo_odfs.py
# Ubicación de archivo: db/alembic/versions/20260828_01_cromo_odfs.py
# Descripción: Nueva tabla app.cromo_odfs — submódulo ODFs de Cromo Red (clase 69), objeto de
# primer nivel hermano de Cable/Botella, sin columna de agrupamiento por sitio.

"""Tabla cromo_odfs (submódulo ODFs, Cromo Red clase 69)

Revision ID: 20260828_01
Revises: 20260825_02
Create Date: 2026-08-28

Cambios:
- Nueva tabla ``app.cromo_odfs``: mismo patrón de columnas que ``app.cromo_botellas`` (``n_id``
  como PK de linaje, ``version_id``/``vmax`` como detector de cambios, dirección desnormalizada,
  ``pts_raw``/``payload_raw`` en JSONB, timestamps de ingesta) salvo `camara_id`/`estado`
  (explícitamente fuera de alcance para ODF en esta iteración) y sin ninguna columna de "sitio":
  el agrupamiento de ODFs que comparten domicilio físico se resuelve por dirección
  (``calle``+``altura``+``localidad``) en la capa de consulta, no en el esquema — diagnóstico real
  contra Cromo (Tarea 0) confirmó que el nombre de un ODF es texto libre sin ningún ID de sitio
  embebido, a diferencia de lo que asumía el ticket original.
- Columnas propias de ODF: ``propietario`` (at.47 Cromo), ``tipo_elemento`` (clasificación
  heurística por nombre que puebla el parser de una tarea posterior; arranca en
  ``'SIN_CLASIFICAR'``, CHECK restringe a ``ODF``/``EMPALME``/``SIN_CLASIFICAR`` — columna simple +
  CHECK, mismo criterio que ``cromo_botella_alias.accion``, no un enum nativo de Postgres) y
  ``cables_asociados`` (JSONB, mirror crudo de n_ids de cables desde ``tp[]``, lo llena el
  parser/ingesta de tareas posteriores).
- Índice btree explícito sobre ``nombre`` (mismo criterio que
  ``ix_cromo_botellas_nombre_btree``, ver ``20260823_01_ingreso_seguimiento_empalme.py`` /
  ``db/models/cromo.py``): soporta la cascada ILIKE/tokens de búsqueda de infraestructura.
- No agrega ``camara_id``, ``estado`` ni ningún ``odf_sitio_id`` — fuera de alcance explícito de
  esta tarea (ver brief de la Tarea 1).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260828_01"
down_revision = "20260825_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cromo_odfs",
        sa.Column("n_id", sa.BigInteger(), primary_key=True),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("vmax", sa.Integer(), nullable=False),
        sa.Column("clase", sa.SmallInteger(), sa.ForeignKey("app.cromo_clases.clase"), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=True),
        sa.Column("codigo_modelo", sa.Text(), nullable=True),
        sa.Column("id_legacy", sa.Text(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("calle", sa.Text(), nullable=True),
        sa.Column("altura", sa.Text(), nullable=True),
        sa.Column("localidad", sa.Text(), nullable=True),
        sa.Column("provincia", sa.Text(), nullable=True),
        sa.Column("ubicacion_fisica", sa.Text(), nullable=True),
        sa.Column("tendido", sa.Text(), nullable=True),
        sa.Column("latitud", sa.Float(), nullable=True),
        sa.Column("longitud", sa.Float(), nullable=True),
        sa.Column("pts_raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("payload_raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("vigente", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "primera_ingesta",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "ultima_ingesta",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("ultima_modificacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("propietario", sa.Text(), nullable=True),
        sa.Column("tipo_elemento", sa.Text(), nullable=False, server_default="SIN_CLASIFICAR"),
        sa.Column("cables_asociados", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="app",
    )
    op.create_index(
        "ix_cromo_odfs_nombre_btree",
        "cromo_odfs",
        ["nombre"],
        schema="app",
    )
    op.create_check_constraint(
        "ck_cromo_odfs_tipo_elemento_valido",
        "cromo_odfs",
        "tipo_elemento IN ('ODF', 'EMPALME', 'SIN_CLASIFICAR')",
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint("ck_cromo_odfs_tipo_elemento_valido", "cromo_odfs", schema="app", type_="check")
    op.drop_index("ix_cromo_odfs_nombre_btree", table_name="cromo_odfs", schema="app")
    op.drop_table("cromo_odfs", schema="app")
