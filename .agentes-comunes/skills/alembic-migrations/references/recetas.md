# Nombre de archivo: recetas.md
# Ubicación de archivo: .agentes-comunes/skills/alembic-migrations/references/recetas.md
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

### Aplicar en dev una migración que todavía vive en un worktree (antes de integrar)

Los contenedores de dev no tienen `DATABASE_URL` en el entorno: la app arma la URL desde los Docker
Secrets. Por eso `alembic current` dentro del contenedor falla con *"password authentication failed
for user lasfocas"*. Le pasa también a `docker exec ... alembic` sobre `/app`, aunque la contraseña
esté bien (real, 2026-10-05). Receta: copiar el código del worktree a `/tmp/wt` del contenedor web de
dev **sin tocar `/app`**, y derivar la URL de `db.session.async_engine`, sin imprimirla:

```bash
docker exec lasfocasdev-web sh -c 'rm -rf /tmp/wt && mkdir -p /tmp/wt'
tar cf - core db modules | docker exec -i lasfocasdev-web tar xf - -C /tmp/wt
docker exec lasfocasdev-web sh -c 'cd /tmp/wt && export DATABASE_URL="$(python -c "from db.session import async_engine as e; print(e.url.set(drivername=\"postgresql+psycopg\").render_as_string(hide_password=False))")" \
  && alembic -c db/alembic.ini upgrade head && alembic -c db/alembic.ini downgrade -1 \
  && alembic -c db/alembic.ini upgrade head && alembic -c db/alembic.ini current'
docker exec lasfocasdev-web rm -rf /tmp/wt   # al terminar
```

Sólo para dev. Para prod está el procedimiento de deploy, con backup previo. Tomar el lease
`db:migrations` mientras se aplica.

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