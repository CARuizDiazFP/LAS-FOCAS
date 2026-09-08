# Nombre de archivo: 20260908_02_servicios_alias_ids_gin.py
# Ubicación de archivo: db/alembic/versions/20260908_02_servicios_alias_ids_gin.py
# Descripción: Índice GIN sobre app.servicios.alias_ids — habilita el self-join anti-ambigüedad
# reescrito a contención (`alias_ids @> ARRAY[...]`) del detector "Servicios sin ODF"

"""Índice GIN sobre app.servicios.alias_ids (self-join anti-ambigüedad)

Revision ID: 20260908_02
Revises: 20260908_01
Create Date: 2026-09-08

Segundo cuello de botella del detector "Servicios sin ODF" (Tarea 3), descubierto al VERIFICAR la
Tarea 1 — no estaba en el plan original.

La Tarea 1 agregó el btree parcial `ix_cromo_odf_conectores_servicio_resuelto` y confirmó con
`EXPLAIN ANALYZE` real que ese nodo pasó de `Seq Scan` a `Index Only Scan` (cost 31923 → 6736). Pero
el tiempo TOTAL de la query de detección apenas bajó de ~23.8s a ~20.8s, porque hay un SEGUNDO nodo
dominante, no relacionado: el self-join anti-ambigüedad de `app.servicios` contra sí misma
(heredado de `core/services/cromo/ingesta.py::_SQL_BUSCAR_SERVICIO`), que descarta ~41 millones de
filas por `Join Filter` en un `Nested Loop Anti Join` con `Seq Scan on servicios v2` repetido por
cada fila candidata:

    NOT EXISTS (SELECT 1 FROM app.servicios v2
                WHERE v2.id <> s.id
                  AND (s.servicio_id = ANY(v2.alias_ids)
                       OR s.numero_primer_servicio = ANY(v2.alias_ids)))

Escrito así es O(n²) en ejecución real aunque el planner lo estime barato (el cost-estimate no
correlaciona con el tiempo real para containment checks sobre arrays sin índice — el plan original
del plan de trabajo descartó el GIN justamente por mirar el cost, ~483 de ~37.828, y se equivocó).

Un GIN sobre `alias_ids` NO acelera `escalar = ANY(columna_array)` tal como está escrito: la
opclass default para arrays (`array_ops`) indexa `&&`, `@>`, `<@` y `=`, no `= ANY(...)`. Por eso
este índice viene acompañado del rewrite equivalente a contención en
`core/services/cromo/servicios_sin_odf.py`:

    v2.alias_ids @> ARRAY[s.servicio_id] OR v2.alias_ids @> ARRAY[s.numero_primer_servicio]

Semánticamente idéntico (verificado real: ambas formas dan las mismas 40 filas ambiguas sobre las
14.147 filas de `app.servicios` de dev, y el mismo universo de 2891 Servicios sin ODF). `alias_ids`
es `varchar(64)[]` y `servicio_id`/`numero_primer_servicio` son `varchar(64)`, así que
`ARRAY[<columna>]` resuelve a `character varying[]` sin necesidad de CAST explícito (confirmado
contra Postgres 16.13 real). El caso `numero_primer_servicio IS NULL` también se preserva:
`alias_ids @> ARRAY[NULL]` da `false` y `NULL @> ARRAY[x]` da `NULL` — ninguno de los dos es TRUE,
igual que el `= ANY(...)` original, así que el `EXISTS` decide lo mismo.

Los dos cambios sólo funcionan juntos, medido real contra `lasfocasdev-postgres`:

| forma de la subquery              | sin este GIN | con este GIN |
|-----------------------------------|--------------|--------------|
| `= ANY(v2.alias_ids)` (original)  | ~23.9s       | ~23.8s (sin cambio) |
| `v2.alias_ids @> ARRAY[...]`      | ~39.8s (peor)| **~11.6s**   |

Con ambos, el nodo pasa de `Seq Scan on servicios v2` (41M filas descartadas) a
`Bitmap Heap Scan` con un `BitmapOr` de dos `Bitmap Index Scan on ix_servicios_alias_ids_gin`.

Los ~11.6s de esa tabla son el estado INTERMEDIO, no el actual: después de este índice apareció un
tercer cuello de botella (el `NOT EXISTS` contra la CTE `resueltos AS MATERIALIZED`, ~46M filas
descartadas por `Join Filter`) y desarmarlo por De Morgan dejó la query en **~0.15s**. Ver la nota
de performance de `core/services/cromo/servicios_sin_odf.py`. Este índice sigue siendo necesario:
sin él la query vuelve a ~12s, y hay un test que lo verifica
(`tests/test_cromo_servicios_sin_odf_real_db.py::test_plan_del_listado_usa_los_dos_indices_sin_seq_scan_ni_cte`).

Índice completo (no parcial) a propósito: `alias_ids` es `NULL` en la mayoría de las filas y GIN ya
no indexa filas nulas/vacías por sí mismo, así que un `WHERE alias_ids IS NOT NULL` no ahorraría
nada y sólo agregaría una condición que el planner tendría que probar. Pesa 480 kB medido real.

Downgrade: dropea el índice.
"""

from __future__ import annotations

from alembic import op

revision = "20260908_02"
down_revision = "20260908_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_servicios_alias_ids_gin",
        "servicios",
        ["alias_ids"],
        schema="app",
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_servicios_alias_ids_gin", table_name="servicios", schema="app")
