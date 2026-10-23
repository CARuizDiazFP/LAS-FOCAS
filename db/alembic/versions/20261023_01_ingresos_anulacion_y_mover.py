# Nombre de archivo: 20261023_01_ingresos_anulacion_y_mover.py
# Ubicación de archivo: db/alembic/versions/20261023_01_ingresos_anulacion_y_mover.py
# Descripción: Baja lógica de app.ingresos (anulado_at/por/motivo) y origen del movimiento en app.ingresos_correcciones

"""Anulación y mover de ingresos desde el portal

Un ingreso puede quedar en la Cámara equivocada (Fontaine ID mal tipeado, reescritura en el hilo,
"Forzar ingreso" con la cámara errónea) o directamente no haber ocurrido. El portal (sólo admin)
pasa a poder *mover* el ingreso a otra Cámara o *anularlo*.

- ``app.ingresos``: ``anulado_at`` (timestamptz), ``anulado_por`` (varchar 128) y ``anulado_motivo``
  (text), todas nullable. Anular es baja lógica: la fila se conserva y los lectores filtran
  ``anulado_at IS NULL`` (``Ingreso.vigente()``). Un CHECK exige que una fila anulada tenga autor y
  motivo.
- ``app.ingresos_correcciones``: ``camara_id_anterior`` (FK a ``app.camaras``, ``ON DELETE SET
  NULL``, igual que ``camara_id_resuelta``) y ``cromo_botella_id_anterior`` (bigint sin FK: es
  histórico y la botella puede desaparecer en una reingesta), para auditar de dónde se movió.

``ADD COLUMN`` sin default no reescribe filas ni dispara el trigger append-only
(``trg_ingresos_correcciones_inmutable``, ``BEFORE UPDATE OR DELETE ... FOR EACH ROW``); ``DROP
COLUMN`` tampoco.

Downgrade: si hay ingresos anulados, bajar la migración los "resucitaría" como vigentes (OCUPADA
sugerida, egresos que cierran un ingreso que nunca ocurrió); si hay correcciones con origen
registrado, se perdería auditoría. En ambos casos el downgrade falla con un mensaje explícito.

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

    op.add_column(
        "ingresos_correcciones",
        sa.Column(
            "camara_id_anterior",
            sa.Integer(),
            sa.ForeignKey("app.camaras.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "ingresos_correcciones",
        sa.Column("cromo_botella_id_anterior", sa.BigInteger(), nullable=True),
        schema=_SCHEMA,
    )


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
            f"SELECT count(*) FROM {_SCHEMA}.ingresos_correcciones "
            "WHERE camara_id_anterior IS NOT NULL OR cromo_botella_id_anterior IS NOT NULL"
        )
    ).scalar()
    if con_origen:
        raise RuntimeError(
            f"{_SCHEMA}.ingresos_correcciones tiene {con_origen} fila(s) con el origen de un movimiento: "
            "bajar la migración perdería auditoría. Downgrade abortado."
        )

    op.drop_column("ingresos_correcciones", "cromo_botella_id_anterior", schema=_SCHEMA)
    op.drop_column("ingresos_correcciones", "camara_id_anterior", schema=_SCHEMA)
    op.drop_constraint(_CHECK_ANULADO, "ingresos", type_="check", schema=_SCHEMA)
    op.drop_column("ingresos", "anulado_motivo", schema=_SCHEMA)
    op.drop_column("ingresos", "anulado_por", schema=_SCHEMA)
    op.drop_column("ingresos", "anulado_at", schema=_SCHEMA)
