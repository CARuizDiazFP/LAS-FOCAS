# Nombre de archivo: 20260908_01_cromo_servicio_odf_override.py
# Ubicación de archivo: db/alembic/versions/20260908_01_cromo_servicio_odf_override.py
# Descripción: Tabla escudo cromo_servicio_odf_override (asociación manual Servicio→ODF de Cromo)
# + índice btree parcial de performance sobre cromo_odf_conectores.servicio_resuelto

"""Tabla cromo_servicio_odf_override + índice parcial cromo_odf_conectores.servicio_resuelto

Revision ID: 20260908_01
Revises: 20260907_01
Create Date: 2026-09-08

Cambios (Tarea 1 del gestor "Servicios sin ODF" — asociar manualmente un Servicio a su ODF real
en Cromo cuando el detector automático de las tareas siguientes no puede resolverlo):

- Nueva tabla ``app.cromo_servicio_odf_override``: cada fila es un evento de asociación manual de
  un operador. ``servicio_id`` es FK DURA a ``app.servicios.id`` (``ondelete="CASCADE"``) — a
  diferencia del resto de las referencias cruzadas de Cromo, acá sí corresponde integridad
  referencial real porque ``app.servicios`` es un maestro propio de este repo, no un objeto de
  Cromo. ``odf_n_id``/``pelo_n_id`` siguen el criterio "sin FK dura" ya establecido para todo lo
  que referencia a Cromo (ver ``CromoCable``/``CromoBotellaAlias`` en ``db/models/cromo.py``):
  Cromo puede reingerir/renumerar, y este repo no debe bloquear un INSERT acá por eso.
  ``pelo_n_id`` es ``NULL``able a propósito: ``NULL`` significa "asociado a la ODF en general,
  sin pin a una posición física específica" — limitación de alcance ya aceptada para esta primera
  iteración.
- Sin ``UNIQUE`` en ``servicio_id`` a propósito: permite reasociar sin perder historial (cada fila
  es un evento, no el estado actual único de un Servicio).
- ``categoria_causa``/``subcategoria``/``senal_direccion`` son ``Text`` + ``CHECK`` (nunca ENUM de
  Postgres, mismo criterio ya usado en el resto del repo — ver ``ck_cromo_botella_alias_accion_valida``
  en ``20260819_01``): agregar un valor nuevo es un ``ALTER TABLE ... DROP/ADD CONSTRAINT``, no un
  ``ALTER TYPE`` irreversible.
- Índices propios: ``ix_cromo_servicio_odf_override_servicio_id`` sobre ``servicio_id`` (acceso
  "overrides de este Servicio") e ``ix_cromo_servicio_odf_override_odf_n_id`` sobre ``odf_n_id``
  (acceso "Servicios asociados manualmente a esta ODF").

- **Fix de performance verificado real, mismo archivo**: índice btree PARCIAL nuevo
  ``ix_cromo_odf_conectores_servicio_resuelto`` sobre
  ``cromo_odf_conectores(servicio_resuelto) WHERE servicio_resuelto IS NOT NULL``. La query del
  universo "Activos verificables sin ODF" (detector de las tareas siguientes) hace 3 NOT EXISTS
  contra ``cromo_odf_conectores.servicio_resuelto`` sin ningún índice utilizable — Seq Scan
  repetido sobre las ~205k filas de la tabla. Parcial porque sólo 5,36% de las filas
  (10986/204840, medido real contra ``lasfocasdev-postgres`` el 2026-09-08) tiene
  ``servicio_resuelto IS NOT NULL``; un índice completo desperdiciaría espacio y no cambiaría el
  plan (Postgres igual preferiría Seq Scan con baja selectividad si no fuera parcial). Ver
  ``EXPLAIN (ANALYZE, TIMING OFF)`` antes/después documentado en el reporte de la Tarea 1
  (``.superpowers/sdd/tambiem-validemos-domicilios-extraidos-robust-swing/task-1-report.md``).

Downgrade: dropea el índice parcial de ``cromo_odf_conectores``, los 3 CHECK constraints, los 2
índices propios y la tabla ``cromo_servicio_odf_override``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260908_01"
down_revision = "20260907_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cromo_servicio_odf_override",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "servicio_id",
            sa.Integer(),
            sa.ForeignKey("app.servicios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("odf_n_id", sa.BigInteger(), nullable=False),
        sa.Column("pelo_n_id", sa.BigInteger(), nullable=True),
        sa.Column("categoria_causa", sa.Text(), nullable=False),
        sa.Column("subcategoria", sa.Text(), nullable=True),
        sa.Column("senal_direccion", sa.Text(), nullable=True),
        sa.Column("usuario", sa.String(length=128), nullable=False),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="app",
    )
    op.create_index(
        "ix_cromo_servicio_odf_override_servicio_id",
        "cromo_servicio_odf_override",
        ["servicio_id"],
        schema="app",
    )
    op.create_index(
        "ix_cromo_servicio_odf_override_odf_n_id",
        "cromo_servicio_odf_override",
        ["odf_n_id"],
        schema="app",
    )
    op.create_check_constraint(
        "ck_cromo_servicio_odf_override_categoria_causa_valida",
        "cromo_servicio_odf_override",
        "categoria_causa IN ('OLT_PON_COMPARTIDO', 'EQUIPO_DOMICILIO_CLIENTE', "
        "'SWITCH_COMPARTIDO_REVISAR', 'SIN_SENAL_PROV', 'OTRO')",
        schema="app",
    )
    op.create_check_constraint(
        "ck_cromo_servicio_odf_override_subcategoria_valida",
        "cromo_servicio_odf_override",
        "subcategoria IS NULL OR subcategoria IN "
        "('PELO_SIN_CONECTOR_ODF', 'AUSENTE_RED_CROMO', 'BAJA_LOGICA_HEREDADA')",
        schema="app",
    )
    op.create_check_constraint(
        "ck_cromo_servicio_odf_override_senal_direccion_valida",
        "cromo_servicio_odf_override",
        "senal_direccion IS NULL OR senal_direccion IN "
        "('coincide', 'no_coincide', 'no_se_pudo_comparar')",
        schema="app",
    )

    # Fix de performance verificado real — ver docstring del módulo.
    op.create_index(
        "ix_cromo_odf_conectores_servicio_resuelto",
        "cromo_odf_conectores",
        ["servicio_resuelto"],
        schema="app",
        postgresql_where=sa.text("servicio_resuelto IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cromo_odf_conectores_servicio_resuelto", table_name="cromo_odf_conectores", schema="app"
    )
    op.drop_constraint(
        "ck_cromo_servicio_odf_override_senal_direccion_valida",
        "cromo_servicio_odf_override",
        schema="app",
        type_="check",
    )
    op.drop_constraint(
        "ck_cromo_servicio_odf_override_subcategoria_valida",
        "cromo_servicio_odf_override",
        schema="app",
        type_="check",
    )
    op.drop_constraint(
        "ck_cromo_servicio_odf_override_categoria_causa_valida",
        "cromo_servicio_odf_override",
        schema="app",
        type_="check",
    )
    op.drop_index(
        "ix_cromo_servicio_odf_override_odf_n_id", table_name="cromo_servicio_odf_override", schema="app"
    )
    op.drop_index(
        "ix_cromo_servicio_odf_override_servicio_id", table_name="cromo_servicio_odf_override", schema="app"
    )
    op.drop_table("cromo_servicio_odf_override", schema="app")
