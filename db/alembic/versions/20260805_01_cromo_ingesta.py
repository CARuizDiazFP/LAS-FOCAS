# Nombre de archivo: 20260805_01_cromo_ingesta.py
# Ubicación de archivo: db/alembic/versions/20260805_01_cromo_ingesta.py
# Descripción: Crea las tablas app.cromo_* (catálogo, auditoría e inventario) para la Etapa 2 de ingesta desde Cromo Red

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260805_01"
down_revision = "20260713_01"
branch_labels = None
depends_on = None


tipo_asociacion_enum = postgresql.ENUM(
    "CLIENTE",
    "TRUNK_DWDM",
    "OLT_LASER",
    "INFRA",
    "LIBRE",
    "INDETERMINADO",
    name="cromo_tipo_asociacion_pelo",
    schema="app",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    tipo_asociacion_enum.create(bind, checkfirst=True)

    # ── Catálogo ─────────────────────────────────────────────────────────────
    op.create_table(
        "cromo_clases",
        sa.Column("clase", sa.SmallInteger(), primary_key=True),
        sa.Column("etiqueta", sa.Text(), nullable=True),
        sa.Column("entidad", sa.Text(), nullable=False),
        sa.Column("ingerible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("homologada", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("motivo_exclusion", sa.Text(), nullable=True),
        sa.Column("count_cromo", sa.BigInteger(), nullable=True),
        sa.Column("count_fecha", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )

    # Seed verificado contra Cromo real el 2026-08-05 (ver docs/Doc Privada/ingesta_cromo.md, capítulos 4 y 12).
    op.execute(
        """
        INSERT INTO app.cromo_clases
            (clase, etiqueta, entidad, ingerible, homologada, motivo_exclusion, count_cromo, count_fecha)
        VALUES
            (68,  '6-1',  'BOTELLA', true,  true,  NULL, 9577,    '2026-08-05'),
            (121, '16-1', 'BOTELLA', true,  true,  NULL, 573,     '2026-08-05'),
            (122, '4-1',  'BOTELLA', true,  true,  NULL, 897,     '2026-08-05'),
            (123, '8-1',  'BOTELLA', true,  true,  NULL, 61,      '2026-08-05'),
            (125, '5-1',  'BOTELLA', true,  true,  NULL, 51,      '2026-08-05'),
            (124, NULL,   'BOTELLA', true,  false, NULL, 20,      '2026-08-05'),
            (120, NULL,   'PARCELA', false, true,  'Parcela catastral, no es planta de FO', 6111729, '2026-08-05'),
            (69,  NULL,   'ODF',     true,  true,  NULL, 7955,    '2026-08-05'),
            (51,  NULL,   'CABLE',   true,  true,  NULL, 33118,   '2026-08-05'),
            (129, NULL,   'TUBO',    true,  true,  NULL, NULL,    NULL),
            (130, NULL,   'PELO',    true,  true,  NULL, NULL,    NULL),
            (132, NULL,   'FUSION',  true,  true,  NULL, NULL,    NULL)
        """
    )

    # ── Auditoría de corridas ────────────────────────────────────────────────
    op.create_table(
        "cromo_ingesta_corridas",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("usuario", sa.String(length=128), nullable=False),
        sa.Column("estado", sa.String(length=32), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("total_objetivo", sa.Integer(), nullable=True),
        sa.Column("leidas", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("creadas", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("actualizadas", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sin_cambios", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("errores", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("refs_colgadas", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("iniciada_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finalizada_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )

    op.create_table(
        "cromo_ingesta_eventos",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "corrida_id",
            sa.BigInteger(),
            sa.ForeignKey("app.cromo_ingesta_corridas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("n_id", sa.BigInteger(), nullable=True),
        sa.Column("clase", sa.SmallInteger(), nullable=True),
        sa.Column("accion", sa.String(length=32), nullable=False),
        sa.Column("detalle", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        schema="app",
    )
    op.create_index(
        "ix_cromo_eventos_corrida", "cromo_ingesta_eventos", ["corrida_id", "id"], schema="app"
    )

    # ── Inventario: botellas ─────────────────────────────────────────────────
    op.create_table(
        "cromo_botellas",
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
        sa.Column("primera_ingesta", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("ultima_ingesta", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("ultima_modificacion", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.create_index(
        "ix_cromo_botellas_legacy",
        "cromo_botellas",
        ["id_legacy"],
        schema="app",
        postgresql_where=sa.text("id_legacy IS NOT NULL"),
    )
    op.create_index(
        "ix_cromo_botellas_geo", "cromo_botellas", ["latitud", "longitud"], schema="app"
    )
    # Índice de expresión (GIN sobre to_tsvector): no expresable con op.create_index/index=True, va crudo.
    op.execute(
        "CREATE INDEX ix_cromo_botellas_nombre ON app.cromo_botellas "
        "USING GIN (to_tsvector('spanish', nombre));"
    )

    # ── Inventario: cables ───────────────────────────────────────────────────
    op.create_table(
        "cromo_cables",
        sa.Column("n_id", sa.BigInteger(), primary_key=True),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("vmax", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=True),
        sa.Column("capacidad", sa.Text(), nullable=True),
        sa.Column("capacidad_pelos", sa.SmallInteger(), nullable=True),
        sa.Column("propietario", sa.Text(), nullable=True),
        sa.Column("jerarquia", sa.Text(), nullable=True),
        sa.Column("tendido", sa.Text(), nullable=True),
        sa.Column("distancia_geo", sa.Numeric(12, 2), nullable=True),
        sa.Column("distancia_real", sa.Numeric(12, 2), nullable=True),
        sa.Column("id_legacy", sa.Text(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("extremo_a_n_id", sa.BigInteger(), nullable=True),
        sa.Column("extremo_a_clase", sa.SmallInteger(), nullable=True),
        sa.Column("extremo_a_legacy", sa.Text(), nullable=True),
        sa.Column("extremo_a_nombre", sa.Text(), nullable=True),
        sa.Column("extremo_b_n_id", sa.BigInteger(), nullable=True),
        sa.Column("extremo_b_clase", sa.SmallInteger(), nullable=True),
        sa.Column("extremo_b_legacy", sa.Text(), nullable=True),
        sa.Column("extremo_b_nombre", sa.Text(), nullable=True),
        sa.Column("pts_raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("payload_raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("vigente", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("primera_ingesta", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("ultima_ingesta", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        schema="app",
    )
    op.create_index("ix_cromo_cables_nombre", "cromo_cables", ["nombre"], schema="app")
    op.create_index(
        "ix_cromo_cables_extremos",
        "cromo_cables",
        ["extremo_a_n_id", "extremo_b_n_id"],
        schema="app",
    )

    # ── Inventario: tubos ────────────────────────────────────────────────────
    op.create_table(
        "cromo_tubos",
        sa.Column("n_id", sa.BigInteger(), primary_key=True),
        sa.Column("cable_n_id", sa.BigInteger(), nullable=False),
        sa.Column("orden", sa.SmallInteger(), nullable=True),
        sa.Column("nombre_color", sa.Text(), nullable=True),
        sa.Column("vigente", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ultima_ingesta", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        schema="app",
    )
    op.create_index("ix_cromo_tubos_cable", "cromo_tubos", ["cable_n_id"], schema="app")

    # ── Inventario: pelos ────────────────────────────────────────────────────
    op.create_table(
        "cromo_pelos",
        sa.Column("n_id", sa.BigInteger(), primary_key=True),
        sa.Column("tubo_n_id", sa.BigInteger(), nullable=False),
        sa.Column("cable_n_id", sa.BigInteger(), nullable=False),
        sa.Column("numero_pelo", sa.Text(), nullable=True),
        sa.Column("orden", sa.SmallInteger(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("servicio_raw", sa.Text(), nullable=True),
        sa.Column("servicio_numero", sa.Text(), nullable=True),
        sa.Column("tipo_asociacion", tipo_asociacion_enum, nullable=False, server_default="LIBRE"),
        sa.Column("vigente", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ultima_ingesta", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        schema="app",
    )
    op.create_index("ix_cromo_pelos_cable", "cromo_pelos", ["cable_n_id"], schema="app")
    op.create_index("ix_cromo_pelos_tubo", "cromo_pelos", ["tubo_n_id"], schema="app")
    op.create_index(
        "ix_cromo_pelos_servicio",
        "cromo_pelos",
        ["servicio_numero"],
        schema="app",
        postgresql_where=sa.text("servicio_numero IS NOT NULL"),
    )

    # ── Inventario: fusiones ─────────────────────────────────────────────────
    op.create_table(
        "cromo_fusiones",
        sa.Column("n_id", sa.BigInteger(), primary_key=True),
        sa.Column("botella_n_id", sa.BigInteger(), nullable=False),
        sa.Column("nombre_par", sa.Text(), nullable=True),
        sa.Column("tipo", sa.Text(), nullable=True),
        sa.Column("pelo_a_n_id", sa.BigInteger(), nullable=True),
        sa.Column("pelo_b_n_id", sa.BigInteger(), nullable=True),
        sa.Column("latitud", sa.Float(), nullable=True),
        sa.Column("longitud", sa.Float(), nullable=True),
        sa.Column("vigente", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ultima_ingesta", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        schema="app",
    )
    op.create_index("ix_cromo_fusiones_botella", "cromo_fusiones", ["botella_n_id"], schema="app")
    op.create_index(
        "ix_cromo_fusiones_pelos", "cromo_fusiones", ["pelo_a_n_id", "pelo_b_n_id"], schema="app"
    )

    # ── Puente hacia el maestro de servicios ─────────────────────────────────
    op.create_table(
        "cromo_servicio_match",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "pelo_n_id",
            sa.BigInteger(),
            sa.ForeignKey("app.cromo_pelos.n_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("servicio_numero", sa.Text(), nullable=False),
        sa.Column("servicio_id", sa.Integer(), sa.ForeignKey("app.servicios.id"), nullable=True),
        sa.Column("metodo", sa.String(length=32), nullable=False),
        sa.Column("confianza", sa.SmallInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        schema="app",
    )
    op.create_index(
        "ix_cromo_match_servicio", "cromo_servicio_match", ["servicio_id"], schema="app"
    )
    op.create_index(
        "ux_cromo_match_pelo_nro",
        "cromo_servicio_match",
        ["pelo_n_id", "servicio_numero"],
        unique=True,
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ux_cromo_match_pelo_nro", table_name="cromo_servicio_match", schema="app")
    op.drop_index("ix_cromo_match_servicio", table_name="cromo_servicio_match", schema="app")
    op.drop_table("cromo_servicio_match", schema="app")

    op.drop_index("ix_cromo_fusiones_pelos", table_name="cromo_fusiones", schema="app")
    op.drop_index("ix_cromo_fusiones_botella", table_name="cromo_fusiones", schema="app")
    op.drop_table("cromo_fusiones", schema="app")

    op.drop_index("ix_cromo_pelos_servicio", table_name="cromo_pelos", schema="app")
    op.drop_index("ix_cromo_pelos_tubo", table_name="cromo_pelos", schema="app")
    op.drop_index("ix_cromo_pelos_cable", table_name="cromo_pelos", schema="app")
    op.drop_table("cromo_pelos", schema="app")

    op.drop_index("ix_cromo_tubos_cable", table_name="cromo_tubos", schema="app")
    op.drop_table("cromo_tubos", schema="app")

    op.drop_index("ix_cromo_cables_extremos", table_name="cromo_cables", schema="app")
    op.drop_index("ix_cromo_cables_nombre", table_name="cromo_cables", schema="app")
    op.drop_table("cromo_cables", schema="app")

    op.execute("DROP INDEX IF EXISTS app.ix_cromo_botellas_nombre;")
    op.drop_index("ix_cromo_botellas_geo", table_name="cromo_botellas", schema="app")
    op.drop_index("ix_cromo_botellas_legacy", table_name="cromo_botellas", schema="app")
    op.drop_table("cromo_botellas", schema="app")

    op.drop_index("ix_cromo_eventos_corrida", table_name="cromo_ingesta_eventos", schema="app")
    op.drop_table("cromo_ingesta_eventos", schema="app")

    op.drop_table("cromo_ingesta_corridas", schema="app")

    op.drop_table("cromo_clases", schema="app")

    tipo_asociacion_enum.drop(op.get_bind(), checkfirst=True)
