# Nombre de archivo: 20260813_01_cromo_botella_default_libre.py
# Ubicación de archivo: db/alembic/versions/20260813_01_cromo_botella_default_libre.py
# Descripción: Cambia el server_default de app.cromo_botellas.estado de NO_OPERATIVA a LIBRE

"""Cambia el default de cromo_botellas.estado a LIBRE

Revision ID: 20260813_01
Revises: 20260811_02
Create Date: 2026-08-13

Cambios:
- ``ALTER COLUMN app.cromo_botellas.estado SET DEFAULT 'LIBRE'`` — reversión
  explícita (decisión del usuario, 2026-08-13) de la política fail-closed
  introducida en ``20260811_01_cromo_botella_camara_padre.py``. Metadata-only,
  no reescribe filas existentes (mismo motivo por el que el default original
  tampoco las reescribió).

Por qué es seguro: el default sólo aplica a una fila recién insertada por la
ingesta que todavía no pasó por la resolución de Cámara padre (``camara_id``
sigue ``NULL`` en ese instante) — no hay ningún ``IncidenteBaneo`` real que
pueda aplicar a una fila sin `camara_id` resuelto todavía. El código de
resolución (``core/services/cromo/camara_padre_service.py``,
``scripts/cromo_backfill_camara_padre.py``, ``core/services/cromo/orfanas_service.py``)
ya fue actualizado en el mismo cambio para crear Cámaras padre nuevas en
``LIBRE`` en vez de ``NO_OPERATIVA``; esta migración alinea el default de
columna con esa misma política para el período transitorio entre ingesta y
resolución. Ver ``docs/decisiones.md``.
"""

from __future__ import annotations

from alembic import op

revision = "20260813_01"
down_revision = "20260811_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.cromo_botellas ALTER COLUMN estado SET DEFAULT 'LIBRE'")


def downgrade() -> None:
    op.execute("ALTER TABLE app.cromo_botellas ALTER COLUMN estado SET DEFAULT 'NO_OPERATIVA'")
