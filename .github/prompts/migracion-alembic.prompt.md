# Nombre de archivo: migracion-alembic.prompt.md
# Ubicación de archivo: .github/prompts/migracion-alembic.prompt.md
# Descripción: Prompt para crear migraciones Alembic de base de datos

---
name: Migración Alembic
description: Genera una migración Alembic para cambios en la base de datos
mode: agent
variables:
  - name: descripcion
    description: Descripción de la migración (ej. "agregar tabla usuarios")
  - name: tipo
    default: autogenerate
    description: Tipo de migración (autogenerate o manual)
---

# Crear Migración Alembic: ${descripcion}

Genera una migración Alembic para: **${descripcion}**

## Pasos a Seguir

### 1. Verificar estado actual de migraciones

```bash
cd /home/focal/proyectos/LAS-FOCAS
alembic -c db/alembic.ini history
alembic -c db/alembic.ini current
```

### 2. Crear la migración

#### Si es autogenerate (cambios en modelos SQLAlchemy):
```bash
alembic -c db/alembic.ini revision --autogenerate -m "${descripcion}"
```

#### Si es manual (cambios no detectables automáticamente):
```bash
alembic -c db/alembic.ini revision -m "${descripcion}"
```

### 3. Estructura del archivo de migración

El archivo generado en `db/alembic/versions/` debe tener:

```python
# Nombre de archivo: XXXX_${descripcion.replace(' ', '_').lower()}.py
# Ubicación de archivo: db/alembic/versions/XXXX_${descripcion.replace(' ', '_').lower()}.py
# Descripción: Migración - ${descripcion}

"""${descripcion}

Revision ID: xxxx
Revises: yyyy
Create Date: YYYY-MM-DD HH:MM:SS

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'xxxx'
down_revision = 'yyyy'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Aplicar migración."""
    # Ejemplo: crear tabla
    op.create_table(
        'nueva_tabla',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('nombre', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        schema='app'
    )
    
    # Ejemplo: agregar columna
    op.add_column(
        'tabla_existente',
        sa.Column('nueva_columna', sa.String(50)),
        schema='app'
    )
    
    # Ejemplo: crear índice
    op.create_index(
        'ix_tabla_columna',
        'tabla',
        ['columna'],
        schema='app'
    )

def downgrade() -> None:
    """Revertir migración."""
    # IMPORTANTE: siempre implementar downgrade
    op.drop_index('ix_tabla_columna', table_name='tabla', schema='app')
    op.drop_column('tabla_existente', 'nueva_columna', schema='app')
    op.drop_table('nueva_tabla', schema='app')
```

### 4. Validar la migración

```bash
# Ver SQL que se generará (sin ejecutar)
alembic -c db/alembic.ini upgrade head --sql

# Verificar sintaxis Python
python db/alembic/versions/XXXX_*.py
```

### 5. Aplicar la migración

```bash
# En desarrollo local
alembic -c db/alembic.ini upgrade head

# Verificar que se aplicó
alembic -c db/alembic.ini current
```

### 6. Rollback si es necesario

```bash
# Revertir última migración
alembic -c db/alembic.ini downgrade -1

# Revertir a revisión específica
alembic -c db/alembic.ini downgrade <revision_id>
```

## Reglas Obligatorias

1. **Siempre implementar `downgrade()`**: permitir rollback
2. **Encabezado de 3 líneas**: en el archivo de migración
3. **Schema `app`**: usar schema 'app' para tablas del sistema
4. **Nombres descriptivos**: índices y constraints con nombres claros
5. **No romper datos**: migraciones deben preservar datos existentes
6. **Tests antes de merge**: verificar que tests pasan con nueva migración

## Checklist de Validación

- [ ] `upgrade()` implementado correctamente
- [ ] `downgrade()` implementado (reversible)
- [ ] Encabezado de 3 líneas presente
- [ ] No hay datos hardcodeados
- [ ] Índices para columnas de búsqueda frecuente
- [ ] Constraints de integridad definidos
- [ ] Tests pasan: `pytest tests/test_db*.py`
- [ ] PR diario actualizado con cambios de DB

## Documentación

Después de crear la migración, actualizar `docs/db.md` con:
- Nueva tabla/columna agregada
- Cambios en esquema
- Notas de migración para otros desarrolladores
