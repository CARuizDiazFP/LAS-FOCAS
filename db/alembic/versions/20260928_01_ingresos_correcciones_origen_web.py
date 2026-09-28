# Nombre de archivo: 20260928_01_ingresos_correcciones_origen_web.py
# Ubicación de archivo: db/alembic/versions/20260928_01_ingresos_correcciones_origen_web.py
# Descripción: Origen (slack/web) y actor web en app.ingresos_correcciones, para auditar el egreso registrado desde el panel

"""Origen web en ingresos_correcciones

Hasta ahora toda corrección de ingresos venía de un comando de Slack, y la tabla lo exigía:
`actor_slack_user_id`, `canal_id` y `mensaje_ts` eran NOT NULL. El botón "Registrar egreso" del
panel web (vista Ingresos del Servicio) escribe en el mismo log de auditoría — mismo criterio que
los comandos de Slack: una fila por invocación, exitosa o no — pero no tiene ninguno de esos tres
datos.

- `origen` (`'slack'` | `'web'`, default `'slack'`): las filas existentes quedan como `'slack'`.
- `actor_web_usuario`: usuario del panel que ejecutó la acción.
- Las tres columnas de Slack pasan a nullable, y un CHECK mantiene la garantía original para las
  filas de Slack y exige `actor_web_usuario` para las web — relajar el NOT NULL sin el CHECK
  permitiría una fila de Slack sin actor, que es justo lo que la auditoría no puede tener.

`ADD COLUMN ... DEFAULT` no dispara el trigger append-only (`trg_ingresos_correcciones_inmutable`,
BEFORE UPDATE OR DELETE a nivel de fila): Postgres completa el default sin ejecutar un UPDATE.

Downgrade: si ya existen filas `origen='web'`, no se pueden descartar (el trigger bloquea el DELETE
y borrar auditoría sería peor que no poder bajar la migración) ni dejar con NULL en columnas
NOT NULL — el downgrade falla con un mensaje explícito en vez de perder datos en silencio.

Revision ID: 20260928_01
Revises: 20260923_03
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_01"
down_revision = "20260923_03"
branch_labels = None
depends_on = None

_TABLA = "ingresos_correcciones"
_SCHEMA = "app"
_CHECK_ORIGEN = "ck_ingresos_correcciones_origen_actor"
_COLUMNAS_SLACK = ("actor_slack_user_id", "canal_id", "mensaje_ts")


def upgrade() -> None:
    op.add_column(
        _TABLA,
        sa.Column("origen", sa.String(16), nullable=False, server_default="slack"),
        schema=_SCHEMA,
    )
    op.add_column(
        _TABLA,
        sa.Column("actor_web_usuario", sa.String(64), nullable=True),
        schema=_SCHEMA,
    )
    for columna in _COLUMNAS_SLACK:
        op.alter_column(_TABLA, columna, existing_type=sa.String(32), nullable=True, schema=_SCHEMA)
    op.create_check_constraint(
        _CHECK_ORIGEN,
        _TABLA,
        "(origen = 'slack' AND actor_slack_user_id IS NOT NULL AND canal_id IS NOT NULL "
        "AND mensaje_ts IS NOT NULL) OR (origen = 'web' AND actor_web_usuario IS NOT NULL)",
        schema=_SCHEMA,
    )


def downgrade() -> None:
    filas_web = op.get_bind().execute(
        sa.text(f"SELECT count(*) FROM {_SCHEMA}.{_TABLA} WHERE origen = 'web'")
    ).scalar()
    if filas_web:
        raise RuntimeError(
            f"{_SCHEMA}.{_TABLA} tiene {filas_web} fila(s) con origen='web': no se pueden volver "
            "NOT NULL las columnas de Slack sin perder auditoría. Downgrade abortado."
        )
    op.drop_constraint(_CHECK_ORIGEN, _TABLA, type_="check", schema=_SCHEMA)
    for columna in _COLUMNAS_SLACK:
        op.alter_column(_TABLA, columna, existing_type=sa.String(32), nullable=False, schema=_SCHEMA)
    op.drop_column(_TABLA, "actor_web_usuario", schema=_SCHEMA)
    op.drop_column(_TABLA, "origen", schema=_SCHEMA)
