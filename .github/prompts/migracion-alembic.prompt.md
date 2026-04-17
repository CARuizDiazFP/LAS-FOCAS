# Nombre de archivo: migracion-alembic.prompt.md
# Ubicación de archivo: .github/prompts/migracion-alembic.prompt.md
# Descripción: Prompt para crear migraciones Alembic de base de datos

---
name: Migración Alembic
description: "Crea o actualiza una migración Alembic con validaciones, downgrade y documentación asociada"
argument-hint: "Describe el cambio y opcionalmente el tipo, por ejemplo: agregar tabla usuarios, tipo autogenerate"
agent: "agent"
---

# Crear Migración Alembic

Crear una migración Alembic a partir de la descripción dada por el usuario. Si el usuario no especifica tipo, inferir si corresponde `autogenerate` o migración manual según el cambio pedido.

## Objetivo

- revisar estado actual de migraciones
- generar migración reversible y consistente con el esquema real
- validar el archivo generado y su impacto en documentación y tests

## Entradas esperadas

- descripción del cambio de esquema
- tipo sugerido: `autogenerate` o `manual`
- contexto adicional sobre tablas, columnas, índices o datos existentes

## Flujo de trabajo

### 1. Verificar estado actual

```bash
cd /home/focal/proyectos/LAS-FOCAS
alembic -c db/alembic.ini history
alembic -c db/alembic.ini current
```

### 2. Elegir estrategia de creación

Usar `revision --autogenerate` si el cambio está reflejado en modelos SQLAlchemy. Usar `revision -m` si requiere SQL manual, backfill, enums, correcciones idempotentes o transformaciones no detectables.

```bash
alembic -c db/alembic.ini revision --autogenerate -m "descripcion"
alembic -c db/alembic.ini revision -m "descripcion"
```

### 3. Implementar la migración

El archivo generado en `db/alembic/versions/` debe tener:

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

# revision identifiers
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
python db/alembic/versions/XXXX_*.py
```

### 5. Aplicar o dejar lista la migración

```bash
alembic -c db/alembic.ini upgrade head
alembic -c db/alembic.ini current
```

### 6. Verificar rollback cuando sea razonable

```bash
alembic -c db/alembic.ini downgrade -1
```

## Reglas obligatorias

1. Siempre implementar `downgrade()` salvo caso excepcional justificado.
2. Mantener encabezado obligatorio de 3 líneas en el archivo creado o editado.
3. Usar nombres descriptivos para índices, constraints y revisiones.
4. No romper datos existentes sin advertirlo explícitamente.
5. Reflejar cambios de DB también en documentación si aplica.
6. Si la migración requiere pasos manuales de despliegue, dejarlos documentados.

## Checklist de validación

- [ ] `upgrade()` implementado correctamente
- [ ] `downgrade()` implementado (reversible)
- [ ] Encabezado de 3 líneas presente
- [ ] No hay SQL o datos peligrosos sin justificación
- [ ] Índices para columnas de búsqueda frecuente
- [ ] Constraints de integridad definidos
- [ ] Validación Alembic ejecutada o explicitada como pendiente
- [ ] PR diario actualizado con cambios de DB

## Salida esperada

1. Crear o actualizar la migración en `db/alembic/versions/`.
2. Explicar si fue `autogenerate` o manual y por qué.
3. Dejar checklist de validación y compatibilidad.
4. Actualizar `docs/db.md` o el PR diario si corresponde.
