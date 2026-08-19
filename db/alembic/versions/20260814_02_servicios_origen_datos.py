# Nombre de archivo: 20260814_02_servicios_origen_datos.py
# Ubicación de archivo: db/alembic/versions/20260814_02_servicios_origen_datos.py
# Descripción: Nuevo enum app.servicio_origen_datos + columna app.servicios.origen_datos — distingue servicios reales (MANUAL/TRACKING/INGEST_EXCEL) de placeholders sintetizados por el matching Cromo (INFERIDO_CROMO)

"""Enum servicio_origen_datos + columna servicios.origen_datos

Revision ID: 20260814_02
Revises: 20260814_01
Create Date: 2026-08-14

Cambios:
- Nuevo enum Postgres ``app.servicio_origen_datos``: MANUAL, TRACKING, INGEST_EXCEL, INFERIDO_CROMO
  — mismo patrón que ``app.camara_origen_datos`` (ver ``db/models/infra.py::CamaraOrigenDatos``,
  migración ``20260108_01``), para distinguir un ``Servicio`` real de un placeholder sintetizado
  por el matching de ``cromo_pelos.servicio_numero`` (ver ``core/services/cromo/ingesta.py::
  fase_servicios`` y ``scripts/cromo_backfill_placeholders_servicios.py``). ``TRACKING`` se agrega
  al vocabulario ahora aunque ningún código lo emite todavía (``core/services/infra_service.py``,
  alta por ``/api/infra/upload_tracking``, sigue sin fijar ``origen_datos`` explícito — queda en
  ``MANUAL`` por el default de columna) — fuera de alcance de esta migración, ver docs/decisiones.md.

- Nueva columna ``app.servicios.origen_datos``: ``NOT NULL DEFAULT 'MANUAL'``.

Backfill de las ~1488 filas existentes: NINGUNO explícito en esta migración — a diferencia de
``categoria`` (columna YA existente: un ``ALTER COLUMN ... SET DEFAULT`` nunca toca retroactivamente
filas ya existentes, por eso esa migración sí necesitó un ``UPDATE`` manual), acá la columna es
NUEVA: ``ADD COLUMN ... NOT NULL DEFAULT 'MANUAL'`` en PG11+ aplica el default a las filas
existentes vía catálogo (metadata-only, sin reescribir la tabla — mismo mecanismo ya documentado en
``20260811_01_cromo_botella_camara_padre.py`` para ``cromo_botellas.estado``). Las 1488 filas
actuales quedan en ``MANUAL`` sin ningún ``UPDATE`` extra.

Se evaluó (y se descarta) reconstruir el origen real de esas 1488 filas distinguiendo TRACKING de
INGEST_EXCEL vía ``raw_tracking_data IS NOT NULL`` — descartado porque la migración
``20260713_01_servicios_sla_fase1.py`` ya sobreescribió ``numero_primer_servicio`` de TODAS las
filas preexistentes por igual (esa columna no sirve como señal de origen), y no hay certeza
suficiente sobre ``raw_tracking_data`` en las filas más viejas como para etiquetarlas con
confianza. ``MANUAL`` uniforme es la opción honesta: "origen histórico no reconstruible con
certeza", no una afirmación falsa de que las 1488 filas se cargaron a mano.

Nota técnica: Postgres prohíbe usar un valor de enum recién agregado (``ALTER TYPE ... ADD VALUE``)
dentro de la misma transacción que lo agrega (ver ``20260811_01_cromo_botella_camara_padre.py``,
primera vez que este repo necesitó ``op.get_context().autocommit_block()``). Esa restricción NO
aplica acá: este enum se CREA de cero (``CREATE TYPE``), no se le agrega un valor a uno ya
existente — mismo caso que ``20260108_01_infra_updates.py`` (creación + uso inmediato de
``camara_origen_datos`` sin ``autocommit_block``), confirmado con ese precedente real de este mismo
repo.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260814_02"
down_revision = "20260814_01"
branch_labels = None
depends_on = None


_VALORES = ("MANUAL", "TRACKING", "INGEST_EXCEL", "INFERIDO_CROMO")


def upgrade() -> None:
    bind = op.get_bind()

    servicio_origen_enum = postgresql.ENUM(*_VALORES, name="servicio_origen_datos", schema="app", create_type=False)
    servicio_origen_enum.create(bind, checkfirst=True)

    op.add_column(
        "servicios",
        sa.Column(
            "origen_datos",
            postgresql.ENUM(*_VALORES, name="servicio_origen_datos", schema="app", create_type=False),
            nullable=False,
            server_default="MANUAL",
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("servicios", "origen_datos", schema="app")
    servicio_origen_enum = postgresql.ENUM(*_VALORES, name="servicio_origen_datos", schema="app", create_type=False)
    servicio_origen_enum.drop(bind=op.get_bind(), checkfirst=True)
