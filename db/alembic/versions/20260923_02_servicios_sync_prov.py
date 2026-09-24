# Nombre de archivo: 20260923_02_servicios_sync_prov.py
# Ubicación de archivo: db/alembic/versions/20260923_02_servicios_sync_prov.py
# Descripción: Tabla app.servicios_sync_prov — última sincronización exitosa contra PROV por Servicio

"""Tabla de sincronización PROV por Servicio

Revision ID: 20260923_02
Revises: 20260923_01
Create Date: 2026-09-23

Cambios (Task 7 del plan "Corrección de ingresos/servicios" — soporte de datos consumido por las
Tasks 8 y 10 para distinguir qué IDs de servicio están "validados contra PROV" de cuáles no):

- Medido real contra `lasfocasdev-postgres` antes de esta migración: `app.servicios` tiene 20
  columnas y NINGUNA es de timestamp (ni `created_at` ni `updated_at`) — hoy es literalmente
  imposible saber si una fila fue sincronizada contra PROV alguna vez. Además, de los servicios
  alcanzables por cable, el 92,5% (8.401 de 9.079) nunca pasó por PROV
  (`origen_datos <> 'INGEST_PROV'`): hasta que corra el backfill (`scripts/servicios_backfill_prov.py`,
  ver `docs/bot.md`), la enorme mayoría de las filas de esta tabla nueva simplemente no existe
  todavía, y eso es el estado esperado, no un bug.

- Tabla nueva y no una columna en `app.servicios`, por tres razones concretas (no una preferencia de
  estilo): (1) esa tabla la escriben tres ingestas distintas (Excel, PROV, placeholders Cromo) y
  `origen_datos` se re-etiqueta incondicionalmente en cada una
  (`core/services/prov/ingesta.py::ingerir_contexto_prov`, línea ~262 antes de este cambio) — una
  columna ahí heredaría exactamente el "pisado por ingesta ajena" que se busca evitar; (2) el estado
  de *fallo* de un intento (`ultimo_error`) es una preocupación operativa del proceso de
  sincronización, no un atributo de dominio del Servicio; (3) separar la escritura de estado de
  sincronización de la escritura de la fila de dominio permite que un futuro camino de fallo
  (fuera de alcance de esta tarea) actualice `ultimo_intento`/`ultimo_error` sin tocar `Servicio` en
  absoluto.

- Columnas y nullability:
  - `servicio_id` (`INTEGER NOT NULL`, FK a `app.servicios.id` `ON DELETE CASCADE`, `UNIQUE`): una
    fila por Servicio — nunca un historial de intentos, sólo el estado vigente. `CASCADE` porque el
    estado de sincronización de un Servicio borrado no tiene ningún sentido por sí solo.
  - `ultima_sincronizacion_ok` (`TIMESTAMPTZ NOT NULL`): momento del último refresco EXITOSO contra
    PROV. `NOT NULL` porque el único punto de escritura de esta migración (el upsert al final de
    `ingerir_contexto_prov`) sólo corre cuando el contexto de PROV ya fue validado como éxito por
    `ProvClient` — una fila de esta tabla nace siempre de un intento exitoso.
  - `ultimo_intento` (`TIMESTAMPTZ NULL`): momento del último intento, exitoso o no. Nullable a
    propósito: el embudo actual siempre lo completa junto con `ultima_sincronizacion_ok`, pero deja
    la puerta abierta a que un futuro camino de fallo lo actualice solo, sin una sincronización
    exitosa de por medio.
  - `ultimo_error` (`TEXT NULL`): detalle del último fallo, si lo hubo. `NULL` mientras el último
    intento haya sido exitoso (el upsert de esta tarea lo limpia en cada éxito, para que un error
    viejo no quede pegado indefinidamente después de un refresco que sí funcionó).
  - `nro_servicio_consultado` (`VARCHAR(64) NULL`): el número que efectivamente se mandó a consultar
    a PROV (puede diferir de `Servicio.servicio_id` vigente si la consolidación de identidad avanzó
    el ID en el mismo refresco) — trazabilidad de auditoría, no requerido para la consulta de
    frescura.
  - `created_at`/`updated_at` (`TIMESTAMPTZ NOT NULL`, calculados en Python por el upsert, mismo
    criterio que `ServicioHistorialId`/`ServicioEquipoUltimaMilla`): auditoría estándar de la fila.

- Sin índice propio sobre `ultima_sincronizacion_ok`: la consulta de frescura (Task 7,
  `core/services/prov/frescura.py`) siempre filtra primero por `servicio_id = ANY(:ids)` (hasta ~118
  ids por llamada, el tamaño de un cable real) — el índice UNIQUE de `servicio_id` ya acota el
  trabajo a esas filas antes de evaluar la condición de vencimiento; un índice adicional sería
  overhead de escritura sin beneficio medible a esta escala.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260923_02"
down_revision = "20260923_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "servicios_sync_prov",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "servicio_id",
            sa.Integer(),
            sa.ForeignKey("app.servicios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ultima_sincronizacion_ok", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultimo_intento", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
        sa.Column("nro_servicio_consultado", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    op.create_index(
        "uq_servicios_sync_prov_servicio_id",
        "servicios_sync_prov",
        ["servicio_id"],
        unique=True,
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("uq_servicios_sync_prov_servicio_id", table_name="servicios_sync_prov", schema="app")
    op.drop_table("servicios_sync_prov", schema="app")
