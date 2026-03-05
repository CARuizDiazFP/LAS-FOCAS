# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/alembic-migrations/SKILL.md
# Descripción: Habilidad para gestionar migraciones Alembic en LAS-FOCAS

---
name: Alembic Migrations
description: Habilidad para crear y gestionar migraciones de base de datos con Alembic
---

# Habilidad: Migraciones Alembic

Guía para gestionar migraciones de base de datos en LAS-FOCAS.

## Ubicación

- Configuración: `db/alembic.ini`
- Migraciones: `db/alembic/versions/`
- Entorno: `db/alembic/env.py`

## Comandos Esenciales

### Ver estado actual

```bash
# Historia de migraciones
alembic -c db/alembic.ini history

# Revisión actual aplicada
alembic -c db/alembic.ini current
```

### Crear migración

```bash
# Autogenerate (detecta cambios en modelos)
alembic -c db/alembic.ini revision --autogenerate -m "descripcion"

# Manual (para cambios no detectables)
alembic -c db/alembic.ini revision -m "descripcion"
```

### Aplicar migraciones

```bash
# Aplicar todas pendientes
alembic -c db/alembic.ini upgrade head

# Aplicar hasta revisión específica
alembic -c db/alembic.ini upgrade <revision_id>

# Aplicar siguiente migración
alembic -c db/alembic.ini upgrade +1
```

### Revertir migraciones

```bash
# Revertir última migración
alembic -c db/alembic.ini downgrade -1

# Revertir a revisión específica
alembic -c db/alembic.ini downgrade <revision_id>

# Revertir todo (PELIGROSO)
alembic -c db/alembic.ini downgrade base
```

### Ver SQL sin ejecutar

```bash
# Ver SQL de upgrade
alembic -c db/alembic.ini upgrade head --sql

# Ver SQL de downgrade
alembic -c db/alembic.ini downgrade -1 --sql
```

## Estructura de una Migración

```python
# Nombre de archivo: xxxx_descripcion.py
# Ubicación de archivo: db/alembic/versions/xxxx_descripcion.py
# Descripción: Migración - descripción

"""descripción de la migración

Revision ID: xxxx
Revises: yyyy (o None si es la primera)
Create Date: 2024-01-01 10:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = 'xxxx'
down_revision = 'yyyy'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Aplicar migración."""
    pass

def downgrade() -> None:
    """Revertir migración."""
    pass
```

## Operaciones Comunes

### Crear tabla

```python
def upgrade():
    op.create_table(
        'nombre_tabla',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('nombre', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        schema='app'
    )

def downgrade():
    op.drop_table('nombre_tabla', schema='app')
```

### Agregar columna

```python
def upgrade():
    op.add_column(
        'tabla',
        sa.Column('nueva_col', sa.String(50), nullable=True),
        schema='app'
    )

def downgrade():
    op.drop_column('tabla', 'nueva_col', schema='app')
```

### Crear índice

```python
def upgrade():
    op.create_index(
        'ix_tabla_columna',
        'tabla',
        ['columna'],
        schema='app'
    )

def downgrade():
    op.drop_index('ix_tabla_columna', table_name='tabla', schema='app')
```

### Crear foreign key

```python
def upgrade():
    op.create_foreign_key(
        'fk_tabla_otra_tabla',
        'tabla', 'otra_tabla',
        ['otra_id'], ['id'],
        source_schema='app',
        referent_schema='app'
    )

def downgrade():
    op.drop_constraint('fk_tabla_otra_tabla', 'tabla', schema='app')
```

### Modificar columna

```python
def upgrade():
    op.alter_column(
        'tabla',
        'columna',
        type_=sa.String(200),  # Cambiar tipo
        nullable=False,         # Cambiar nullable
        schema='app'
    )
```

### Insertar datos

```python
def upgrade():
    # Para datos de configuración/semilla
    op.execute("""
        INSERT INTO app.config (key, value)
        VALUES ('version', '1.0')
    """)

def downgrade():
    op.execute("DELETE FROM app.config WHERE key = 'version'")
```

## Reglas Obligatorias

1. **Siempre implementar `downgrade()`**: toda migración debe ser reversible
2. **Usar schema 'app'**: para tablas del sistema LAS-FOCAS
3. **Encabezado de 3 líneas**: en cada archivo de migración
4. **No romper datos**: las migraciones deben preservar datos existentes
5. **Nombres descriptivos**: para constraints e índices
6. **Testing**: verificar con `--sql` antes de aplicar

## Checklist Pre-Migración

- [ ] Backup de datos si es producción
- [ ] `downgrade()` implementado y probado
- [ ] SQL revisado con `--sql`
- [ ] Tests pasan con la nueva migración
- [ ] Documentación actualizada en `docs/db.md`

## Troubleshooting

### Error de dependencia circular

```bash
# Mostrar árbol de dependencias
alembic -c db/alembic.ini heads
```

### Migración aplicada pero no registrada

```bash
# Marcar como aplicada sin ejecutar
alembic -c db/alembic.ini stamp <revision_id>
```

### Reset completo (solo desarrollo)

```bash
alembic -c db/alembic.ini downgrade base
alembic -c db/alembic.ini upgrade head
```
