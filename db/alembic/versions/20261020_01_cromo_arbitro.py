# Nombre de archivo: 20261020_01_cromo_arbitro.py
# Ubicación de archivo: db/alembic/versions/20261020_01_cromo_arbitro.py
# Descripción: Tablas del árbitro de Cromo (reglas, propuestas, evidencia de camino, evaluaciones) y origen AUTO en el override de ODF

"""Árbitro de Cromo

Revision ID: 20261020_01
Revises: 20261017_04
Create Date: 2026-10-20

Cambios:
- ``app.cromo_regla_correccion``: una fila por regla con modo (APAGADA/SOMBRA/AUTO), umbral y
  presupuesto por corrida. Seed idempotente de las 5 reglas en SOMBRA con umbral 90.
- ``app.cromo_propuesta``: propuestas del árbitro. Índice único parcial: a lo sumo una abierta
  (PROPUESTA/EN_OBSERVACION) por (regla, objeto_tipo, objeto_id).
- ``app.cromo_evidencia_camino``: último camino observado por (servicio, pelo). FK dura sólo a
  ``app.servicios`` (maestro propio); ``pelo_n_id`` es referencia blanda a Cromo.
- ``app.cromo_arbitro_evaluacion``: cola/seguimiento de evaluaciones lanzadas desde la UI.
- ``app.cromo_servicio_odf_override``: columnas ``origen`` (MANUAL/AUTO) y ``propuesta_id``; el CHECK de
  ``categoria_causa`` suma ``EVIDENCIA_CAMINO``.
- Vocabularios cerrados como Text + CHECK (nunca ENUM). ``downgrade()`` borra primero las filas
  ``EVIDENCIA_CAMINO`` (datos del árbitro) y restaura el CHECK original.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261020_01"
down_revision = "20261017_04"
branch_labels = None
depends_on = None

_CK_CATEGORIA = "ck_cromo_servicio_odf_override_categoria_causa_valida"
_CATEGORIAS_ORIGINALES = (
    "'OLT_PON_COMPARTIDO', 'EQUIPO_DOMICILIO_CLIENTE', 'SWITCH_COMPARTIDO_REVISAR', 'SIN_SENAL_PROV', 'OTRO'"
)
_MODOS = "'APAGADA', 'SOMBRA', 'AUTO'"
_DISPAROS = "'INGESTA', 'REGISTRADOR', 'VIEWER', 'NORMALIZADOR'"

_REGLAS = (
    ("ODF_POR_CAMINO", "Asocia la ODF a un servicio sin ODF cuando el camino vivo de su pelo termina en ella"),
    ("CONTRADICCION_SERVICIO", "Informa servicios cuyo camino contradice la ODF o el cable asociado"),
    ("GEMELO_VACIO", "Fusiona una botella sin cables con su gemela que sí los tiene"),
    ("GEMELO_OPERATIVO", "Fusiona botellas gemelas que ambas tienen cables, con evidencia coincidente"),
    ("ODF_GEMELA_ISLA", "Informa ODF gemelas aisladas (isla) que duplican a otra ODF con cables"),
)


def upgrade() -> None:
    op.create_table(
        "cromo_regla_correccion",
        sa.Column("codigo", sa.Text(), primary_key=True),
        sa.Column("modo", sa.Text(), nullable=False, server_default="SOMBRA"),
        sa.Column("umbral", sa.SmallInteger(), nullable=False, server_default="90"),
        sa.Column("presupuesto_por_corrida", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("actualizado_por", sa.String(128), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(f"modo IN ({_MODOS})", name="ck_cromo_regla_correccion_modo_valido"),
        sa.CheckConstraint("umbral BETWEEN 0 AND 100", name="ck_cromo_regla_correccion_umbral_valido"),
        sa.CheckConstraint(
            "presupuesto_por_corrida >= 0", name="ck_cromo_regla_correccion_presupuesto_valido"
        ),
        schema="app",
    )
    for codigo, descripcion in _REGLAS:
        op.execute(
            sa.text(
                "INSERT INTO app.cromo_regla_correccion (codigo, descripcion) "
                "VALUES (:c, :d) ON CONFLICT DO NOTHING"
            ).bindparams(c=codigo, d=descripcion)
        )

    op.create_table(
        "cromo_propuesta",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("regla", sa.Text(), nullable=False),
        sa.Column("objeto_tipo", sa.Text(), nullable=False),
        sa.Column("objeto_id", sa.BigInteger(), nullable=False),
        sa.Column("accion", sa.Text(), nullable=False),
        sa.Column("parametros", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confianza", sa.SmallInteger(), nullable=False),
        sa.Column("senales", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidencia_hash", sa.String(64), nullable=False),
        sa.Column("estado", sa.Text(), nullable=False),
        sa.Column("modo_al_evaluar", sa.Text(), nullable=False),
        sa.Column("disparo", sa.Text(), nullable=False),
        sa.Column("reversion", postgresql.JSONB(), nullable=True),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.Column("creada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "actualizada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("decidida_por", sa.String(128), nullable=True),
        sa.Column("decidida_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aplicada_en", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["regla"], ["app.cromo_regla_correccion.codigo"], name="fk_cromo_propuesta_regla"),
        sa.CheckConstraint(
            "objeto_tipo IN ('SERVICIO', 'BOTELLA', 'ODF', 'CABLE')",
            name="ck_cromo_propuesta_objeto_tipo_valido",
        ),
        sa.CheckConstraint(
            "accion IN ('ASOCIAR_ODF', 'FUSIONAR_GEMELO', 'INFORMAR')", name="ck_cromo_propuesta_accion_valida"
        ),
        sa.CheckConstraint("confianza BETWEEN 0 AND 100", name="ck_cromo_propuesta_confianza_valida"),
        sa.CheckConstraint(
            "estado IN ('PROPUESTA', 'EN_OBSERVACION', 'APLICADA', 'RECHAZADA', 'REVERTIDA', 'OBSOLETA')",
            name="ck_cromo_propuesta_estado_valido",
        ),
        sa.CheckConstraint(f"modo_al_evaluar IN ({_MODOS})", name="ck_cromo_propuesta_modo_al_evaluar_valido"),
        sa.CheckConstraint(f"disparo IN ({_DISPAROS})", name="ck_cromo_propuesta_disparo_valido"),
        schema="app",
    )
    op.create_index(
        "ux_cromo_propuesta_abierta",
        "cromo_propuesta",
        ["regla", "objeto_tipo", "objeto_id"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("estado IN ('PROPUESTA', 'EN_OBSERVACION')"),
    )
    op.create_index("ix_cromo_propuesta_estado_regla", "cromo_propuesta", ["estado", "regla"], schema="app")

    op.create_table(
        "cromo_evidencia_camino",
        sa.Column(
            "servicio_id",
            sa.Integer(),
            sa.ForeignKey("app.servicios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pelo_n_id", sa.BigInteger(), nullable=False),
        sa.Column("completo", sa.Boolean(), nullable=False),
        sa.Column("extremos", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("pelos_camino", postgresql.ARRAY(sa.BigInteger()), nullable=True),
        sa.Column("fuente", sa.Text(), nullable=False),
        sa.Column("generado_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("servicio_id", "pelo_n_id", name="pk_cromo_evidencia_camino"),
        sa.CheckConstraint(
            "fuente IN ('SLACK', 'WEB', 'AUDITORIA_GLOBAL')", name="ck_cromo_evidencia_camino_fuente_valida"
        ),
        schema="app",
    )

    op.create_table(
        "cromo_arbitro_evaluacion",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("disparo", sa.Text(), nullable=False),
        sa.Column("alcance", postgresql.JSONB(), nullable=False),
        sa.Column("reglas", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("estado", sa.Text(), nullable=False),
        sa.Column("resumen", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("solicitada_por", sa.String(128), nullable=True),
        sa.Column("encolada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("iniciada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminada_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"disparo IN ({_DISPAROS})", name="ck_cromo_arbitro_evaluacion_disparo_valido"),
        sa.CheckConstraint(
            "estado IN ('EN_COLA', 'EN_CURSO', 'OK', 'OMITIDA', 'FALLIDA')",
            name="ck_cromo_arbitro_evaluacion_estado_valido",
        ),
        schema="app",
    )
    op.create_index(
        "ix_cromo_arbitro_evaluacion_encolada_en",
        "cromo_arbitro_evaluacion",
        [sa.text("encolada_en DESC")],
        schema="app",
    )

    op.add_column(
        "cromo_servicio_odf_override",
        sa.Column("origen", sa.Text(), nullable=False, server_default="MANUAL"),
        schema="app",
    )
    op.add_column(
        "cromo_servicio_odf_override",
        sa.Column(
            "propuesta_id",
            sa.BigInteger(),
            sa.ForeignKey("app.cromo_propuesta.id", ondelete="SET NULL", name="fk_cromo_servicio_odf_override_propuesta"),
            nullable=True,
        ),
        schema="app",
    )
    op.create_check_constraint(
        "ck_cromo_servicio_odf_override_origen_valido",
        "cromo_servicio_odf_override",
        "origen IN ('MANUAL', 'AUTO')",
        schema="app",
    )
    op.drop_constraint(_CK_CATEGORIA, "cromo_servicio_odf_override", schema="app", type_="check")
    op.create_check_constraint(
        _CK_CATEGORIA,
        "cromo_servicio_odf_override",
        f"categoria_causa IN ({_CATEGORIAS_ORIGINALES}, 'EVIDENCIA_CAMINO')",
        schema="app",
    )


def downgrade() -> None:
    # Las filas EVIDENCIA_CAMINO son datos del árbitro: se borran antes de restaurar el CHECK original.
    op.execute("DELETE FROM app.cromo_servicio_odf_override WHERE categoria_causa = 'EVIDENCIA_CAMINO'")
    op.drop_constraint(_CK_CATEGORIA, "cromo_servicio_odf_override", schema="app", type_="check")
    op.create_check_constraint(
        _CK_CATEGORIA,
        "cromo_servicio_odf_override",
        f"categoria_causa IN ({_CATEGORIAS_ORIGINALES})",
        schema="app",
    )
    op.drop_constraint(
        "ck_cromo_servicio_odf_override_origen_valido", "cromo_servicio_odf_override", schema="app", type_="check"
    )
    op.drop_column("cromo_servicio_odf_override", "propuesta_id", schema="app")
    op.drop_column("cromo_servicio_odf_override", "origen", schema="app")
    op.drop_index("ix_cromo_arbitro_evaluacion_encolada_en", table_name="cromo_arbitro_evaluacion", schema="app")
    op.drop_table("cromo_arbitro_evaluacion", schema="app")
    op.drop_table("cromo_evidencia_camino", schema="app")
    op.drop_index("ix_cromo_propuesta_estado_regla", table_name="cromo_propuesta", schema="app")
    op.drop_index("ux_cromo_propuesta_abierta", table_name="cromo_propuesta", schema="app")
    op.drop_table("cromo_propuesta", schema="app")
    op.drop_table("cromo_regla_correccion", schema="app")
