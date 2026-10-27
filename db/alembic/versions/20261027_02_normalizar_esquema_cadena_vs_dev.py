# Nombre de archivo: 20261027_02_normalizar_esquema_cadena_vs_dev.py
# Ubicación de archivo: db/alembic/versions/20261027_02_normalizar_esquema_cadena_vs_dev.py
# Descripción: Normaliza (idempotente) las 9 diferencias entre una base creada desde la cadena de migraciones y la base de dev: 6 nombres de índice, un DEFAULT y 2 comentarios

"""Normalización del esquema: cadena de migraciones ↔ dev

Una base nueva migrada desde cero (``db/init.sql`` + ``alembic upgrade head``) no queda igual que
dev: dev no salió sólo de la cadena (DDL manual y migraciones corridas con otras versiones de
SQLAlchemy, que nombraban distinto los ``index=True``). Medido el 2026-10-27 con
``scripts/check_drift_desde_cero.sh`` (P18):

- ``20260112_01`` crea los índices de ``incidentes_baneo`` con ``index=True``
  (``ix_incidentes_baneo_ticket_asociado``…); dev los tiene con nombre corto
  (``ix_incidentes_baneo_ticket``…). Lo mismo con ``config_servicios.nombre_servicio`` y
  ``rutas_servicio.servicio_id``, que en dev llevan el prefijo ``ix_app_``.
- ``incidentes_baneo.activo`` nace sin ``DEFAULT``; dev lo tiene en ``true``.
- ``20260428_01`` comenta ``config_servicios.workflow_ids`` y ``solo_workflows``; dev no tiene esos
  comentarios.

Los modelos siguen a dev (la base manda), salvo los dos comentarios, que vuelven al modelo. Esta
migración lleva cualquier base a ese estado: cada índice se renombra **sólo si** existe con el
nombre de la cadena y no existe con el de dev, así que en dev es un no-op salvo los comentarios, y
prod converge tenga la variante que tenga. ``ALTER INDEX … RENAME`` y ``COMMENT ON`` son cambios de
catálogo (lock breve, sin reescritura).

Downgrade: vuelve al estado que deja la cadena hasta ``20261027_01`` (nombres largos, sin
``DEFAULT`` en ``activo``, con los comentarios), con la misma guarda.

Revision ID: 20261027_02
Revises: 20261027_01
Create Date: 2026-10-27
"""

from __future__ import annotations

from alembic import op

revision = "20261027_02"
down_revision = "20261027_01"
branch_labels = None
depends_on = None

# (nombre que deja la cadena, nombre en dev = el que declara el modelo)
_INDICES = (
    ("ix_incidentes_baneo_ticket_asociado", "ix_incidentes_baneo_ticket"),
    ("ix_incidentes_baneo_servicio_afectado_id", "ix_incidentes_baneo_afectado"),
    ("ix_incidentes_baneo_servicio_protegido_id", "ix_incidentes_baneo_protegido"),
    ("ix_incidentes_baneo_ruta_protegida_id", "ix_incidentes_baneo_ruta"),
    ("ix_config_servicios_nombre_servicio", "ix_app_config_servicios_nombre_servicio"),
    ("ix_rutas_servicio_servicio_id", "ix_app_rutas_servicio_servicio_id"),
)

_COMENTARIOS = (
    ("workflow_ids", "IDs de Workflow de Slack permitidos, separados por coma (NULL = sin filtro)"),
    ("solo_workflows", "Si True, solo procesa mensajes con workflow_id incluido en workflow_ids"),
)


def _renombrar(origen: str, destino: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('app.{origen}') IS NOT NULL AND to_regclass('app.{destino}') IS NULL THEN
                ALTER INDEX app.{origen} RENAME TO {destino};
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    for cadena, dev in _INDICES:
        _renombrar(cadena, dev)
    op.execute("ALTER TABLE app.incidentes_baneo ALTER COLUMN activo SET DEFAULT true")
    for columna, comentario in _COMENTARIOS:
        op.execute(f"COMMENT ON COLUMN app.config_servicios.{columna} IS '{comentario}'")


def downgrade() -> None:
    for cadena, dev in _INDICES:
        _renombrar(dev, cadena)
    op.execute("ALTER TABLE app.incidentes_baneo ALTER COLUMN activo DROP DEFAULT")
    # Los comentarios existen en el estado de la cadena hasta 20261027_01: no se tocan.
