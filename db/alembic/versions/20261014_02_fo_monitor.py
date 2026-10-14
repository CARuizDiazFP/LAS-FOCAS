# Nombre de archivo: 20261014_02_fo_monitor.py
# Ubicación de archivo: db/alembic/versions/20261014_02_fo_monitor.py
# Descripción: Tablas app.fomon_* de FO Monitor (intervenciones, consultas a burritoIA, resultados append-only, geometría)

"""Tablas de FO Monitor

Revision ID: 20261014_02
Revises: 20261014_01
Create Date: 2026-10-14

Cambios:

- ``app.fomon_config`` (singleton, ``CHECK id = 1``): ventana del piloto, tope diario de mensajes a
  burritoIA (400), lote máximo, timeouts, concurrencia, versión de prompt y la marca de agua
  ``ultimo_ingreso_id_procesado``. Se siembra con el ``max(id)`` actual de ``app.ingresos`` para que
  el worker NO procese el histórico al arrancar. ``canales_ingreso`` limita qué ingresos se verifican
  por ``app.ingresos.canal_id``: por defecto sólo ``C08UB8ML3LP`` (#baneo-de-camaras-prueba); el canal
  productivo de ingresos queda en stand-by hasta que se agregue explícitamente.
- Fila ``fo_monitor`` en ``app.config_servicios`` (kill switch + canal), **inactiva**, canal
  ``C08UB8ML3LP`` (#baneo-de-camaras-prueba). Cada worker filtra ``config_servicios`` por su propio
  ``nombre_servicio``, así que la fila nueva no dispara nada en los demás.
- ``app.fomon_intervenciones``, ``app.fomon_intervencion_ingresos`` (``ingreso_id`` UNIQUE),
  ``app.fomon_intervencion_servicios`` (lista congelada; ``servicio_pk`` sin FK a propósito, ver
  ``db/models/fo_monitor.py``), ``app.fomon_consultas``.
- ``app.fomon_resultados``, ``app.fomon_reconocimientos`` y ``app.fomon_config_auditoria``:
  **append-only** con trigger ``BEFORE UPDATE OR DELETE`` (mismo patrón que
  ``20260923_01_ingresos_correcciones``).
- ``app.fomon_cable_geo``: polilínea WGS84 simplificada por cable + bbox (sin PostGIS: la imagen
  ``postgres:16-alpine`` no trae la extensión).

Estados y fases como ``String`` + ``CHECK`` (no enum de Postgres). El ``downgrade()`` borra todo,
incluida la fila de ``config_servicios``; pierde el histórico de FO Monitor.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261014_02"
down_revision = "20261014_01"
branch_labels = None
depends_on = None

_APPEND_ONLY = ("fomon_resultados", "fomon_reconocimientos", "fomon_config_auditoria")
_FUNCTION_NAME = "app.fomon_bloquear_mutacion"


def _in(col: str, valores: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in valores)})"


def upgrade() -> None:
    op.create_table(
        "fomon_config",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("ventana_desde", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ventana_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tope_mensajes_diario", sa.Integer(), nullable=False, server_default="400"),
        sa.Column("max_ids_por_mensaje", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("timeout_base_s", sa.Integer(), nullable=False, server_default="240"),
        sa.Column("timeout_por_servicio_s", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("concurrencia", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("burrito_user_id", sa.String(32), nullable=False, server_default="U0A2HE3K950"),
        sa.Column("prompt_version", sa.String(8), nullable=False, server_default="v4"),
        sa.Column("ultimo_ingreso_id_procesado", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("canales_ingreso", sa.String(256), nullable=False, server_default="C08UB8ML3LP"),
        sa.Column("actualizado_por", sa.String(128), nullable=True),
        sa.Column("actualizado_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_fomon_config_singleton"),
        sa.CheckConstraint("max_ids_por_mensaje BETWEEN 1 AND 20", name="ck_fomon_config_lote"),
        sa.CheckConstraint("concurrencia BETWEEN 1 AND 10", name="ck_fomon_config_concurrencia"),
        schema="app",
    )
    op.execute(
        "INSERT INTO app.fomon_config (id, ultimo_ingreso_id_procesado) "
        "SELECT 1, COALESCE(max(id), 0) FROM app.ingresos"
    )
    op.execute(
        "INSERT INTO app.config_servicios (nombre_servicio, intervalo_horas, slack_channels, activo) "
        "SELECT 'fo_monitor', 0, 'C08UB8ML3LP', false "
        "WHERE NOT EXISTS (SELECT 1 FROM app.config_servicios WHERE nombre_servicio = 'fo_monitor')"
    )

    op.create_table(
        "fomon_config_auditoria",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("usuario", sa.String(128), nullable=False),
        sa.Column("cambios", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="app",
    )

    op.create_table(
        "fomon_intervenciones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("origen", sa.String(16), nullable=False),
        sa.Column("camara_id", sa.Integer(), sa.ForeignKey("app.camaras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("botella_objetivo_n_id", sa.BigInteger(), nullable=True),
        sa.Column("botella_1_inferida", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cable_n_id_manual", sa.BigInteger(), nullable=True),
        sa.Column("tecnico", sa.String(128), nullable=True),
        sa.Column("thread_ts_ingreso", sa.String(32), nullable=True),
        sa.Column("canal_ingreso", sa.String(32), nullable=True),
        sa.Column("estado", sa.String(24), nullable=False, server_default="PRE_PENDIENTE"),
        sa.Column("fecha_ingreso", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_egreso", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sin_linea_base", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("post_tardio", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("egreso_inferido", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("atribucion_compartida", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("aviso_canal", sa.String(32), nullable=True),
        sa.Column("aviso_ts", sa.String(32), nullable=True),
        sa.Column("proximo_evento_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("iniciada_por", sa.String(128), nullable=True),
        sa.Column("creada_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actualizada_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("cerrada_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_in("origen", ("INGRESO", "MANUAL")), name="ck_fomon_interv_origen"),
        sa.CheckConstraint(
            _in("estado", ("PRE_PENDIENTE", "PRE_EN_CURSO", "EN_CURSO", "POST_PENDIENTE", "POST_EN_CURSO",
                           "CERRADA", "SIN_EGRESO", "CANCELADA")),
            name="ck_fomon_interv_estado",
        ),
        schema="app",
    )
    op.create_index("ix_fomon_intervenciones_camara_id", "fomon_intervenciones", ["camara_id"], schema="app")
    op.create_index("ix_fomon_intervenciones_estado", "fomon_intervenciones", ["estado"], schema="app")
    op.create_index("ix_fomon_intervenciones_proximo_evento_en", "fomon_intervenciones", ["proximo_evento_en"], schema="app")

    op.create_table(
        "fomon_intervencion_ingresos",
        sa.Column("intervencion_id", sa.Integer(), sa.ForeignKey("app.fomon_intervenciones.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("ingreso_id", sa.Integer(), sa.ForeignKey("app.ingresos.id", ondelete="CASCADE"), primary_key=True),
        sa.UniqueConstraint("ingreso_id", name="uq_fomon_interv_ingresos_ingreso"),
        schema="app",
    )

    op.create_table(
        "fomon_intervencion_servicios",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("intervencion_id", sa.Integer(), sa.ForeignKey("app.fomon_intervenciones.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cable_n_id", sa.BigInteger(), nullable=False),
        sa.Column("cable_nombre", sa.Text(), nullable=True),
        sa.Column("cable_clase", sa.SmallInteger(), nullable=True),
        sa.Column("botella_n_id", sa.BigInteger(), nullable=True),
        sa.Column("es_objetivo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("servicio_pk", sa.Integer(), nullable=True),
        sa.Column("servicio_id_externo", sa.String(64), nullable=True),
        sa.Column("tipo_servicio", sa.String(64), nullable=True),
        sa.Column("categoria", sa.SmallInteger(), nullable=True),
        sa.Column("cliente", sa.Text(), nullable=True),
        sa.UniqueConstraint("intervencion_id", "cable_n_id", "servicio_pk", name="uq_fomon_interv_serv"),
        schema="app",
    )
    op.create_index("ix_fomon_intervencion_servicios_intervencion_id", "fomon_intervencion_servicios", ["intervencion_id"], schema="app")
    op.create_index("ix_fomon_intervencion_servicios_cable_n_id", "fomon_intervencion_servicios", ["cable_n_id"], schema="app")

    op.create_table(
        "fomon_consultas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("intervencion_id", sa.Integer(), sa.ForeignKey("app.fomon_intervenciones.id"), nullable=False),
        sa.Column("fase", sa.String(8), nullable=False),
        sa.Column("intento", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("estado", sa.String(12), nullable=False, server_default="PENDIENTE"),
        sa.Column("servicios_pk", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("ids_solicitados", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("prompt_version", sa.String(8), nullable=True),
        sa.Column("canal", sa.String(32), nullable=True),
        sa.Column("slack_ts", sa.String(32), nullable=True),
        sa.Column("permalink", sa.Text(), nullable=True),
        sa.Column("texto_crudo", sa.Text(), nullable=True),
        sa.Column("ref_burrito", sa.String(16), nullable=True),
        sa.Column("completa", sa.Boolean(), nullable=True),
        sa.Column("lineas_invalidas", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("creada_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("enviada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("respondida_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proximo_evento_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_in("fase", ("PRE", "POST", "REVERIF")), name="ck_fomon_consultas_fase"),
        sa.CheckConstraint(
            _in("estado", ("PENDIENTE", "ENVIADA", "RESPONDIDA", "TIMEOUT", "ERROR", "CANCELADA")),
            name="ck_fomon_consultas_estado",
        ),
        schema="app",
    )
    op.create_index("ix_fomon_consultas_intervencion_id", "fomon_consultas", ["intervencion_id"], schema="app")
    op.create_index("ix_fomon_consultas_estado", "fomon_consultas", ["estado"], schema="app")
    op.create_index("ix_fomon_consultas_enviada_at", "fomon_consultas", ["enviada_at"], schema="app")

    op.create_table(
        "fomon_resultados",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("consulta_id", sa.Integer(), sa.ForeignKey("app.fomon_consultas.id"), nullable=False),
        sa.Column("intervencion_id", sa.Integer(), nullable=False),
        sa.Column("fase", sa.String(8), nullable=False),
        sa.Column("servicio_pk", sa.Integer(), nullable=False),
        sa.Column("servicio_id_externo", sa.String(64), nullable=False),
        sa.Column("estado", sa.String(16), nullable=False),
        sa.Column("extremo", sa.String(16), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("parseado", sa.Boolean(), nullable=False),
        sa.Column("medido_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            _in("estado", ("UP", "DOWN", "ADMIN_DOWN", "DESCONOCIDO", "NO_SOPORTADO")),
            name="ck_fomon_resultados_estado",
        ),
        sa.CheckConstraint(_in("fase", ("PRE", "POST", "REVERIF")), name="ck_fomon_resultados_fase"),
        schema="app",
    )
    op.create_index("ix_fomon_resultados_consulta_id", "fomon_resultados", ["consulta_id"], schema="app")
    op.create_index("ix_fomon_resultados_intervencion_id", "fomon_resultados", ["intervencion_id"], schema="app")

    op.create_table(
        "fomon_reconocimientos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("intervencion_id", sa.Integer(), sa.ForeignKey("app.fomon_intervenciones.id"), nullable=False),
        sa.Column("servicio_pk", sa.Integer(), nullable=True),
        sa.Column("usuario", sa.String(128), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("length(trim(motivo)) >= 3", name="ck_fomon_reconocimientos_motivo"),
        schema="app",
    )
    op.create_index("ix_fomon_reconocimientos_intervencion_id", "fomon_reconocimientos", ["intervencion_id"], schema="app")

    op.create_table(
        "fomon_cable_geo",
        sa.Column("cable_n_id", sa.BigInteger(), primary_key=True),
        sa.Column("coords", postgresql.JSONB(), nullable=False),
        sa.Column("min_lon", sa.Float(), nullable=False),
        sa.Column("min_lat", sa.Float(), nullable=False),
        sa.Column("max_lon", sa.Float(), nullable=False),
        sa.Column("max_lat", sa.Float(), nullable=False),
        sa.Column("vmax", sa.Integer(), nullable=True),
        sa.Column("calidad", sa.String(32), nullable=True),
        sa.Column("actualizado_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="app",
    )
    op.create_index("ix_fomon_cable_geo_bbox", "fomon_cable_geo", ["min_lon", "max_lon", "min_lat", "max_lat"], schema="app")

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION_NAME}()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'app.% es append-only: % sobre id=% está prohibido (registro de FO Monitor inmutable)',
                TG_TABLE_NAME, TG_OP, OLD.id;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for tabla in _APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER trg_{tabla}_inmutable BEFORE UPDATE OR DELETE ON app.{tabla} "
            f"FOR EACH ROW EXECUTE FUNCTION {_FUNCTION_NAME}();"
        )


def downgrade() -> None:
    for tabla in _APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tabla}_inmutable ON app.{tabla};")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION_NAME}();")

    op.drop_index("ix_fomon_cable_geo_bbox", table_name="fomon_cable_geo", schema="app")
    op.drop_table("fomon_cable_geo", schema="app")
    op.drop_index("ix_fomon_reconocimientos_intervencion_id", table_name="fomon_reconocimientos", schema="app")
    op.drop_table("fomon_reconocimientos", schema="app")
    op.drop_index("ix_fomon_resultados_intervencion_id", table_name="fomon_resultados", schema="app")
    op.drop_index("ix_fomon_resultados_consulta_id", table_name="fomon_resultados", schema="app")
    op.drop_table("fomon_resultados", schema="app")
    op.drop_index("ix_fomon_consultas_enviada_at", table_name="fomon_consultas", schema="app")
    op.drop_index("ix_fomon_consultas_estado", table_name="fomon_consultas", schema="app")
    op.drop_index("ix_fomon_consultas_intervencion_id", table_name="fomon_consultas", schema="app")
    op.drop_table("fomon_consultas", schema="app")
    op.drop_index("ix_fomon_intervencion_servicios_cable_n_id", table_name="fomon_intervencion_servicios", schema="app")
    op.drop_index("ix_fomon_intervencion_servicios_intervencion_id", table_name="fomon_intervencion_servicios", schema="app")
    op.drop_table("fomon_intervencion_servicios", schema="app")
    op.drop_table("fomon_intervencion_ingresos", schema="app")
    op.drop_index("ix_fomon_intervenciones_proximo_evento_en", table_name="fomon_intervenciones", schema="app")
    op.drop_index("ix_fomon_intervenciones_estado", table_name="fomon_intervenciones", schema="app")
    op.drop_index("ix_fomon_intervenciones_camara_id", table_name="fomon_intervenciones", schema="app")
    op.drop_table("fomon_intervenciones", schema="app")
    op.drop_table("fomon_config_auditoria", schema="app")
    op.execute("DELETE FROM app.config_servicios WHERE nombre_servicio = 'fo_monitor'")
    op.drop_table("fomon_config", schema="app")
