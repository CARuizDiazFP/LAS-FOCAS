# Nombre de archivo: 20260923_01_ingresos_correcciones.py
# Ubicación de archivo: db/alembic/versions/20260923_01_ingresos_correcciones.py
# Descripción: Columnas de hilo en app.ingresos + tabla append-only app.ingresos_correcciones (auditoría de "Forzar ingreso"/"Forzar egreso")

"""Columnas de hilo en ingresos + tabla ingresos_correcciones

Revision ID: 20260923_01
Revises: 20260919_04
Create Date: 2026-09-23

Cambios (Task 2 del plan "Corrección de ingresos/servicios" — soporte de datos para los comandos
Slack "Forzar ingreso"/"Forzar egreso" que implementan las Tasks 5 y 6):

- Nuevas columnas ``app.ingresos.thread_ts`` (``VARCHAR(32) NULL``, indexada) y
  ``app.ingresos.canal_id`` (``VARCHAR(32) NULL``). Hoy ``app.ingresos`` no guarda nada del hilo de
  Slack en el que se originó el movimiento — sólo ``IngresoSinMatch`` guarda ``thread_ts``, y sólo
  para los casos que no matchearon ninguna cámara. Para un caso que matcheó bien no hay forma de
  llegar del hilo al ``Ingreso`` real. Estas columnas cierran ese hueco de acá en adelante; los
  hilos históricos (anteriores a esta migración) se resuelven por los niveles 2 y 3 de la cascada de
  búsqueda de la Task 5, no por esta columna.

- Tabla nueva ``app.ingresos_correcciones``, append-only: un registro por cada ejecución de
  "Forzar ingreso"/"Forzar egreso", exitosa o no. Se crea como tabla nueva y no como extensión de
  ``IngresoSinMatch`` a propósito: esa tabla modela "el nombre no matcheó" (subconjunto de casos) y
  sus filas se mutan en el tiempo (``resuelto_via_empalme``, ``resuelto_via_revalidacion``) —
  semántica opuesta a la de un log inmutable. Una corrección manual puede ocurrir también sobre un
  hilo que matcheó perfecto la primera vez.

  ``comando``, ``resultado`` y ``fuente_momento`` se modelan como ``String`` y no como enum de
  Postgres: sus valores previstos van a crecer durante las Tasks 5 y 6 (``resultado`` sólo ya tiene
  al menos 10 valores previstos, incluido ``PENDIENTE_FECHA``), y un enum de Postgres obligaría a una
  migración ``ALTER TYPE ... ADD VALUE`` por cada valor nuevo.

  Nullability: ``comando``, ``actor_slack_user_id``, ``canal_id``, ``mensaje_ts``, ``comando_crudo``,
  ``camara_texto_solicitado``, ``resultado`` y ``created_at`` son ``NOT NULL`` — se conocen siempre
  al momento de escribir la fila (append-only: se escribe una sola vez, al terminar de procesar el
  comando). El resto es nullable porque depende del camino que tomó el procesamiento: ``thread_ts``
  puede faltar si el comando no fue una respuesta en un hilo (``fuente_momento = 'explicito'``);
  ``actor_nombre`` puede no resolverse (mismo caso que ``Ingreso.tecnico_id``, migración
  ``20260904_01``); ``camara_id_resuelta``/``cromo_botella_id_resuelta`` quedan ``NULL`` si el
  ``resultado`` fue una falla de resolución de cámara; ``momento_solicitado``/``momento_efectivo``/
  ``fuente_momento`` quedan ``NULL`` para el caso ``PENDIENTE_FECHA`` (todavía no hay una fecha
  resuelta); ``ingreso_id`` sólo se completa si la corrección terminó creando/cerrando un ``Ingreso``
  real.

  FKs con ``ON DELETE SET NULL`` (``camara_id_resuelta`` -> ``app.camaras.id``,
  ``cromo_botella_id_resuelta`` -> ``app.cromo_botellas.n_id``, ``ingreso_id`` ->
  ``app.ingresos.id``): el log de auditoría sobrevive aunque la entidad referenciada se borre después
  — perder la fila de auditoría sería peor que perder sólo el vínculo.

- Trigger de inmutabilidad: función PL/pgSQL ``app.ingresos_correcciones_bloquear_mutacion()`` +
  trigger ``trg_ingresos_correcciones_inmutable`` (``BEFORE UPDATE OR DELETE ... FOR EACH ROW``) que
  hace ``RAISE EXCEPTION`` ante cualquier intento de modificar o borrar una fila ya escrita. Es la
  diferencia entre "inmutable" como promesa de docstring/código de aplicación (que cualquier acceso
  directo a la DB, script one-off o bug puede violar) e inmutable de verdad, garantizado por la DB.
  El ``downgrade()`` dropea trigger y función explícitamente, no sólo la tabla.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260923_01"
down_revision = "20260919_04"
branch_labels = None
depends_on = None


_FUNCTION_NAME = "app.ingresos_correcciones_bloquear_mutacion"
_TRIGGER_NAME = "trg_ingresos_correcciones_inmutable"

_CREATE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {_FUNCTION_NAME}()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'app.ingresos_correcciones es append-only: % sobre id=% está prohibido (log de auditoría inmutable)',
        TG_OP, OLD.id;
END;
$$ LANGUAGE plpgsql;
"""

_CREATE_TRIGGER_SQL = f"""
CREATE TRIGGER {_TRIGGER_NAME}
BEFORE UPDATE OR DELETE ON app.ingresos_correcciones
FOR EACH ROW EXECUTE FUNCTION {_FUNCTION_NAME}();
"""

_DROP_TRIGGER_SQL = f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON app.ingresos_correcciones;"
_DROP_FUNCTION_SQL = f"DROP FUNCTION IF EXISTS {_FUNCTION_NAME}();"


def upgrade() -> None:
    # --- Step 1: columnas de hilo en app.ingresos ---
    op.add_column(
        "ingresos",
        sa.Column("thread_ts", sa.String(32), nullable=True),
        schema="app",
    )
    op.add_column(
        "ingresos",
        sa.Column("canal_id", sa.String(32), nullable=True),
        schema="app",
    )
    op.create_index(
        "ix_ingresos_thread_ts",
        "ingresos",
        ["thread_ts"],
        schema="app",
    )

    # --- Step 2: tabla append-only app.ingresos_correcciones ---
    op.create_table(
        "ingresos_correcciones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("comando", sa.String(32), nullable=False),  # 'FORZAR_INGRESO' | 'FORZAR_EGRESO'
        sa.Column("actor_slack_user_id", sa.String(32), nullable=False),
        sa.Column("actor_nombre", sa.String(255), nullable=True),
        sa.Column("canal_id", sa.String(32), nullable=False),
        sa.Column("thread_ts", sa.String(32), nullable=True),
        sa.Column("mensaje_ts", sa.String(32), nullable=False),
        sa.Column("comando_crudo", sa.Text(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("camara_texto_solicitado", sa.String(512), nullable=False),
        sa.Column(
            "camara_id_resuelta",
            sa.Integer(),
            sa.ForeignKey("app.camaras.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "cromo_botella_id_resuelta",
            sa.BigInteger(),
            sa.ForeignKey("app.cromo_botellas.n_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("momento_solicitado", sa.DateTime(timezone=True), nullable=True),
        sa.Column("momento_efectivo", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fuente_momento", sa.String(16), nullable=True),  # 'hilo' | 'explicito'
        sa.Column(
            "ingreso_id",
            sa.Integer(),
            sa.ForeignKey("app.ingresos.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resultado", sa.String(64), nullable=False),
        sa.Column("error_detalle", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )
    op.create_index(
        "ix_ingresos_correcciones_thread_ts",
        "ingresos_correcciones",
        ["thread_ts"],
        schema="app",
    )
    op.create_index(
        "ix_ingresos_correcciones_created_at",
        "ingresos_correcciones",
        ["created_at"],
        schema="app",
    )
    op.create_index(
        "ix_ingresos_correcciones_camara_id_resuelta",
        "ingresos_correcciones",
        ["camara_id_resuelta"],
        schema="app",
    )
    op.create_index(
        "ix_ingresos_correcciones_cromo_botella_id_resuelta",
        "ingresos_correcciones",
        ["cromo_botella_id_resuelta"],
        schema="app",
    )
    op.create_index(
        "ix_ingresos_correcciones_ingreso_id",
        "ingresos_correcciones",
        ["ingreso_id"],
        schema="app",
    )

    # --- Step 3: trigger de inmutabilidad ---
    op.execute(_CREATE_FUNCTION_SQL)
    op.execute(_CREATE_TRIGGER_SQL)


def downgrade() -> None:
    # Trigger + función primero: sin esto, el drop_table de abajo funcionaría igual (DROP TABLE no
    # dispara el trigger), pero dejar función/trigger huérfanos en la DB sería un residuo silencioso.
    op.execute(_DROP_TRIGGER_SQL)
    op.execute(_DROP_FUNCTION_SQL)

    op.drop_index("ix_ingresos_correcciones_ingreso_id", table_name="ingresos_correcciones", schema="app")
    op.drop_index(
        "ix_ingresos_correcciones_cromo_botella_id_resuelta", table_name="ingresos_correcciones", schema="app"
    )
    op.drop_index("ix_ingresos_correcciones_camara_id_resuelta", table_name="ingresos_correcciones", schema="app")
    op.drop_index("ix_ingresos_correcciones_created_at", table_name="ingresos_correcciones", schema="app")
    op.drop_index("ix_ingresos_correcciones_thread_ts", table_name="ingresos_correcciones", schema="app")
    op.drop_table("ingresos_correcciones", schema="app")

    op.drop_index("ix_ingresos_thread_ts", table_name="ingresos", schema="app")
    op.drop_column("ingresos", "canal_id", schema="app")
    op.drop_column("ingresos", "thread_ts", schema="app")
