# Nombre de archivo: clientes_categoria.md
# Ubicación de archivo: docs/clientes_categoria.md
# Descripción: Módulo admin "Clientes por categoría" (C0–C6): reglas de precedencia, normalización, sincronización, lista oficial y regularización

# Clientes por categoría (C0–C6)

## Propósito

Un listado de clientes agrupados por categoría es la **fuente de verdad** de `servicios.categoria`. Cada
grupo (C6 a C0 y "Sin categorizar") es desplegable y está ordenado alfabéticamente. Admite edición
individual, masiva y por lista adjunta. Las ingestas (planilla SLA, Cromo, PROV) se conservan como fuentes
secundarias. Sólo Admin: `/admin/servicios/clientes-categoria` (`AdminClientesCategoria.vue`).

Decisiones y rulings: `docs/decisiones.md` (2026-10-14). Esquema: `docs/db.md` (tablas `clientes` y
`clientes_alias`, migración `20261014_01`).

## Semántica de la categoría

- `servicios.categoria` y `clientes.categoria`: `NULL` = sin categorizar; 0 a 6 válidos; **6 = sólo C6 real**.
  Nunca se usa 6 como default ni como reemplazo.
- `servicios.categoria` es una copia materializada de la categoría del cliente, así los lectores existentes
  (listados, filtros, informes) no cambian.
- `servicios.categoria_sla` guarda el "Nivel Cliente" crudo de la planilla SLA. Es el insumo de la moda.

## Precedencia de la categoría de un cliente

| Origen (`origen_categoria`) | Quién lo define | Valor |
|---|---|---|
| `LISTA` / `MANUAL` | Un admin (lista adjunta o edición en el módulo) | El que fijó. Gana siempre y la sync no lo recalcula. |
| `SLA` | La planilla | Moda de `categoria_sla` en 1 a 6 entre sus servicios; **empate → la más alta**. Se muestra como "C6 · SLA" cuando es 6 y no está en la Lista. |
| `AUTO` | Sin dato SLA | `0` si el cliente tiene al menos un servicio (son placeholders de Cromo/PROV); `NULL` si no tiene servicios. |

- `a_revisar = true` cuando los servicios de un cliente traen más de una categoría SLA distinta (1 a 6).
- Los servicios con excepción siguen votando en la moda con su `categoria_sla`.
- "Volver a automático" pasa el cliente a `AUTO` y recalcula.

## Herencia y excepción por servicio

- Un servicio toma la categoría de su cliente. La propagación **nunca** pisa un servicio con
  `categoria_excepcion = true`.
- Cambiar la categoría de un servicio (`PATCH /servicios/{id}/categoria`, `PATCH /servicios/bulk-categoria`
  o el detalle del servicio) marca la excepción.
- **Heredar** (`PATCH /servicios/{id}/categoria/heredar`) quita la excepción y re-sincroniza a su cliente.
- "Sin categorizar" no se puede fijar como excepción de un servicio puntual (0 a 6); para eso está Heredar.

## Normalización de nombres

`core/services/clientes_categoria_service.py::normalizar_clave_cliente`: `limpiar_clave` (sin acentos ni
puntuación) en mayúsculas, y se quitan **sufijos societarios al final**, repetidos si hace falta
(`SOCIEDAD ANONIMA`, `S A U`, `S A`, `S R L`, `SAIC`, `COOPERATIVO LTDO`, `INC`, `LTDA`, entre otros;
lista en `SUFIJOS_SOCIETARIOS`).

- Galicia: `BANCO DE GALICIA Y BUENOS AIRES SA` y `... S A U` dan la misma clave.
- ARSAT: `... SOCIEDAD ANONIMA ARSAT` y `... (ARSAT)` **no** colapsan (el sufijo no queda al final), por eso
  se vinculan con un alias manual.
- Cada cliente tiene al menos un alias (el propio nombre). Un alias vincula otra variante al mismo cliente.
  Agregar un alias que movería el único alias de un cliente `LISTA`/`MANUAL` se rechaza ("usar fusionar").
- **Fusionar** mueve los alias de los clientes origen al destino y borra los origen.

## Sincronización

`sincronizar_categorias(session, claves=None)` es set-based (SQL, no fila por fila): registra clientes y
alias nuevos, recalcula los de origen `SLA`/`AUTO` y propaga a `servicios` (salvo excepciones). Es
idempotente. Corre:

- Al editar en el módulo (categoría, lista, fusión, alias): sólo las claves afectadas.
- Tras la **ingesta Excel** (`POST /servicios/ingest`): sólo los clientes de la planilla. La planilla escribe
  `categoria_sla`; en filas existentes **conserva** `categoria`, y sólo la completa de forma provisoria si es
  NULL. Una celda vacía o fuera de rango no baja el valor previo. No hay fallback a 6.
- Tras el **refresco PROV** (on-demand y desde Slack, una sync por lote) y los scripts de backfill PROV.
- Con **Re-sincronizar** (`POST /clientes/sincronizar`): global.

Resiliencia (`core/services/clientes_categoria_hooks.py`): se ejecuta después del `commit` de la ingesta
con sesión propia. Si falla, se loguea `action=clientes_sync_error` y la ingesta sigue. El botón
Re-sincronizar o la próxima ingesta lo corrige.

Concurrencia: la sync y toda operación del módulo (categoría, lista, fusión, alias, heredar) toman primero
`pg_advisory_xact_lock(2026101401)` (`bloquear_categorias_clientes`), así una sync concurrente no pisa una
decisión del admin. Además el `UPDATE` de recálculo sólo toca clientes que siguen en `SLA`/`AUTO`. Efecto
esperado: mientras corre un Re-sincronizar global, las operaciones del módulo esperan a que termine.

## Lista oficial adjunta

- Formatos: `.txt` (un nombre por línea, UTF-8 o Latin-1), `.xlsx`, `.xlsm`, `.csv`. Máximo **5 MB**.
- El encabezado es **opcional**: si la primera fila tiene "Cliente" o "Nombre Cliente" se usa esa columna; si
  no, es la primera columna y la primera fila cuenta como nombre.
- Se elige la categoría destino (o "Sin categorizar") y el modo:
  - `agregar`: asigna la categoría con origen `LISTA` a los nombres de la lista.
  - `reemplazar`: además devuelve a `AUTO` a los clientes `LISTA` de esa categoría que no vienen en la lista.
- **Siempre primero la previsualización** (no escribe): sube, baja, sin cambio, clientes nuevos, nombres
  con sugerencias por similitud (para vincular como alias) y, en `reemplazar`, los que se quitan. Aplicar
  re-resuelve los nombres en el servidor.
- `categoria` es obligatoria en el pedido (un campo olvidado no debe aplicarse como "sin categorizar").

## Endpoints

**API interna** (`api/app/routes/clientes.py`, prefijo `/clientes`):

| Método y ruta | Uso |
|---|---|
| `GET /clientes/por-categoria` | Grupos `"6"`…`"0"`, `"sin"` con alias, servicios y excepciones. |
| `PATCH /clientes/categoria` | `cliente_ids`, `categoria` (o null) o `automatico=true`. |
| `POST /clientes/lista/previsualizar` | Diff de la lista (multipart con archivo o JSON con `nombres`). |
| `POST /clientes/lista/aplicar` | Aplica la lista. |
| `POST /clientes/fusionar` | `destino_id`, `origen_ids`. |
| `POST /clientes/{cliente_id}/alias`, `DELETE /clientes/alias/{alias_id}` | Alias manuales. |
| `POST /clientes/sincronizar` | Sync global. |

**Proxy web** (`web/app/main.py`, sólo admin y con CSRF en los que escriben): los mismos bajo
`/api/admin/clientes/...`, más `PATCH /api/servicios/{id}/categoria/heredar`. `GET /servicios/search` acepta
el token `sin` en `categoria`.

## Script de regularización

`scripts/clientes_categoria_regularizar.py`, una vez por entorno, **siempre primero con `--dry-run`**
(una transacción externa que se revierte: el resumen es lo que haría la corrida real).

Orden: sync global → alias `canónico | variante` del archivo → Lista C6 (`agregar`, categoría 6) → sync final
(la regularización retroactiva: los placeholders C0 de clientes C6 pasan a 6). Imprime un JSON con antes y
después por categoría, clientes `a_revisar` y nombres sin match.

Archivo por defecto: `scripts/data/clientes_c6_inicial.txt` (52 nombres y alias; `--archivo PATH` usa otro).

```bash
# dev
docker exec lasfocasdev-api python scripts/clientes_categoria_regularizar.py --dry-run
docker exec lasfocasdev-api python scripts/clientes_categoria_regularizar.py
# prod (después de la migración; revisar el dry-run con el usuario)
docker exec lasfocas-api python scripts/clientes_categoria_regularizar.py --dry-run
docker exec lasfocas-api python scripts/clientes_categoria_regularizar.py
```

**Dry-run en dev (2026-10-14):** servicios C6 2150 → 2177; 52 de 52 nombres de la Lista con match; 26
clientes `a_revisar`. C6 por SLA fuera de la Lista, que quedan "C6 · SLA": `BANCO ITAU ARGENTINA SA`,
`PRISMA MEDIOS DE PAGO SA` y los 3 clientes de prueba "CLIENTE SMOKE".

## Archivos

`core/services/clientes_categoria_service.py`, `core/services/clientes_categoria_hooks.py`,
`core/parsers/lista_clientes.py`, `api/app/routes/clientes.py`, `web/app/main.py`,
`web/frontend/src/admin/views/AdminClientesCategoria.vue` (+ `admin/components/clientes/`,
`admin/api/clientesCategoria.ts`).
