---
description: "Crear una migración Alembic reversible (manual: el autogenerate está inactivo), validarla y aplicarla"
argument-hint: "descripción del cambio de esquema"
---

# Nombre de archivo: migracion-alembic.md
# Ubicación de archivo: .claude/commands/migracion-alembic.md
# Descripción: Comando Claude Code para crear migraciones Alembic de base de datos

Crea una migración Alembic a partir de la descripción del usuario. Argumento requerido: $ARGUMENTS (descripción del cambio de esquema).

La migración se escribe **siempre a mano**: `db/alembic/env.py` tiene `target_metadata = None`, así que `--autogenerate` produce un archivo vacío. Encenderlo no es trivial, porque el drift modelo↔base ya suma ~180 índices (ver la skill `alembic-migrations`, gotcha 5). Después de cambiar un modelo, copiar a mano en la migración los nombres de índice y los tipos exactos.

## Objetivo

- revisar estado actual de migraciones
- generar migración reversible y consistente con el esquema real
- validar el archivo generado y su impacto en documentación y tests

## Flujo de trabajo

### 1. Verificar estado actual

```bash
source .venv/bin/activate
alembic -c db/alembic.ini history
alembic -c db/alembic.ini current
```

### 2. Crear la migración

```bash
# Manual (único modo efectivo: target_metadata = None)
alembic -c db/alembic.ini revision -m "descripcion"
```

### 3. Implementar la migración

El archivo generado en `db/alembic/versions/` debe seguir esta estructura:

```python
# Nombre de archivo: XXXX_descripcion.py
# Ubicación de archivo: db/alembic/versions/XXXX_descripcion.py
# Descripción: Migración de base de datos

"""descripcion

Revision ID: xxxx
Revises: yyyy
Create Date: YYYY-MM-DD HH:MM:SS

"""
from alembic import op
import sqlalchemy as sa

revision = 'xxxx'
down_revision = 'yyyy'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Aplicar migración."""
    ...

def downgrade() -> None:
    """Revertir migración."""
    ...
```

### 4. Validar la migración

```bash
alembic -c db/alembic.ini upgrade head --sql
```

### 5. Aplicar

```bash
alembic -c db/alembic.ini upgrade head
alembic -c db/alembic.ini current
```

### 6. Verificar rollback

```bash
alembic -c db/alembic.ini downgrade -1
```

## Reglas obligatorias

1. Siempre implementar `downgrade()` salvo caso excepcional justificado.
2. Mantener encabezado obligatorio de 3 líneas en el archivo generado.
3. Usar nombres descriptivos para índices, constraints y revisiones.
4. No romper datos existentes sin advertirlo explícitamente.
5. Reflejar cambios de DB en `docs/db.md` y en el PR diario si corresponde.
6. Si la migración requiere pasos manuales de despliegue, documentarlos.

## Checklist de validación

- [ ] `upgrade()` implementado correctamente
- [ ] `downgrade()` implementado (reversible)
- [ ] Encabezado de 3 líneas presente
- [ ] No hay SQL o datos peligrosos sin justificación
- [ ] Índices definidos para columnas de búsqueda frecuente
- [ ] Constraints de integridad definidos
- [ ] Validación Alembic ejecutada o explicitada como pendiente
- [ ] PR diario actualizado con cambios de DB

## Referencia

Ver recetas de troubleshooting en `.github/skills/alembic-migrations/references/recetas.md`.
