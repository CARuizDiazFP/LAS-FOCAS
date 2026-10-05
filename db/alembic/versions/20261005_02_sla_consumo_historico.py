# Nombre de archivo: 20261005_02_sla_consumo_historico.py
# Ubicación de archivo: db/alembic/versions/20261005_02_sla_consumo_historico.py
# Descripción: Histórico SLA consumido — amplía app.reclamos, crea sla_ingestas, servicio_sla_snapshot y v_eventos_sla

"""sla_consumo_historico

Revision ID: 20261005_02
Revises: 20261005_01
Create Date: 2026-10-05

Cambios:
- ``app.reclamos``: horas en horas decimales Numeric(12,4) (antes Numeric(10,2) con minutos por bug
  del parser; la tabla estaba vacía en dev y prod el 2026-10-05), columnas de Carrier, código y
  grupo de cierre, ingesta y first/last seen.
- ``app.sla_ingestas`` (una fila por par de archivos, única por hashes).
- ``app.servicio_sla_snapshot`` (foto del Excel de Servicios por fecha de corte).
- Vista ``app.v_eventos_sla`` derivada de reclamos.

Los índices usan la convención del modelo (``ix_reclamos_<col>``), igual que 20251014_01.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261005_02"
down_revision = "20261005_01"
branch_labels = None
depends_on = None

_NUEVAS = [
    ("numero_primer_servicio", sa.String(64)),
    ("codigo_cierre", sa.Integer()),
    ("grupo_cierre", sa.String(40)),
    ("horas_totales_problema", sa.Numeric(12, 4)),
    ("horas_indisponibilidad_problema", sa.Numeric(12, 4)),
    ("horas_netas_escalamiento_carrier", sa.Numeric(12, 4)),
    ("carrier", sa.String(128)),
    ("numero_reclamo_carrier", sa.String(128)),
    ("sector_responsable", sa.String(80)),
    ("descripcion_problema", sa.Text()),
]


def upgrade() -> None:
    # Guardia de datos previos: las filas escritas antes de esta migración las generó el parser viejo,
    # que guardaba "horas netas" en MINUTOS y dejaba "-"/vacío como numero_evento. La tabla estaba vacía
    # en dev y prod el 2026-10-05, así que normalmente no hace nada; si hubiera filas se convierten acá,
    # ANTES de crear columnas nuevas, para que luego no se pueda confundir una fila migrada con una
    # ingerida por el parser nuevo (que ya guarda horas decimales).
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM app.reclamos")).scalar_one() > 0:
        op.execute("UPDATE app.reclamos SET horas_netas = horas_netas / 60.0")
        op.execute("UPDATE app.reclamos SET numero_evento = NULL WHERE btrim(numero_evento) IN ('', '-')")
    op.create_table(
        "sla_ingestas",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("fecha_corte", sa.Date(), nullable=False),
        sa.Column("hash_servicios", sa.String(64), nullable=False),
        sa.Column("hash_reclamos", sa.String(64), nullable=False),
        sa.Column("usuario", sa.String(128)),
        sa.Column("reclamos_insertados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reclamos_actualizados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("servicios_snapshot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("report_history_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("hash_servicios", "hash_reclamos", name="uq_sla_ingestas_hashes"),
        schema="app",
    )
    op.create_index("ix_sla_ingestas_fecha_corte", "sla_ingestas", ["fecha_corte"], schema="app")
    op.create_table(
        "servicio_sla_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("numero_linea", sa.String(64), nullable=False),
        sa.Column("numero_primer_servicio", sa.String(64)),
        sa.Column("fecha_corte", sa.Date(), nullable=False),
        sa.Column("nombre_cliente", sa.String(128)),
        sa.Column("tipo_servicio", sa.String(80)),
        sa.Column("sla_prometido", sa.Numeric(6, 3)),
        sa.Column("sla_entregado", sa.Numeric(9, 6)),
        sa.Column("horas_reclamos_mes", sa.Numeric(12, 4)),
        sa.Column("horas_carriers_mes", sa.Numeric(12, 4)),
        sa.Column("horas_reclamos_todos", sa.Numeric(12, 4)),
        sa.Column("horas_carriers_todos", sa.Numeric(12, 4)),
        sa.Column("horas_restantes", sa.Numeric(12, 4)),
        sa.Column("abono_usd", sa.Numeric(14, 2)),
        sa.Column("cantidad_reclamos_todos", sa.Integer()),
        sa.Column("ingesta_id", sa.BigInteger()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("numero_linea", "fecha_corte", name="uq_sla_snapshot_linea_corte"),
        schema="app",
    )
    for col in ("numero_linea", "numero_primer_servicio", "fecha_corte"):
        op.create_index(f"ix_servicio_sla_snapshot_{col}", "servicio_sla_snapshot", [col], schema="app")
    for nombre, tipo in _NUEVAS:
        op.add_column("reclamos", sa.Column(nombre, tipo, nullable=True), schema="app")
    op.add_column("reclamos", sa.Column("ingesta_id", sa.BigInteger(),
                  sa.ForeignKey("app.sla_ingestas.id", ondelete="SET NULL")), schema="app")
    op.add_column("reclamos", sa.Column("first_seen_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()), schema="app")
    op.add_column("reclamos", sa.Column("last_seen_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()), schema="app")
    op.alter_column("reclamos", "horas_netas", type_=sa.Numeric(12, 4), schema="app")
    op.alter_column("reclamos", "tipo_solucion", type_=sa.String(160), schema="app")
    op.create_index("ix_reclamos_numero_primer_servicio", "reclamos", ["numero_primer_servicio"], schema="app")
    op.create_index("ix_reclamos_grupo_cierre", "reclamos", ["grupo_cierre"], schema="app")
    # No existía índice sobre fecha_inicio (verificado con \d app.reclamos el 2026-10-05).
    op.create_index("ix_reclamos_fecha_inicio", "reclamos", ["fecha_inicio"], schema="app")
    op.execute("""
        CREATE VIEW app.v_eventos_sla AS
        SELECT numero_evento,
               COUNT(*) AS reclamos,
               COUNT(DISTINCT numero_linea) AS servicios_afectados,
               MIN(fecha_inicio) AS inicio,
               MAX(fecha_cierre) AS cierre,
               SUM(horas_netas) AS horas_netas,
               MODE() WITHIN GROUP (ORDER BY grupo_cierre) AS grupo_predominante
        FROM app.reclamos
        WHERE numero_evento IS NOT NULL
        GROUP BY numero_evento
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS app.v_eventos_sla")
    op.drop_index("ix_reclamos_fecha_inicio", table_name="reclamos", schema="app")
    op.drop_index("ix_reclamos_grupo_cierre", table_name="reclamos", schema="app")
    op.drop_index("ix_reclamos_numero_primer_servicio", table_name="reclamos", schema="app")
    op.alter_column("reclamos", "tipo_solucion", type_=sa.String(80), schema="app")
    op.alter_column("reclamos", "horas_netas", type_=sa.Numeric(10, 2), schema="app")
    for nombre in ("last_seen_at", "first_seen_at", "ingesta_id"):
        op.drop_column("reclamos", nombre, schema="app")
    for nombre, _ in reversed(_NUEVAS):
        op.drop_column("reclamos", nombre, schema="app")
    op.drop_table("servicio_sla_snapshot", schema="app")
    op.drop_table("sla_ingestas", schema="app")
