# Nombre de archivo: 20261023_01_ingresos_anulacion_y_mover.py
# Ubicación de archivo: db/alembic/versions/20261023_01_ingresos_anulacion_y_mover.py
# Descripción: Baja lógica de app.ingresos (anulado_at/por/motivo), origen del movimiento en app.ingresos_correcciones y fin de sus FKs (ids históricos)

"""Anulación y mover de ingresos desde el portal

Un ingreso puede quedar en la Cámara equivocada (Fontaine ID mal tipeado, reescritura en el hilo,
"Forzar ingreso" con la cámara errónea) o directamente no haber ocurrido. El portal (sólo admin)
pasa a poder *mover* el ingreso a otra Cámara o *anularlo*.

- ``app.ingresos``: ``anulado_at`` (timestamptz), ``anulado_por`` (varchar 128) y ``anulado_motivo``
  (text), todas nullable. Anular es baja lógica: la fila se conserva y los lectores filtran
  ``anulado_at IS NULL`` (``Ingreso.vigente()``). Un CHECK exige que una fila anulada tenga autor y
  motivo.
- ``app.ingresos_correcciones``: ``camara_id_anterior`` (integer) y ``cromo_botella_id_anterior``
  (bigint), sin FK, para auditar de dónde se movió un ingreso.
- ``app.ingresos_correcciones`` deja de tener FKs: se eliminan ``*_camara_id_resuelta_fkey``,
  ``*_cromo_botella_id_resuelta_fkey`` e ``*_ingreso_id_fkey`` (las tres ``ON DELETE SET NULL``).
  En una tabla de auditoría inmutable los ids son dato histórico, no referencias vivas: el trigger
  append-only (``trg_ingresos_correcciones_inmutable``, ``BEFORE UPDATE OR DELETE ... FOR EACH ROW``)
  hace ``RAISE`` también ante el ``UPDATE ... SET NULL`` que ejecuta la FK, así que borrar o unificar
  una cámara (``camara_merge_service.unificar_camaras`` borra la secundaria), una botella o un
  ingreso referenciado por la auditoría fallaba. Con "mover" toda cámara de origen quedaría
  referenciada. Las columnas y sus índices se conservan; la fila guarda el id original.

``ADD COLUMN`` sin default no reescribe filas ni dispara el trigger; ``DROP COLUMN`` y ``DROP
CONSTRAINT`` tampoco.

Downgrade: si hay ingresos anulados, bajar la migración los "resucitaría" como vigentes (OCUPADA
sugerida, egresos que cierran un ingreso que nunca ocurrió); si hay correcciones con origen
registrado, se perdería auditoría; si hay ids de auditoría que ya no existen en su tabla, las FKs no
se pueden recrear (y la auditoría no se puede mutar). En los tres casos el downgrade falla con un
mensaje explícito. Si no, recrea las tres FKs como estaban (``ON DELETE SET NULL``).

Revision ID: 20261023_01
Revises: 20261021_01
Create Date: 2026-10-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261023_01"
down_revision = "20261021_01"
branch_labels = None
depends_on = None

_SCHEMA = "app"
_CHECK_ANULADO = "ck_ingresos_anulado_coherente"
_AUDITORIA = "ingresos_correcciones"
# (nombre de la FK, columna local, tabla referida, columna referida) — nombres reales en dev/prod
# (los generó Postgres en `20260923_01`).
_FKS_AUDITORIA = (
    ("ingresos_correcciones_camara_id_resuelta_fkey", "camara_id_resuelta", "camaras", "id"),
    ("ingresos_correcciones_cromo_botella_id_resuelta_fkey", "cromo_botella_id_resuelta", "cromo_botellas", "n_id"),
    ("ingresos_correcciones_ingreso_id_fkey", "ingreso_id", "ingresos", "id"),
)


def upgrade() -> None:
    op.add_column("ingresos", sa.Column("anulado_at", sa.DateTime(timezone=True), nullable=True), schema=_SCHEMA)
    op.add_column("ingresos", sa.Column("anulado_por", sa.String(length=128), nullable=True), schema=_SCHEMA)
    op.add_column("ingresos", sa.Column("anulado_motivo", sa.Text(), nullable=True), schema=_SCHEMA)
    op.create_check_constraint(
        _CHECK_ANULADO,
        "ingresos",
        "anulado_at IS NULL OR (anulado_por IS NOT NULL AND anulado_motivo IS NOT NULL)",
        schema=_SCHEMA,
    )

    op.add_column(_AUDITORIA, sa.Column("camara_id_anterior", sa.Integer(), nullable=True), schema=_SCHEMA)
    op.add_column(_AUDITORIA, sa.Column("cromo_botella_id_anterior", sa.BigInteger(), nullable=True), schema=_SCHEMA)
    for nombre, _columna, _tabla, _referida in _FKS_AUDITORIA:
        op.drop_constraint(nombre, _AUDITORIA, type_="foreignkey", schema=_SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    anulados = bind.execute(
        sa.text(f"SELECT count(*) FROM {_SCHEMA}.ingresos WHERE anulado_at IS NOT NULL")
    ).scalar()
    if anulados:
        raise RuntimeError(
            f"{_SCHEMA}.ingresos tiene {anulados} ingreso(s) anulado(s): bajar la migración los volvería "
            "vigentes. Downgrade abortado."
        )
    con_origen = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {_SCHEMA}.{_AUDITORIA} "
            "WHERE camara_id_anterior IS NOT NULL OR cromo_botella_id_anterior IS NOT NULL"
        )
    ).scalar()
    if con_origen:
        raise RuntimeError(
            f"{_SCHEMA}.{_AUDITORIA} tiene {con_origen} fila(s) con el origen de un movimiento: "
            "bajar la migración perdería auditoría. Downgrade abortado."
        )

    for _nombre, columna, tabla, referida in _FKS_AUDITORIA:
        huerfanas = bind.execute(
            sa.text(
                f"SELECT count(*) FROM {_SCHEMA}.{_AUDITORIA} a WHERE a.{columna} IS NOT NULL "
                f"AND NOT EXISTS (SELECT 1 FROM {_SCHEMA}.{tabla} t WHERE t.{referida} = a.{columna})"
            )
        ).scalar()
        if huerfanas:
            raise RuntimeError(
                f"{_SCHEMA}.{_AUDITORIA}.{columna} tiene {huerfanas} id(s) que ya no existen en "
                f"{_SCHEMA}.{tabla}: la FK no se puede recrear y la auditoría no se puede mutar. "
                "Downgrade abortado."
            )

    for nombre, columna, tabla, referida in _FKS_AUDITORIA:
        op.create_foreign_key(
            nombre,
            _AUDITORIA,
            tabla,
            [columna],
            [referida],
            source_schema=_SCHEMA,
            referent_schema=_SCHEMA,
            ondelete="SET NULL",
        )
    op.drop_column(_AUDITORIA, "cromo_botella_id_anterior", schema=_SCHEMA)
    op.drop_column(_AUDITORIA, "camara_id_anterior", schema=_SCHEMA)
    op.drop_constraint(_CHECK_ANULADO, "ingresos", type_="check", schema=_SCHEMA)
    op.drop_column("ingresos", "anulado_motivo", schema=_SCHEMA)
    op.drop_column("ingresos", "anulado_por", schema=_SCHEMA)
    op.drop_column("ingresos", "anulado_at", schema=_SCHEMA)
