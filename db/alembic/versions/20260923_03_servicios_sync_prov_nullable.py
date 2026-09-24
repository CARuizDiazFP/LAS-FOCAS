# Nombre de archivo: 20260923_03_servicios_sync_prov_nullable.py
# Ubicación de archivo: db/alembic/versions/20260923_03_servicios_sync_prov_nullable.py
# Descripción: app.servicios_sync_prov.ultima_sincronizacion_ok pasa a NULLABLE — fix de la revisión de calidad de la Task 9 (centinela 1970-01-01 reemplazado por NULL)

"""servicios_sync_prov.ultima_sincronizacion_ok nullable

Revision ID: 20260923_03
Revises: 20260923_02
Create Date: 2026-09-23

Fix del round de revisión de calidad de la Task 9 del plan "Corrección de ingresos/servicios"
(Important 3): el implementador de la Task 9 necesitaba persistir un intento FALLIDO de refresco
(`modules/slack_baneo_notifier/refresco_prov.py::_persistir_intento_fallido`) para un servicio que
nunca sincronizó con éxito, pero `ultima_sincronizacion_ok` era `NOT NULL` (migración `20260923_02`,
pensada sólo para el camino de éxito de `ingerir_contexto_prov`) — usó un centinela
(`datetime(1970, 1, 1, tzinfo=utc)`) para satisfacerlo. Tres razones para reemplazar el centinela
por `NULL` en vez de sostenerlo:

(a) `NULL` ya es el encoding canónico de "nunca sincronizado" — la consulta de frescura
    (`core/services/prov/frescura.py::_SQL_VENCIDOS_BATCH`) ya la maneja explícito:
    `WHERE sp.ultima_sincronizacion_ok IS NULL OR sp.ultima_sincronizacion_ok < :corte`. El
    centinela agrega un SEGUNDO encoding del mismo estado ("nunca sincronizado") que la consulta de
    frescura ni siquiera necesita — un 1970 real cae del lado `< :corte` de todas formas, así que el
    centinela nunca aportó nada ahí; sólo quedaba como una constante mágica que sostener para
    siempre en cualquier código futuro que lea la columna directamente (no a través de la consulta
    de frescura).
(b) Obliga a cualquier consumidor futuro (Task 10, un panel admin) a importar
    `refresco_prov._EPOCA_NUNCA_SINCRONIZADO`, una constante PRIVADA de un módulo del bot de Slack,
    sólo para renderizar bien una columna de DB — la dependencia al revés.
(c) Cuesta cero HOY: `app.servicios_sync_prov` tiene 0 filas en dev (confirmado real contra
    `lasfocasdev-postgres` antes de esta migración) y la tabla no existe en prod. Sin backfill.

Sin backfill a propósito (no hay filas que backfillear — ver (c) arriba, y aunque las hubiera, un
1970 histórico seguiría siendo correcto reinterpretado como NULL: mismo significado semántico,
"nunca sincronizó con éxito"). La consulta de frescura NO se toca — ya esperaba `NULL`.

`down_revision` es `20260923_02` (confirmado con `alembic heads` contra este mismo checkout: single
head, `20260923_02`, antes de crear esta revisión).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260923_03"
down_revision = "20260923_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "servicios_sync_prov",
        "ultima_sincronizacion_ok",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        schema="app",
    )


def downgrade() -> None:
    # Sin backfill acá tampoco: revertir con filas NULL existentes (creadas por el camino de fallo
    # de la Task 9 después de que esta migración corrió) rompería el `NOT NULL` que este downgrade
    # intenta restaurar. Mismo criterio que el upgrade — la tabla no tiene volumen real hoy (ver
    # docstring del módulo) y este downgrade es sólo para poder revertir en un entorno de desarrollo
    # limpio, no para producción con datos.
    op.alter_column(
        "servicios_sync_prov",
        "ultima_sincronizacion_ok",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        schema="app",
    )
