# Nombre de archivo: recetas.md
# Ubicación de archivo: .github/skills/alembic-migrations/references/recetas.md
# Descripción: Recetas y operaciones comunes para migraciones Alembic en LAS-FOCAS

# Recetas de Migraciones Alembic

## Estado actual

```bash
alembic -c db/alembic.ini history
alembic -c db/alembic.ini current
alembic -c db/alembic.ini heads
```

## Crear migración

```bash
alembic -c db/alembic.ini revision --autogenerate -m "descripcion"
alembic -c db/alembic.ini revision -m "descripcion"
```

## Aplicar o revertir

```bash
alembic -c db/alembic.ini upgrade head
alembic -c db/alembic.ini upgrade <revision_id>
alembic -c db/alembic.ini downgrade -1
alembic -c db/alembic.ini downgrade <revision_id>
alembic -c db/alembic.ini upgrade head --sql
alembic -c db/alembic.ini downgrade -1 --sql
```

## Estructura mínima

```python
# Nombre de archivo: xxxx_descripcion.py
# Ubicación de archivo: db/alembic/versions/xxxx_descripcion.py
# Descripción: Migración - descripción

from alembic import op
import sqlalchemy as sa

revision = 'xxxx'
down_revision = 'yyyy'
branch_labels = None
depends_on = None

def upgrade() -> None:
    ...

def downgrade() -> None:
    ...
```

## Operaciones comunes

### Crear tabla

```python
op.create_table(
    'nombre_tabla',
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('nombre', sa.String(100), nullable=False),
    schema='app'
)
```

### Agregar columna

```python
op.add_column('tabla', sa.Column('nueva_col', sa.String(50), nullable=True), schema='app')
```

### Índices y foreign keys

```python
op.create_index('ix_tabla_columna', 'tabla', ['columna'], schema='app')
op.create_foreign_key('fk_tabla_otra_tabla', 'tabla', 'otra_tabla', ['otra_id'], ['id'], source_schema='app', referent_schema='app')
```

## Troubleshooting

```bash
alembic -c db/alembic.ini stamp <revision_id>
alembic -c db/alembic.ini downgrade base
alembic -c db/alembic.ini upgrade head
```

## Guardrails

- Toda migración debe incluir `downgrade()` salvo excepción justificada.
- Revisar SQL con `--sql` antes de aplicar cambios delicados.
- Preservar datos y documentar impactos en `docs/db.md` o PR diario.