# Nombre de archivo: db.md
# Ubicación de archivo: docs/db.md
# Descripción: Documentación del módulo de conexión a PostgreSQL

El módulo `api/app/db.py` establece una conexión a PostgreSQL utilizando SQLAlchemy y Psycopg 3.
La cadena DSN se construye a partir de variables de entorno:

- `POSTGRES_HOST`: dirección del servidor de base de datos.
- `POSTGRES_PORT`: puerto del servicio.
- `POSTGRES_DB`: nombre de la base de datos.
- `POSTGRES_USER`: usuario para la conexión.
- `POSTGRES_PASSWORD`: contraseña del usuario como fallback de transición.

En dev, la contraseña se lee primero desde `/run/secrets/db_password_v1`,
montado por Docker Compose desde `.secrets/Dev_db_password_v1.txt` (prefijo
`Dev_`). En producción (`deploy/compose.yml`) se usa el mismo mecanismo pero
con el archivo sin prefijo `.secrets/db_password_v1.txt`. Si el archivo no
existe, el código conserva el fallback a `POSTGRES_PASSWORD` para no bloquear
entornos locales antiguos.

**Atención:** si `DATABASE_URL`/`ALEMBIC_URL` está seteada en el `.env`
correspondiente, tiene prioridad sobre el secreto y lo anula por completo
(ver `_engine_url()`). Debe quedar comentada (no solo vacía) para que el
secret realmente se use.

La función `db_health` ejecuta una consulta simple `SELECT 1` y obtiene la versión del servidor
para verificar el estado de la base de datos.

## Reglas de persistencia

- Todo acceso nuevo a datos debe usar `AsyncSession` y `create_async_engine`.
- Evitar consultas sincrónicas en rutas y repositorios nuevos.
- Usar Pydantic en la capa de API para complementar la validación de datos.
- Mantener constraints, índices y migraciones reversibles en Alembic.

Se limpiaron imports innecesarios en los repositorios de conversaciones y mensajes para mantener el código conforme a PEP8.

## Infraestructura (cámaras, cables y servicios)

- Base común: `db/base.py` expone la base declarativa; en desarrollos nuevos preferir SQLAlchemy 2.0 style y sesiones async.
- Nuevas tablas en esquema `app` definidas en `db/models/infra.py`:

### Tabla `camaras`

| Columna       | Tipo                 | Descripción |
|---------------|----------------------|-------------|
| `id`               | Integer (PK)         | ID autoincremental. |
| `fontine_id`       | String(64), unique   | Referencia externa (opcional si se crea desde tracking). |
| `nombre`           | String(255), index   | Nombre/dirección de la cámara (requerido). |
| `latitud`          | Float                | Coordenada latitud (opcional). |
| `longitud`         | Float                | Coordenada longitud (opcional). |
| `direccion`        | String(255)          | Dirección alternativa (opcional). |
| `estado`           | Enum                 | `LIBRE`, `OCUPADA`, `BANEADA`, `DETECTADA`, `PENDIENTE_REVISION`, `NO_OPERATIVA`. |
| `origen_datos`     | Enum                 | `MANUAL`, `TRACKING`, `SHEET`, `INFERIDO`, `INFERIDO_CROMO`. |
| `camara_padre_id`  | FK → camaras, index, nullable | Jerarquía Cámara→Botella (2026-08-10): si está seteado, esta fila es una **Botella** y apunta a su Cámara padre (`camara_padre_id IS NULL`). Exactamente 2 niveles — `CHECK` anti-autoreferencia. Ver `docs/infra.md` sección "Jerarquía Cámara → Botellas". |
| `last_update`      | DateTime(tz)         | Última actualización. |

Relationship inverso desde 2026-08-11: `Camara.cromo_botellas` (`CromoBotella.camara_id`, ver tabla
`cromo_botellas` más abajo) — una Cámara padre puede tener Botellas legado (self-FK) **y** Botellas
Cromo a la vez, son colecciones independientes.

**Estados operables (desde 2026-08-11): sólo estos 4 son seteables** — `estados_disponibles` (`GET
/api/infra/camaras/{id}/estado`) y la validación de `POST /api/infra/camaras/{id}/estado` sólo
aceptan los siguientes:
- `LIBRE`: cámara disponible para nuevos servicios.
- `OCUPADA`: cámara en uso.
- `BANEADA`: cámara excluida de operaciones.
- `NO_OPERATIVA`: sin ninguna señal operativa real. **Ya no es el default de alta** (revertido
  2026-08-13, ver `docs/decisiones.md`) — sigue siendo un estado seteable/heredable válido (una
  Cámara reusada, o un grupo escalado al más restrictivo, puede legítimamente terminar acá), pero
  toda Cámara padre nueva sintetizada por `scripts/cromo_backfill_camara_padre.py`/
  `core/services/cromo/orfanas_service.py`/`core/services/cromo/camara_padre_service.py` nace ahora
  en `LIBRE`.

**Estados retirados de la asignación activa (2026-08-11), aún presentes en el enum de Postgres por
filas legado — no removibles sin recrear el tipo**:
- `DETECTADA`: cámara creada automáticamente desde tracking (pendiente de validación). Retirado —
  `scripts/retirar_estado_detectada.py` migró retroactivamente toda fila existente a su estado real
  (corrida real 2026-08-11: 1.053 filas → 100% `LIBRE`). Ningún código nuevo debe crear filas con
  este estado.
- `PENDIENTE_REVISION`: cámara auto-registrada por el listener de ingresos Slack al recibir una cámara desconocida. El *auto-registro* quedó retirado (2026-08-11, ver `app.ingresos_sin_match` más abajo) — el panel admin de aprobación sigue vigente sólo para las 34 filas legado ya existentes a esa fecha, no recibe filas nuevas.

**Origen de datos:**
- `MANUAL`: ingresada manualmente.
- `TRACKING`: detectada al procesar un archivo de tracking.
- `SHEET`: importada desde Google Sheets.
- `INFERIDO`: Cámara padre sintetizada automáticamente al agrupar Botellas legado (backfill Bot-N o alta en vivo vía `resolver_o_crear_padre`) — no proviene de ningún origen de datos real, es un artefacto de la jerarquía.
- `INFERIDO_CROMO` (2026-08-11): Cámara padre sintetizada por `scripts/cromo_backfill_camara_padre.py` a partir de un nombre de Botella Cromo — mismo concepto que `INFERIDO` pero de un pipeline distinto (permite distinguir con una query trivial qué backfill sintetizó cada fila).

### Tabla `cables`

| Columna            | Tipo         | Descripción |
|--------------------|--------------|-------------|
| `id`               | Integer (PK) | ID autoincremental. |
| `nombre`           | String(128)  | Nombre del cable. |
| `origen_camara_id` | FK → camaras | Cámara de origen. |
| `destino_camara_id`| FK → camaras | Cámara de destino. |

### Tabla `empalmes`

| Columna              | Tipo          | Descripción |
|----------------------|---------------|-------------|
| `id`                 | Integer (PK)  | ID autoincremental. |
| `tracking_empalme_id`| String(64), index | ID compuesto `{servicio_id}_{empalme_num}`. |
| `camara_id`          | FK → camaras  | Cámara donde se ubica. |
| `tipo`               | String(64)    | Tipo de empalme (opcional). |

### Tabla `servicios`

| Columna               | Tipo           | Descripción |
|-----------------------|----------------|-------------|
| `id`                  | Integer (PK)   | ID autoincremental. |
| `servicio_id`         | String(64), unique | ID de línea vigente ("final") de la familia (ej: "111995"). Desde 2026-08-26 lo calcula `core/services/servicios_consolidacion_service.py::consolidar_identidad_servicio` en cada ingesta SLA (el numérico más alto conocido de la familia) — antes se pisaba siempre con `numero_primer_servicio`, ignorando cualquier upgrade real. Si el módulo de tracking físico (`execute_upgrade`) ya lo dejó en un ID no numérico (ej. "O1C1"), la ingesta SLA no lo toca. |
| `alias_ids`           | `ARRAY(String(64))`, nullable | Historial de IDs superados de la familia (upgrades SLA vía `numero_linea`/`Línea Upgrade De-A`, y los que deja el módulo de tracking al hacer `execute_upgrade`). Consultado por el matching Cromo↔Servicio (`servicio_id = :n OR numero_primer_servicio = :n OR :n = ANY(alias_ids)`) — por eso un ID histórico de un pelo sigue resolviendo a la familia correcta. Cada entrada es una forma canónica (`str(int(...))` para numéricos, sin ceros a la izquierda ni espacios); nunca se agrega manualmente. |
| `numero_primer_servicio` | String(64), unique, index | ID lógico padre usado por ingesta SLA — ancla estable de la familia, nunca cambia una vez creada. |
| `nombre_cliente`      | String(255)    | Nombre del cliente en origen SLA. |
| `numero_linea`        | String(128), index | Línea asociada al servicio. |
| `tipo_servicio`       | String(128), index | Tipo comercial/técnico del servicio. |
| `sla_prometido`       | String(128)    | SLA comprometido en el origen. |
| `direccion`           | String(255)    | Dirección principal del servicio. |
| `localidad`           | String(128)    | Localidad del servicio. |
| `provincia`           | String(128)    | Provincia del servicio. |
| `direccion_2`         | String(255)    | Dirección complementaria. |
| `estado_servicio`     | String(128), index | Estado informado en la última ingesta SLA que lo tocó — pass-through directo del Excel, salvo la protección contra catch-up histórico descripta abajo (2026-08-31). |
| `cliente`             | String(255)    | Nombre del cliente (opcional). |
| `categoria`           | Integer, **nullable, sin default**, `CHECK BETWEEN 0 AND 6` | Categoría efectiva del servicio (C0 a C6). **`NULL` = sin categorizar**; `6` = sólo C6 real (desde la migración `20261014_01` ya no es el default, y el viejo 6 sin cliente pasó a NULL). Es una copia materializada de la categoría de su cliente (`app.clientes.categoria`): la escribe `core/services/clientes_categoria_service.py::sincronizar_categorias` salvo que `categoria_excepcion` sea `true`. Ya no la pisa la planilla SLA: el Excel sólo llena `categoria_sla` y, si `categoria` está en NULL, la completa de forma provisoria hasta la próxima sync. Sigue editable por servicio vía `PATCH /servicios/{id}/categoria` y `PATCH /servicios/bulk-categoria` (marcan `categoria_excepcion = true`). Detalle de reglas en `docs/clientes_categoria.md`. |
| `categoria_sla`       | SmallInteger, nullable, `CHECK BETWEEN 0 AND 6` | Nivel Cliente que trajo la planilla SLA (columna "Nivel Cliente"), sin interpretar. Es el dato con el que se calcula la moda por cliente. Una celda vacía o fuera de rango conserva el valor previo. Desde `20261014_01`. |
| `categoria_excepcion` | Boolean, `NOT NULL DEFAULT false` | `true` = un admin fijó la categoría de este servicio a mano y la propagación del cliente no lo pisa. `PATCH /servicios/{id}/categoria/heredar` lo vuelve a `false` y re-sincroniza al cliente. Desde `20261014_01`. |
| `es_verificable`      | Boolean, `NOT NULL DEFAULT false` | `True` si `tipo_servicio` ∈ {INT, RPV, ISI, ISIS, TLS, EWS} (`core/services/servicios_consolidacion_service.py::TIPOS_SERVICIO_VERIFICABLES`). Recalculado en cada ingesta SLA salvo que `es_verificable_override` no sea NULL. Desde 2026-08-26 (migración `20260825_02`, backfill inicial por `tipo_servicio` sobre las filas existentes). |
| `es_verificable_override` | Boolean, nullable | Corrección manual de admin vía `PATCH /servicios/{id}/verificable` (mismo patrón sin auditoría que `categoria`) — cuando no es NULL, la ingesta respeta este valor y no recalcula `es_verificable`. No tiene forma de volver a NULL ("automático") desde la UI todavía — un servicio corregido una vez queda fijo. |
| `origen_datos`        | enum `app.servicio_origen_datos` (`MANUAL`\|`TRACKING`\|`INGEST_EXCEL`\|`INFERIDO_CROMO`), `NOT NULL DEFAULT 'MANUAL'` | Distingue un `Servicio` real de un placeholder sintetizado por el matching Cromo↔Servicio (`INFERIDO_CROMO`, `categoria=0`). Mismo patrón que `CamaraOrigenDatos`. Desde 2026-08-14. |
| `nombre_archivo_origen`| String(255)   | Nombre del archivo de tracking original. |
| `raw_tracking_data`   | JSON           | Datos crudos del tracking parseado. |

**Consolidación de la cadena de upgrades e IDs finales (2026-08-26)**: cada `POST /servicios/ingest`
calcula, por `numero_primer_servicio`, el ID numérico más alto conocido entre `numero_linea`, los
punteros "Línea Upgrade (De)"/"(A)" del Excel, y el estado ya persistido (`servicio_id`/`alias_ids`
actuales) — `core/services/servicios_consolidacion_service.py::consolidar_identidad_servicio`
(función pura, sin acceso a DB, con fuzz-testing de 363k casos verificando que dos formas del mismo
entero nunca coexisten en el resultado). El ganador se escribe en `servicio_id` (el mismo campo que
ya leen el bot de Slack "Validador de Cables" y `CableDetalleCromoView.vue`, sin cambios en esos
módulos) y todo lo superado queda en `alias_ids`.

**`estado_servicio` no se degrada por un catch-up histórico de Excel** (2026-08-31): `consolidar_identidad_servicio`
también devuelve `avanza_por_excel` (bool) — si ESTE Excel aporta el ID de línea más alto conocido de
la familia, o si ese máximo ya estaba en la DB antes de esta ingesta (típicamente un archivo viejo
subido después para completar el histórico de IDs). `resolver_estado_servicio` (mismo módulo) usa ese
flag: cuando `avanza_por_excel=False` y el `estado_servicio` ya persistido es `"Activo"`, el Excel NO
puede degradarlo a otro valor — sólo el ID entra a `alias_ids` como de costumbre. Cuando el Excel sí
avanza la identidad, es la fuente más vigente conocida y su `estado_servicio` se respeta tal cual
(incluida una "Baja" legítima). Regla de negocio confirmada por el usuario tras reportar servicios
"Baja" que en realidad estaban activos; investigación completa (sin causa de código para el dato ya
persistido, sólo esta protección hacia adelante) en `docs/decisiones.md`, entrada 2026-08-31 (histórico
de IDs + estado Baja/Activo).

**Fusión de placeholders Cromo al liberar un `servicio_id` ya ocupado** (2026-08-26): como
`servicio_id` es `UNIQUE`, el ID final calculado puede coincidir con el de OTRA fila ya existente —
típicamente un placeholder `INFERIDO_CROMO` (ver abajo). Cuando esa fila es un placeholder puro
(nunca tocado por tracking físico: sin filas en `rutas_servicio` ni en `servicio_empalme_association`
colgadas), `ingest_servicios` reasigna sus referencias (`cromo_servicio_match.servicio_id`,
`rutas_servicio.servicio_id`; `servicio_empalme_association` se borra, no se reasigna, por su PK
compuesta `(servicio_id, empalme_id)`) y lo elimina, liberando el ID para la familia real — mismo
patrón que el merge de Cámaras (`docs/decisiones.md`, entrada 2026-08-14). Si la fila en colisión NO
es un placeholder puro (origen `MANUAL`/`INGEST_EXCEL`, o un placeholder ya usado por tracking) NO se
fusiona automáticamente — la familia no pisa su `servicio_id`, pero el ID igual queda en `alias_ids`,
y se loggea `evento=servicio_id_colision_no_fusionable`. Verificado real contra dev con la ingesta
completa de `Servicios C4.xlsx` (1230 filas): 176 fusiones, 0 colisiones no fusionables, 0
`cromo_servicio_match` huérfanos.

**Placeholders de `origen_datos=INFERIDO_CROMO`** (2026-08-14): `core/services/cromo/ingesta.py::fase_servicios`
crea un `Servicio` placeholder (`categoria=0`) cuando un pelo Cromo referencia un `servicio_numero` sin
match y ese número es "plausible" (longitud 4-6 dígitos, ver `core/services/cromo/parser.py::es_numero_servicio_plausible`)
— antes esos casos quedaban sólo como traza (`CromoServicioMatch.servicio_id = NULL`), nunca creaban
fila. Backfill retroactivo (`scripts/cromo_backfill_placeholders_servicios.py`) corrido contra dev el
2026-08-14: 9.054 placeholders creados, 112.340 filas de `cromo_servicio_match` resueltas, 3.144 quedaron
sin resolver (números de 1-3 u 8-10 dígitos, basura de parseo). Un ingest real por Excel
(`POST /servicios/ingest`) reetiqueta el placeholder a `origen_datos=INGEST_EXCEL` cuando lo enriquece
por el mismo `numero_primer_servicio` (nunca toca `categoria`, que es admin-only).

**Integración con la API PROV — `origen_datos=INGEST_PROV` y dos tablas nuevas** (2026-09-02):
`app.servicio_origen_datos` gana un nuevo valor de enum, `INGEST_PROV`, para distinguir un
`Servicio` enriquecido/actualizado por la integración con la API interna PROV
(`https://prov.metrotel.com.ar/api/v1/ADMEQ/API_Contexto_Servicio`) — vía `POST
/servicios/prov/refrescar` (on-demand) o `scripts/servicios_backfill_prov.py` (masivo) — de uno
tocado por Excel (`INGEST_EXCEL`) o tracking físico. Se agrega vía `ALTER TYPE ... ADD VALUE`
dentro de `op.get_context().autocommit_block()` (migración `20260902_01`) — misma técnica (no el
mismo enum) que `db/alembic/versions/20260811_01_cromo_botella_camara_padre.py` usó por primera vez
en este repo para agregar valores a un enum ya existente (`app.camara_estado`/`app.camara_origen_datos`,
un enum distinto de `app.servicio_origen_datos`); el valor `INFERIDO_CROMO` de `app.servicio_origen_datos`
en sí se creó de una vez vía `CREATE TYPE` (`20260814_02_servicios_origen_datos.py`) y nunca antes se
había extendido este enum con `ADD VALUE`. No se puede revertir un `ADD VALUE` en PostgreSQL 11+, así
que el `downgrade()` de la migración deja `INGEST_PROV` en el enum aunque borre las dos tablas.
`core/services/prov/ingesta.py::ingerir_contexto_prov` pisa `origen_datos` a `INGEST_PROV`
**incondicionalmente** en cada ingesta/refresh exitoso — no existe ninguna jerarquía de "orígenes más
autoritativos" implementada hoy en el repo (ni acá, ni en el endpoint, ni en el backfill). Mismo
criterio que ya usa `POST /servicios/ingest` (Excel), que también re-etiqueta `origen_datos`
incondicionalmente en cada upsert (`api/app/routes/servicios.py::ingest_servicios`,
`set_map["origen_datos"] = excluded.origen_datos`).

Dos tablas hijas de `Servicio`, mismo espíritu que `rutas_servicio`: **se reescriben completas
(delete + reinsert) en cada ingesta/refresh**, porque PROV siempre devuelve la cadena de upgrades y
los equipos de última milla completos y vigentes — nunca un delta parcial que se pueda mergear fila
a fila.

### Tabla `servicios_historial_id`

| Columna             | Tipo                 | Descripción |
|---------------------|----------------------|-------------|
| `id`                | Integer (PK)         | ID autoincremental. |
| `servicio_id`       | FK → `servicios.id`, `ondelete=CASCADE`, index | Servicio dueño de este eslabón. Borrar el `Servicio` borra en cascada todo su historial. |
| `numero_id`         | String(64)           | Un ID de la cadena de upgrades (`cadena_upgrade[*].nro_servicio` de PROV). |
| `orden`             | Integer              | Posición en la cadena: `0` = ID vigente, crece hacia atrás (más viejo). |
| `fecha_instalacion` | Date, nullable       | `cadena_upgrade[*].fecha_instalacion`. |
| `fecha_baja`        | Date, nullable       | `cadena_upgrade[*].fecha_baja` (`null` en el eslabón vigente). |
| `estado_comercial`  | String(128), nullable| Valor crudo de PROV para este eslabón (`INSTALADO`/`DADO BAJA`) — sin traducir; la traducción a `Servicio.estado_servicio` sólo se aplica al eslabón vigente. |
| `motivo_baja`       | String(255), nullable| `cadena_upgrade[*].motivo_baja` (ej. `"UPGRADE"`). |
| `es_vigente`        | Boolean, `NOT NULL DEFAULT false` | `true` sólo en el eslabón con `orden=0`. |
| `created_at`        | DateTime(tz)         | Fecha de la última ingesta/refresh que reescribió la fila. |

No reemplaza `Servicio.alias_ids` (que sigue siendo la fuente que consulta
`consolidar_identidad_servicio` y el matching Cromo↔Servicio): esta tabla existe porque `alias_ids`
es un `ARRAY(String)` plano que no puede guardar fecha/motivo/estado por ID — ver la entrada
2026-09-02 de `docs/decisiones.md` sobre por qué esto no reutiliza el diseño de `alias_ids` del
2026-08-25. Si PROV no trae `cadena_upgrade` (servicio sin upgrades), la ingesta escribe una única
fila sintética con `numero_id=nro_servicio_original`, `orden=0`, `es_vigente=true` y
`estado_comercial`/`fecha_instalacion` tomados del nivel superior del payload (`creacion`).

### Tabla `servicios_equipos_ultima_milla`

| Columna       | Tipo                 | Descripción |
|---------------|----------------------|-------------|
| `id`          | Integer (PK)         | ID autoincremental. |
| `servicio_id` | FK → `servicios.id`, `ondelete=CASCADE`, index | Servicio dueño de este extremo. |
| `extremo`     | Integer              | `1` o `2` — la mayoría de los servicios tiene un solo extremo; los que traen `Nodo2`/`Equipo2`/`Port2` en el payload de PROV tienen dos. La cardinalidad la decide el payload, no una regla fija por `tipo_servicio`. |
| `nodo`        | String(255), nullable| `Nodo{N}` de PROV. |
| `equipo`      | String(255), nullable| `Equipo{N}` de PROV. |
| `puerto`      | String(128), nullable| `Port{N}` de PROV. |
| `direccion`   | String(255), nullable| `Direccion{N}` de PROV (por extremo; distinto de `Servicio.direccion`, que guarda el extremo 1 a nivel del propio `Servicio`). |
| `provincia`   | String(128), nullable| `Provincia{N}` de PROV. |
| `created_at`  | DateTime(tz)         | Fecha de la última ingesta/refresh que reescribió la fila. |

Relaciones nuevas en `Servicio`: `historial_ids` (ordenada por `orden`, `cascade="all,
delete-orphan"`) y `equipos_ultima_milla` (mismo cascade). Ambas tablas se leen (sin llamar a PROV)
desde `GET /servicios/detail`, que extiende su `response_model` con `historial_ids`/
`equipos_ultima_milla` — decisión explícita para no acoplar la vista de detalle al rate-limit de
PROV. Se escriben desde `core/services/prov/ingesta.py::ingerir_contexto_prov`, invocado tanto por
`POST /servicios/prov/refrescar` (on-demand, un servicio) como por
`scripts/servicios_backfill_prov.py` (masivo, respetando el rate limit de 5 req/s). Ver
`docs/superpowers/specs/2026-09-02-servicios-prov-integracion-design.md` para los payloads reales
de PROV que fijaron este mapeo.

### Tabla `servicios_sync_prov` (2026-09-23)

| Columna                    | Tipo                  | Descripción |
|----------------------------|-----------------------|-------------|
| `id`                       | Integer (PK)          | ID autoincremental. |
| `servicio_id`              | FK → `servicios.id`, `ondelete=CASCADE`, **UNIQUE** | Una fila por `Servicio` — nunca un historial de intentos, sólo el estado vigente. |
| `ultima_sincronizacion_ok` | DateTime(tz), `NOT NULL` | Momento del último refresco EXITOSO contra PROV. `NOT NULL` porque el único punto de escritura (el upsert al final de `ingerir_contexto_prov`) sólo corre con un contexto ya validado como éxito. |
| `ultimo_intento`           | DateTime(tz), nullable | Momento del último intento, exitoso o no. Hoy siempre coincide con `ultima_sincronizacion_ok` (el embudo actual sólo escribe en éxito); queda separado para que un futuro camino de fallo lo actualice sin tocar la fecha de la última sincronización que sí funcionó. |
| `ultimo_error`             | Text, nullable        | Detalle del último fallo, si lo hubo. Se limpia (`NULL`) en cada escritura exitosa — un error viejo no queda pegado después de un refresco que sí funcionó. |
| `nro_servicio_consultado`  | String(64), nullable  | Número efectivamente consultado a PROV (`parseado.nro_servicio_original`) — trazabilidad de auditoría. |
| `created_at` / `updated_at`| DateTime(tz), `NOT NULL` | Auditoría estándar, calculada en Python por el upsert (mismo criterio que `servicios_historial_id`). |

Tabla nueva y no una columna en `Servicio`, por tres razones (ver `docs/decisiones.md`, entrada
2026-09-23 "Tabla `app.servicios_sync_prov`"): `Servicio` la escriben tres ingestas distintas (Excel,
PROV, placeholders Cromo) que re-etiquetan `origen_datos` incondicionalmente en cada una — una
columna ahí heredaría ese mismo "pisado por ingesta ajena"; el estado de *fallo* no es un atributo de
dominio del Servicio; y separar la escritura permite que un futuro camino de fallo actualice sólo el
estado de sincronización.

Se escribe en el mismo único embudo que `servicios_historial_id`/`servicios_equipos_ultima_milla`
(`ingerir_contexto_prov`, upsert `ON CONFLICT (servicio_id) DO UPDATE`). Se lee en batch — nunca una
query por servicio — desde `core/services/prov/frescura.py` (`servicios_vencidos`/
`servicios_vencidos_sync`, versión async y sync), que alimenta las Tasks 8/10 (comandos de Slack
sobre servicios) con el umbral `PROV_FRESCURA_HORAS` (default 48 h, ver `docs/bot.md`). Arranca
vacía: hasta que corra `scripts/servicios_backfill_prov.py`, todo `servicio_id` consultado vuelve
"vencido" por el `LEFT JOIN` con `ultima_sincronizacion_ok IS NULL` — no es un bug de la consulta,
es el estado real de un 92,5% de los servicios que nunca pasó por PROV (medido real, ver
`docs/bot.md`).

### Tablas `clientes` y `clientes_alias` (2026-10-14)

Fuente de verdad de la categoría (C0 a C6) por cliente. Reglas completas en `docs/clientes_categoria.md`.
Migración `20261014_01`. Modelos `Cliente`, `ClienteAlias` y `ClienteOrigenCategoria` en `db/models/infra.py`.

**`app.clientes`**: un registro por `clave` normalizada (mayúsculas, sin sufijos societarios).

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | Integer (PK) | |
| `nombre` | String(255) | Nombre para mostrar: el más frecuente entre sus servicios, o el de la lista. |
| `clave` | String(255), unique | Salida de `normalizar_clave_cliente`. |
| `categoria` | SmallInteger, nullable, `CHECK BETWEEN 0 AND 6` | `NULL` = sin categorizar. |
| `origen_categoria` | enum `app.cliente_origen_categoria` (`LISTA`\|`MANUAL`\|`SLA`\|`AUTO`), `NOT NULL DEFAULT 'AUTO'` | Quién definió la categoría. `LISTA`/`MANUAL` los fija un admin y la sync no los recalcula. `SLA` = moda de `categoria_sla`. `AUTO` = 0 si el cliente sólo tiene placeholders, o NULL sin datos. |
| `a_revisar` | Boolean, `NOT NULL DEFAULT false` | `true` si sus servicios traen más de una categoría SLA distinta (1 a 6). |
| `creado_en`, `actualizado_en` | DateTime(tz) | `actualizado_en` tiene `onupdate`. |
| `actualizado_por` | String(120), nullable | Usuario (`X-Usuario`) del último cambio manual o de lista. |

**`app.clientes_alias`**: variantes del nombre que resuelven a un cliente.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | Integer (PK) | |
| `clave` | String(255), unique | Clave normalizada de la variante. |
| `nombre_original` | String(255) | Texto tal como llegó. |
| `cliente_id` | FK `app.clientes.id` `ON DELETE CASCADE`, índice `ix_clientes_alias_cliente_id` | |
| `origen` | String(10), `CHECK IN ('AUTO','MANUAL')` | `AUTO` lo crea la sync; `MANUAL` lo vincula un admin (o el script de regularización). |

**Semántica de `NULL`:** en `servicios.categoria` y en `clientes.categoria`, `NULL` significa "sin categorizar" y
es un valor válido. Los lectores que arman filtros o textos deben tratarlo (el filtro de `/servicios/search`
acepta el token `sin`). Nunca usar 6 como reemplazo.

**Sin FK** entre `servicios.nombre_cliente` y `clientes`: el vínculo es por la clave calculada en Python
(`normalizar_clave_cliente`) y la sync lo resuelve con una tabla temporal, en SQL set-based.

### Tabla `servicio_empalme_association` (Legacy)

Tabla intermedia N-a-N entre `servicios` y `empalmes`. Es legacy pero **sigue viva**: el alta y los
merges de tracking (`core/services/infra_service.py`) la escriben en paralelo a las rutas, y la leen la
búsqueda por servicio de `api/app/routes/infra.py` y el chequeo de placeholders de
`api/app/routes/servicios.py` (en dev, 2026-10-26: 2967 filas de 49 servicios). Qué falta para
retirarla: ver el comentario sobre la tabla en `db/models/infra.py`.
**Para nuevas implementaciones usar `rutas_servicio` + `ruta_empalme_association`.**

| Columna      | Tipo         | Descripción |
|--------------|--------------|-------------|
| `servicio_id`| FK → servicios (PK) | ID del servicio. |
| `empalme_id` | FK → empalmes (PK)  | ID del empalme. |

---

## Versionado de Rutas (Nuevo modelo)

A partir de la migración `20260110_01`, se introduce un sistema de versionado de rutas similar a "branches" de Git.
Cada servicio puede tener múltiples rutas (Principal, Backup, Alternativa) con su propio conjunto de empalmes.

### Tabla `rutas_servicio`

| Columna               | Tipo                | Descripción |
|-----------------------|---------------------|-------------|
| `id`                  | Integer (PK)        | ID autoincremental. |
| `servicio_id`         | FK → servicios      | Servicio al que pertenece la ruta. |
| `nombre`              | String(255)         | Nombre de la ruta (ej: "Principal", "Backup Norte"). |
| `tipo`                | Enum(ruta_tipo)     | `PRINCIPAL`, `BACKUP`, `ALTERNATIVA`. |
| `cantidad_pelos`      | Integer, nullable   | Cantidad de pelos de la ruta, extraída del tracking (migración `20260113_01`). |
| `hash_contenido`      | String(64)          | SHA256 del contenido normalizado del tracking. |
| `activa`              | Boolean             | Si la ruta está activa (true por defecto). |
| `nombre_archivo_origen`| String(255)        | Nombre del archivo de tracking original. |
| `contenido_original`  | Text                | JSON parseado del tracking. |
| `raw_file_content`    | Text                | Contenido exacto del `.txt` original (migración `20260112_02`); lo adjuntan las notificaciones de baneo. |
| `created_at`          | DateTime(tz)        | Fecha de creación. |
| `updated_at`          | DateTime(tz)        | Última actualización. |

**Tipos de ruta:**
- `PRINCIPAL`: Ruta principal del servicio (solo una activa por servicio).
- `BACKUP`: Ruta de respaldo.
- `ALTERNATIVA`: Ruta alternativa para casos especiales.

### Tabla `ruta_empalme_association`

Tabla intermedia N-a-N entre `rutas_servicio` y `empalmes`:

| Columna     | Tipo               | Descripción |
|-------------|--------------------| ------------|
| `ruta_id`   | FK → rutas_servicio (PK) | ID de la ruta. |
| `empalme_id`| FK → empalmes (PK) | ID del empalme. |
| `orden`     | Integer            | Orden del empalme en la secuencia de la ruta. |

### Tabla `puntos_terminales`

Extremos A y B de una ruta (ODF, nodo o rack donde empieza y termina el tracking). Modelo
`PuntoTerminal` (`db/models/infra.py`), migración `20260113_01_puntos_terminales.py`.

| Columna                | Tipo                        | Descripción |
|------------------------|-----------------------------|-------------|
| `id`                   | Integer (PK)                | ID autoincremental. |
| `ruta_id`              | FK → `rutas_servicio.id` `ON DELETE CASCADE`, indexado | Ruta a la que pertenece. |
| `tipo`                 | Enum `punto_terminal_tipo` (`A`, `B`) | Punta A (origen) o B (destino). |
| `sitio_descripcion`    | String(255), nullable       | Sitio, p. ej. `ODF MAIPU 316 1`. |
| `identificador_fisico` | String(255), nullable       | Posición física, p. ej. `RACK 1 BANDEJA 2`. |
| `pelo_conector`        | String(64), nullable        | Par pelo-conector, p. ej. `P09-C10`. |

**Claves:** `UNIQUE (ruta_id, tipo)` (`uq_punto_terminal_ruta_tipo`): a lo sumo una punta A y una B
por ruta. La migración crea la tabla e índice `ix_app_puntos_terminales_ruta_id` con SQL crudo
(`CREATE ... IF NOT EXISTS`) para no recrear el enum. Acceso: `RutaServicio.puntos_terminales` y
las propiedades `punta_a`/`punta_b`. La misma migración agregó `servicios.alias_ids`,
`empalmes.es_transito` y `rutas_servicio.cantidad_pelos`.

### Relaciones del modelo de rutas

- `Servicio.rutas`: Lista de rutas del servicio (1-a-N).
- `RutaServicio.servicio`: Servicio al que pertenece (N-a-1).
- `RutaServicio.empalmes`: Empalmes de la ruta en orden (N-a-N).
- `Empalme.rutas`: Rutas que pasan por el empalme (N-a-N).

### Propiedades helper en Servicio

- `servicio.ruta_principal`: Retorna la ruta de tipo PRINCIPAL activa (o None).
- `servicio.rutas_activas`: Lista de rutas activas del servicio.

---

## API de Ingesta Inteligente (Patrón "Portero")

El sistema implementa una lógica de ingesta en 2 pasos para manejar conflictos:

### Paso 1: Análisis (`POST /api/infra/trackings/analyze`)

Analiza el archivo de tracking sin modificar la base de datos.

**Escenarios posibles:**
- `NEW`: El servicio no existe, se puede crear.
- `IDENTICAL`: El archivo es idéntico a una ruta existente.
- `CONFLICT`: El servicio existe pero el contenido difiere.
- `ERROR`: Error durante el análisis.

### Paso 2: Resolución (`POST /api/infra/trackings/resolve`)

Ejecuta la acción elegida por el usuario:

| Acción       | Descripción |
|--------------|-------------|
| `CREATE_NEW` | Crea nuevo servicio con ruta Principal. |
| `MERGE_APPEND` | Agrega empalmes nuevos a ruta existente (unión). |
| `REPLACE`    | Reemplaza todos los empalmes de una ruta. |
| `BRANCH`     | Crea nueva ruta bajo el mismo servicio. |

### Endpoints adicionales

- `GET /api/infra/servicios/{id}/rutas`: Lista todas las rutas de un servicio.
- `GET /api/infra/rutas/{id}/empalmes`: Lista empalmes de una ruta específica.

### Tabla `ingresos`

| Columna            | Tipo           | Descripción |
|--------------------|----------------|-------------|
| `id`               | Integer (PK)   | ID autoincremental. |
| `camara_id`        | FK → camaras   | Cámara (o Botella legado) de ingreso. |
| `cromo_botella_id` | FK → cromo_botellas.n_id (`ON DELETE SET NULL`), nullable | Botella Cromo específica del movimiento (migración `20260831_02`) — `null` cuando fue sobre la cámara padre directamente. |
| `tecnico_id`       | String(128)    | Nombre/ID del técnico. Hasta el fix de 2026-09-04 guardaba el ID crudo de Slack (ej. `"U03DPFK0Q69"`) tal cual llegaba en el mensaje. **Desde ese fix**, las filas nuevas guardan el NOMBRE RESUELTO del técnico (vía `modules/slack_baneo_notifier/slack_user_resolver.py::resolver_nombre_tecnico`, que llama Slack `users.info`) — el nombre de columna se mantiene sin cambios (evita una migración de rename + actualizar consumidores fuera de alcance de ese fix). Filas escritas ANTES de ese deploy pueden todavía tener el ID crudo si nunca se cerraron con un Egreso posterior a la resolución. El cierre de un Egreso matchea contra AMBOS valores (nombre resuelto y, si se conoce, el `slack_user_id` crudo del mismo evento — ver `core/services/ingreso_service.py::_tecnico_id_filtro`) para poder cerrar tanto filas viejas como nuevas. |
| `tipo`             | Enum `ingreso_tipo` | `INGRESO` \| `EGRESO` \| `INTENTO_BLOQUEADO` (migración `20260904_01`, default `INGRESO` para todo el histórico previo). Distingue un ingreso/egreso real de un intento bloqueado por baneo del grupo — ambos `INGRESO` "en curso" e `INTENTO_BLOQUEADO` comparten `fecha_fin IS NULL`, así que cualquier query de "ingreso activo" debe filtrar `tipo == 'INGRESO'` explícitamente (ver `camara_estado_service.get_camara_estado_contexto`, `ingreso_service.py` y `protection_service.py::_determinar_estado_restauracion`). |
| `fecha_inicio`     | DateTime(tz)   | Fecha/hora de inicio. `null` en un Egreso huérfano sin Ingreso previo detectado. |
| `fecha_fin`        | DateTime(tz)   | Fecha/hora de fin. `null` tanto en un `INGRESO` real "en curso" como en un `INTENTO_BLOQUEADO` (nunca se cierra con un Egreso, por diseño) — no alcanza con mirar sólo esta columna para saber si el movimiento sigue "abierto", hay que mirar `tipo`. |
| `thread_ts`        | `VARCHAR(32)`, nullable, index (2026-09-23, migración `20260923_01`) | `ts` del hilo de Slack donde se originó el movimiento. Hasta esta migración `app.ingresos` no guardaba nada del hilo — sólo `ingresos_sin_match` lo hacía, y sólo para los casos que no matchearon. Filas anteriores a esta fecha quedan con `NULL`; se resuelven por los niveles 2 y 3 de la cascada de `core/services/ingreso_correccion_service.py::resolver_contexto_hilo` (ver más abajo). En el camino "Egreso" que **cierra** una fila `Ingreso` existente, este campo **no se pisa** — conserva el del ingreso original. |
| `canal_id`         | `VARCHAR(32)`, nullable (2026-09-23) | Canal de Slack del movimiento. Mismo criterio de no-pisado en el camino de cierre. |
| `anulado_at` / `anulado_por` / `anulado_motivo` | `TIMESTAMPTZ` / `VARCHAR(128)` / `TEXT`, nullable (2026-10-23, migración `20261023_01`) | Baja lógica desde el portal (admin) de un ingreso que nunca ocurrió. La fila se conserva. CHECK `ck_ingresos_anulado_coherente`: si `anulado_at` no es NULL, autor y motivo son obligatorios. |

**Ingreso vigente** (desde 2026-10-23): toda query que decide estado a partir de esta tabla filtra,
además de `tipo`, `Ingreso.vigente()` (`anulado_at IS NULL`). "Ingreso activo" es entonces
`tipo = 'INGRESO' AND fecha_fin IS NULL AND anulado_at IS NULL`. Lectores filtrados:
`camara_estado_service.get_camara_estado_contexto`, `protection_service._determinar_estado_restauracion`,
`ingreso_service.registrar_movimiento_ingreso` (camino Egreso) y `registrar_egreso_historico`,
`ingreso_correccion_service.resolver_contexto_hilo` (nivel 1) y `_ingresos_abiertos`,
`ingreso_reproceso_service._ya_registrado` y `fo_monitor/motor.py` (`detectar_ingresos`,
`detectar_egresos`). `Forzar egreso #<id>` y el egreso web rechazan un anulado con
`resultado='INGRESO_ANULADO'`, y `cerrar_ingreso_forzado` lo rechaza como defensa en profundidad. **No**
filtran: los merges de Cámara/Botella (reasignan todas las filas, anuladas incluidas),
`camara_botella_delete_service._bloqueo_camara` y el `DELETE` de cámara pendiente (una fila anulada
también bloquea el borrado: es historial) ni la marca de agua de FO Monitor (`cargar_config`).

**Mover / anular desde el portal** (`ingreso_correccion_service.mover_ingreso_web` /
`anular_ingreso_web`, admin): una fila de auditoría por invocación (`origen='web'`), incluidos los
rechazos. En el camino exitoso el cambio (ingreso + FO Monitor) y su fila de auditoría se confirman en
un **único** `commit()`: si la auditoría falla, se revierte todo y la excepción llega al endpoint
(500 con ref). Mover cambia `camara_id` y deja `cromo_botella_id` en NULL salvo una `CromoBotella`
vigente del destino; el destino tiene que ser una Cámara raíz (`camara_padre_id IS NULL`; si no,
`DESTINO_NO_RAIZ`; una `PENDIENTE_REVISION` se acepta); no mueve un anulado ni al mismo par
cámara/botella; un ingreso abierto se mueve abierto.
Anular exige motivo (3 a 500 caracteres) y no re-anula. Ninguna de las dos escribe `Camara.estado` ni
reabre el `IngresoSinMatch` que hubiera resuelto el ingreso. FO Monitor: las intervenciones vinculadas
en un estado abierto (`motor.ESTADOS_ABIERTOS`) siguen el cambio, salvo que tengan otros ingresos
vigentes vinculados que no acompañan el cambio ("Botella 1 y 2" del mismo hilo; motivo
`OTROS_INGRESOS_VIGENTES`), en cuyo caso se dejan como están:
- **Anular:** pasan a `CANCELADA` con `cerrada_at`; sus consultas `PENDIENTE` también pasan a `CANCELADA`.
- **Mover:** se reubican en el destino recalculando el alcance con `fo_monitor.alcance.resolver_alcance`
  (sólo DB, sin red) y reemplazando `fomon_intervencion_servicios` (vía `motor.congelar_alcance`); la
  botella objetivo es la elegida o la Botella 1 del destino. Las consultas `PENDIENTE` se cancelan
  (`error='alcance_recalculado'`) y `PRE_EN_CURSO`/`POST_EN_CURSO` vuelven a `PRE_PENDIENTE`/`POST_PENDIENTE`
  para que `planificar_consultas` cree las del alcance nuevo en el próximo tick. Siempre se limpia
  `aviso_ts` (nada más sale en el hilo de la cámara vieja, que queda en Slack): antes de la PRE el
  próximo tick publica un aviso raíz nuevo; después de la PRE (`EN_CURSO`, `SIN_EGRESO`, `POST_*`) el
  motor no republica la raíz y la intervención deja de avisar por Slack (sus resultados siguen en el
  panel), y si el alcance nuevo tiene servicios se marca `sin_linea_base=True`. Si la
  intervención ya tiene alguna consulta `ENVIADA`, `RESPONDIDA` o `TIMEOUT` (ya hubo comunicación con
  burritoIA sobre el alcance viejo) **no** se recalcula: queda como está, con motivo
  `CONSULTAS_YA_ENVIADAS` (el ingreso se mueve igual).

### Tabla `ingresos_correcciones` (2026-09-23) — auditoría append-only de `Forzar ingreso`/`Forzar egreso`

Un registro por cada ejecución de los comandos de corrección manual de Slack (ver `docs/bot.md`,
sección "Actualización 2026-09-23"), exitosa o no — **incluidos los rechazos**. Tabla nueva y no una
extensión de `ingresos_sin_match`: esa tabla modela "el nombre no matcheó" (subconjunto de casos) y
sus filas *se mutan* (`resuelto_via_empalme`/`resuelto_via_revalidacion`); una corrección puede
ocurrir también sobre un hilo que matcheó perfecto la primera vez — semántica opuesta a la de un log
inmutable. Ver `docs/decisiones.md`, entrada 2026-09-23, para el razonamiento completo.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` (PK) | Integer | — |
| `comando` | `String(32)`, `NOT NULL` | `FORZAR_INGRESO` \| `FORZAR_EGRESO`; desde 2026-10-23 también `MOVER_INGRESO` \| `ANULAR_INGRESO` (portal, `origen='web'`). `String`, no enum de Postgres — sus valores previstos crecen sin exigir `ALTER TYPE`. |
| `origen` | `String(16)`, `NOT NULL`, default `'slack'` | Desde `20260928_01`: `slack` (comandos del canal) \| `web` (botón "Registrar egreso" de la vista Ingresos del Servicio). |
| `actor_web_usuario` | `String(64)`, nullable | Desde `20260928_01`: usuario del panel que ejecutó la acción; obligatorio si `origen='web'` (CHECK). |
| `actor_slack_user_id` | `String(32)`, nullable desde `20260928_01` | Quién ejecutó el comando de Slack — siempre se conoce, no hay allowlist que lo condicione (ver `docs/decisiones.md`). Obligatorio si `origen='slack'` (CHECK). |
| `actor_nombre` | `String(255)`, nullable | Nombre resuelto del actor; puede no resolverse, mismo criterio que `Ingreso.tecnico_id`. |
| `canal_id` | `String(32)`, nullable desde `20260928_01` | Obligatorio si `origen='slack'` (CHECK). |
| `thread_ts` | `String(32)`, nullable, index | `NULL` sólo si el comando no fue una respuesta en un hilo (en la práctica esto no ocurre: los comandos sólo se procesan dentro de un hilo, ver `docs/decisiones.md`). |
| `mensaje_ts` | `String(32)`, nullable desde `20260928_01` | `ts` del mensaje del comando en sí. Obligatorio si `origen='slack'` (CHECK). |
| `comando_crudo` | `Text`, `NOT NULL` | Texto íntegro del comando — lo re-lee el flujo de "fecha pendiente" para re-ejecutar sin que el operador retipee todo. |
| `motivo` | `Text`, nullable | Sin palabra clave obligatoria (decisión de producto) — sólo se captura cuando hay un delimitador natural (después de la fecha, después del `#<id>`). |
| `camara_texto_solicitado` | `String(512)`, `NOT NULL` | Nunca cadena vacía: `"(del hilo)"` en la forma bare, `"#<id>"` (con el id real) en la forma por id, `"(no parseado)"` si el comando murió en el parser antes de tener nombre de cámara. |
| `camara_id_resuelta` | Integer, nullable, index — sin FK desde `20261023_01` (antes FK → `app.camaras.id`, `ON DELETE SET NULL`) | Id histórico: se conserva aunque la cámara se borre o se unifique. |
| `cromo_botella_id_resuelta` | BigInteger, nullable, index — sin FK desde `20261023_01` (antes FK → `app.cromo_botellas.n_id`) | Id histórico. |
| `momento_solicitado` / `momento_efectivo` | DateTime(tz), nullable | `NULL` en el estado `PENDIENTE_FECHA` — todavía no hay una fecha resuelta. |
| `fuente_momento` | `String(16)`, nullable | `hilo` \| `explicito`. |
| `ingreso_id` | Integer, nullable, index — sin FK desde `20261023_01` (antes FK → `app.ingresos.id`) | Sólo se completa si la corrección terminó creando/cerrando un `Ingreso` real. Id histórico. |
| `camara_id_anterior` | Integer, nullable, sin FK | Desde `20261023_01`: cámara de origen de un `MOVER_INGRESO` (portal). El destino va en `camara_id_resuelta`. Id histórico. |
| `cromo_botella_id_anterior` | BigInteger, nullable, sin FK | Desde `20261023_01`: botella de origen de un `MOVER_INGRESO`. Id histórico. |
| `resultado` | `String(64)`, `NOT NULL` | Uno de 21 valores (`OK_INGRESO`, `OK_EGRESO_CERRADO`, `OK_EGRESO_ASENTADO`, `CAMARA_AMBIGUA`, `CAMARA_NO_ENCONTRADA`, `VARIOS_INGRESOS_ABIERTOS`, `SIN_INGRESO_ABIERTO`, `EGRESO_ANTERIOR_AL_INGRESO`, `INGRESO_YA_CERRADO`, `INGRESO_ANULADO` (desde 2026-10-23), `INGRESO_NO_ENCONTRADO`, `HILO_SIN_FORMULARIO`, `MOMENTO_INVALIDO`, `ERROR_INTERNO`, `PENDIENTE_FECHA`; desde 2026-10-23, para `MOVER_INGRESO`/`ANULAR_INGRESO`: `OK_INGRESO_MOVIDO`, `OK_INGRESO_ANULADO`, `BOTELLA_INVALIDA`, `DESTINO_NO_RAIZ`, `MISMO_DESTINO`, `MOTIVO_INVALIDO`) — constantes `RESULTADO_*` de `core/services/ingreso_correccion_service.py`. `PENDIENTE_FECHA` es un **estado pendiente, no un rechazo**: habilita que el operador conteste en el mismo hilo sólo con `DD-MM-AAAA HH:MM` y el comando se re-ejecute (escribiendo una fila NUEVA — la tabla es append-only). |
| `error_detalle` | `Text`, nullable | Detalle del rechazo/error, si lo hubo. |
| `created_at` | DateTime(tz), `NOT NULL`, index | — |

**CHECK `ck_ingresos_correcciones_origen_actor`** (desde `20260928_01`): `origen='slack'` exige
`actor_slack_user_id`, `canal_id` y `mensaje_ts`; `origen='web'` exige `actor_web_usuario`. Relajar
el `NOT NULL` de las columnas de Slack sin este CHECK habría permitido una fila de Slack sin actor.
Verificado real contra `lasfocasdev-postgres` (2026-09-28): una fila web sin actor y una de Slack
sin canal/mensaje son rechazadas; una web con actor entra. Una fila web usa `comando='FORZAR_EGRESO'`
(es la misma operación que `Forzar egreso #<id>`), `camara_texto_solicitado='#<id>'` y
`thread_ts=NULL` — por eso nunca la ve el flujo de "fecha pendiente" del listener, que filtra por hilo.

**Sin FKs desde `20261023_01`** (antes `camara_id_resuelta`, `cromo_botella_id_resuelta` e
`ingreso_id` eran FK `ON DELETE SET NULL`): en una tabla de auditoría inmutable los ids son dato
histórico, no referencias vivas. El trigger de inmutabilidad también rechaza el `UPDATE ... SET NULL`
que ejecuta una FK, así que borrar o unificar una cámara (`camara_merge_service.unificar_camaras`
borra la secundaria), una botella o un ingreso referenciado por la auditoría **fallaba** — verificado
real contra dev el 2026-10-23. Con "mover" toda cámara de origen quedaría referenciada en
`camara_id_anterior`. Ahora la fila conserva el id original aunque la entidad ya no exista (puede
quedar un id que no resuelve: es historia, no un vínculo). Columnas e índices se conservan; el modelo
ya no tiene `relationship` hacia esas tablas. Test: `tests/test_ingresos_anulados_real_db.py`
(borrar y unificar una cámara referenciada).

**Trigger de inmutabilidad**: función `app.ingresos_correcciones_bloquear_mutacion()` + trigger
`trg_ingresos_correcciones_inmutable` (`BEFORE UPDATE OR DELETE ON app.ingresos_correcciones FOR
EACH ROW`), `RAISE EXCEPTION` ante cualquier intento de modificar o borrar una fila ya escrita — es
la diferencia entre "inmutable" como promesa de código de aplicación (violable por cualquier acceso
directo a la DB o script one-off) y garantizado por la DB. Verificado real contra
`lasfocasdev-postgres`: un `UPDATE`/`DELETE` de prueba sobre una fila insertada a mano dieron `exit
code 1` con el mensaje de error de la función. El `downgrade()` de la migración `20260923_01`
dropea trigger y función explícitamente, no sólo la tabla.

Escritor único: `core/services/ingreso_correccion_service.py::procesar_comando_correccion`, cableado
en `modules/slack_baneo_notifier/listener.py` (nunca `UPDATE`/`DELETE` directo desde ningún otro
punto). Detalle completo de diseño en
`docs/superpowers/specs/2026-09-23-correccion-ingresos-y-servicios-por-cable-design.md`.

### Tabla `ingresos_sin_match` (2026-08-11)

Reemplaza el auto-registro `PENDIENTE_REVISION` en ingresos sin match (ver `docs/infra.md`, sección
homónima) — no crea ninguna `Camara`, es sólo información de sólo lectura para revisión manual y
mejora del regex de búsqueda. Poblada por `modules/slack_baneo_notifier/listener.py` (bot de Slack),
`web/app/routers/servicios.py::upload_tracking_web` (carga de tracking) y, desde 2026-08-24,
`core/services/camara_ingest_service.py` (ingesta Excel de cámaras baneadas, `origen="excel_camaras"`)
— el único de los 3 orígenes con una acción de resolución real además del triage (asociación manual,
ver tabla `camara_alias` más abajo).

| Columna | Tipo | Descripción |
|---|---|---|
| `id` (PK) | Integer | — |
| `texto_original` | String(512) | Nombre buscado que no matcheó, ya limpio de ruido operativo. |
| `origen` | String(32) | `"slack"` \| `"tracking"` \| `"excel_camaras"`. |
| `contexto` | Text, nullable | Canal de Slack o nombre de archivo de tracking, según `origen`. |
| `revisado` | Boolean | `false` por defecto — flag de triage admin. |
| `thread_ts` | String(32), nullable | ts del hilo de Slack donde se registró el caso (sólo `origen="slack"`) — habilita el seguimiento por ID de empalme. |
| `resuelto_via_empalme` | Boolean | `false` por defecto — se marca `true` cuando el técnico responde en el mismo hilo con un ID de empalme y `core/services/cromo/empalme_resolucion.py` resuelve la Botella dueña, tanto si la resolución tuvo éxito como si no (evita reprocesar el mismo hilo dos veces). |
| `created_at` | DateTime(tz), index | — |

---

## Protocolo de Protección (Baneo de Cámaras)

El sistema permite bloquear el acceso físico a cámaras que contienen fibra óptica de respaldo
cuando la fibra principal está cortada. Esto se implementa mediante la tabla `incidentes_baneo`.

### Tabla `incidentes_baneo`

| Columna               | Tipo              | Descripción |
|-----------------------|-------------------|-------------|
| `id`                  | Integer (PK)      | ID autoincremental. |
| `ticket_asociado`     | String(64), index | ID del ticket de soporte (ej: "INC0012345"). |
| `servicio_afectado_id`| String(64), index | ID del servicio que sufrió el corte. |
| `servicio_protegido_id`| String(64), index| ID del servicio cuyas cámaras se banean. |
| `ruta_protegida_id`   | FK → rutas_servicio | Ruta específica a proteger (opcional). |
| `usuario_ejecutor`    | String(128)       | Usuario que ejecutó el baneo. |
| `motivo`              | String(512)       | Descripción del motivo. |
| `fecha_inicio`        | DateTime(tz)      | Timestamp de inicio del baneo. |
| `fecha_fin`           | DateTime(tz)      | Timestamp de cierre (cuando se levanta). |
| `activo`              | Boolean, index    | Si el baneo está vigente. |

**Índice compuesto:** `ix_incidentes_baneo_servicio_activo` sobre `(servicio_protegido_id, activo)`.

**Características:**
- **Redundancia cruzada:** El servicio afectado puede ser diferente al protegido.
- **Baneo a nivel de entidad:** El estado de `Camara` cambia a `BANEADA`.
- **Cascada de grupo (2026-08-10):** banear o desbanear cualquier `Camara` cascadea a TODO su grupo Cámara→Botellas (padre + botellas hermanas, ver `docs/infra.md`) vía `aplicar_estado_a_grupo`.
- **Restauración inteligente:** al levantar un baneo, cada cámara del grupo se evalúa por separado — vuelve a `LIBRE` u `OCUPADA` según ingresos activos, y se mantiene en `BANEADA` si la última transición a ese estado es anterior al inicio del incidente que se levanta (baneo independiente sin `IncidenteBaneo` que lo respalde — override manual o heredado del backfill de jerarquía). Ver `core/services/protection_service.py::_determinar_estado_restauracion` y `camara_estado_service.obtener_ultima_transicion_a_baneada`. Hasta 2026-08-11 también preservaba `DETECTADA` si ese era el estado previo a ser baneada — retirado junto con el resto del estado `DETECTADA` (ver tabla `camaras`, sección "Estados").
- **Cámaras nuevas:** Si se carga un tracking de un servicio baneado, las cámaras nuevas nacen `BANEADAS`.

### Tabla `camaras_estado_auditoria`

Registra overrides manuales del campo `Camara.estado` cuando un administrador necesita
normalizar discrepancias entre el estado efectivo persistido y el estado operativo sugerido
por incidentes activos o ingresos abiertos.

| Columna               | Tipo                    | Descripción |
|-----------------------|-------------------------|-------------|
| `id`                  | Integer (PK)            | ID autoincremental. |
| `camara_id`           | FK → camaras, index     | Cámara modificada manualmente. |
| `usuario`             | String(128)             | Usuario administrador que realizó el cambio. |
| `motivo`              | Text                    | Motivo auditado del override. |
| `estado_anterior`     | Enum `camara_estado`    | Estado persistido antes del cambio. |
| `estado_nuevo`        | Enum `camara_estado`    | Estado persistido después del cambio. |
| `estado_sugerido`     | Enum `camara_estado`    | Estado que el sistema sugería al momento del override. |
| `incidentes_activos`  | JSON                    | IDs de incidentes activos relacionados en el momento del cambio. |
| `created_at`          | DateTime(tz), index     | Timestamp del override manual. |

**Migración:** `20260420_01_camaras_estado_auditoria.py`.

**Uso operativo:**
- El panel web permite editar manualmente `estado` solo a usuarios `admin`.
- La auditoría preserva trazabilidad aunque el operador fuerce un estado distinto al sugerido.
- Los conteos visuales del panel se alinean con el estado efectivo de `app.camaras.estado`, no solo con la topología de incidentes activos.

### Relaciones

- `Camara.empalmes`: lista de empalmes ubicados en la cámara.
- `Camara.ingresos`: historial de ingresos de técnicos.
- `Camara.cables_origen` / `Camara.cables_destino`: cables conectados.
- `Camara.camara_padre` / `Camara.botellas`: jerarquía self-referencial de 2 niveles (ver `docs/infra.md`, sección "Jerarquía Cámara → Botellas").
- `Servicio.empalmes`: empalmes por los que pasa el servicio (N-a-N).
- `Empalme.servicios`: servicios que pasan por el empalme (N-a-N).
- `Empalme.camara`: cámara donde se ubica el empalme.

### Servicios de sincronización

- **Google Sheets** (`/sync/camaras`): `core/services/infra_sync.py` sincroniza desde la hoja "Camaras" configurada vía `INFRA_SHEET_ID`/`INFRA_SHEET_NAME`, actualizando `fontine_id`, coordenadas y estado.
- **Tracking** (`/api/infra/upload_tracking`): procesa archivos TXT de tracking, crea servicios y registra empalmes. Desde 2026-08-23 **nunca crea una `Camara` nueva** — resuelve la ubicación con la búsqueda extendida Camara+CromoBotella (`core/services/cromo/camara_botella_busqueda.py`) y, si no matchea, registra un `IngresoSinMatch` (`origen="tracking"`) dejando `Empalme.camara_id=NULL`; ver `docs/infra.md`, sección "Ingresos sin match".

## Configuración de Servicios Automatizados

### Tabla `config_servicios`

Almacena configuración dinámica de workers y servicios automatizados. Definida en `db/models/servicios.py`.

## Histórico de Reportes Web

La tabla `app.report_history` registra la ejecución de informes generados desde el panel web. En la primera versión cubre sólo SLA y Repetitividad.

| Columna | Descripción |
|---------|-------------|
| `id` | ID autoincremental del registro. |
| `report_type` | Tipo de informe: `sla` o `repetitividad`. |
| `status` | Estado operativo: `running`, `success` o `error`. |
| `username` | Usuario autenticado que inició la generación. |
| `source` | Origen de datos: `excel`, `excel-legacy` o `db`. |
| `period_month`, `period_year` | Período informado por el usuario. |
| `started_at`, `finished_at`, `duration_ms` | Tiempos de ejecución. |
| `input_metadata` | Metadata segura de entrada, como nombres de archivos, flags y cantidad de adjuntos. |
| `output_metadata` | Enlaces públicos `/reports/*`, estadísticas y conteos devueltos por el generador. |
| `error_code`, `error_message` | Error amigable cuando la ejecución falla. |

No se almacenan bytes de archivos, contenido de planillas, secretos ni payloads crudos extensos. La migración asociada es `20260625_01_report_history.py`.

| Columna           | Tipo              | Descripción |
|-------------------|-------------------|-------------|
| `id`              | Integer (PK)      | ID autoincremental. |
| `nombre_servicio` | String(128), unique, index | Identificador único del servicio (ej: `slack_baneo_notifier`). |
| `intervalo_horas` | Integer           | Intervalo de ejecución en horas (default: 4). |
| `slack_channels`  | String(512)       | Canales Slack separados por coma. |
| `ultima_ejecucion`| DateTime(tz)      | Timestamp de la última ejecución exitosa. |
| `activo`          | Boolean           | Si el servicio está habilitado (default: true). |
| `ultimo_error`    | Text              | Último error registrado (NULL si la última ejecución fue exitosa). |
| `hora_inicio`     | SmallInteger      | Hora del día (0-23, GMT-3) que ancla el primer ciclo; NULL = arrancar de inmediato. |
| `workflow_ids`    | String(512)       | IDs de Workflow de Slack permitidos, separados por coma. NULL = sin filtro. Usado por `slack_ingreso_listener`. |
| `solo_workflows`  | Boolean           | Si TRUE, el listener solo procesa mensajes con `workflow_id` incluido en `workflow_ids` (default: false). |

**Migración:** `20260417_01_config_servicios.py` — crea la tabla e inserta fila por defecto para `slack_baneo_notifier`.

**Uso:** El worker `slack_baneo_notifier` lee esta tabla en cada ejecución para obtener la configuración actualizada (intervalo, canales, estado activo). El panel admin en `/admin/Servicios/Baneos` permite modificar estos valores sin reiniciar el worker.

## Informe SLA consumido (`sla_ingestas`, `servicio_sla_snapshot`)

Persistencia del informe SLA consumido: cada par de archivos (Excel de Servicios + Excel de
Reclamos) que se procesa queda registrado, los reclamos se upsertean en `app.reclamos` y se guarda
una foto del SLA de cada línea por fecha de corte. Migración `20261005_02_sla_consumo_historico.py`;
modelos `SlaIngesta` y `ServicioSlaSnapshot` (`db/models/sla_consumo.py`); escritura en
`core/sla_consumo/persistencia.py::ingerir`. Flujo funcional en `docs/informes/sla_consumo.md`.

### Tabla `sla_ingestas`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | BigInteger PK | |
| `fecha_corte` | Date, `NOT NULL`, indexado (`ix_sla_ingestas_fecha_corte`) | Calculada desde los reclamos (`calcular_fecha_corte`). |
| `hash_servicios`, `hash_reclamos` | String(64), `NOT NULL` | SHA-256 de cada archivo. `UNIQUE (hash_servicios, hash_reclamos)` (`uq_sla_ingestas_hashes`). |
| `usuario` | String(128), nullable | Quién subió los archivos. |
| `reclamos_insertados`, `reclamos_actualizados`, `servicios_snapshot` | Integer, `NOT NULL`, default 0 | Conteos de la ingesta. |
| `report_history_id` | BigInteger, nullable | Referencia blanda (sin FK) a `app.report_history`. |
| `created_at` | timestamptz, default `now()` | |

**Idempotencia:** si el mismo par de hashes ya existe, `ingerir` devuelve la ingesta previa sin
escribir nada. `app.reclamos.ingesta_id` sí tiene FK a `sla_ingestas.id` (`ON DELETE SET NULL`).

### Tabla `servicio_sla_snapshot`

Una fila por `(numero_linea, fecha_corte)` (`UNIQUE`, `uq_sla_snapshot_linea_corte`); una nueva
ingesta con la misma fecha de corte la actualiza (`ON CONFLICT DO UPDATE`).

| Columna | Tipo | Notas |
|---|---|---|
| `id` | BigInteger PK | |
| `numero_linea` | String(64), `NOT NULL`, indexado | |
| `numero_primer_servicio` | String(64), nullable, indexado | |
| `fecha_corte` | Date, `NOT NULL`, indexado | |
| `nombre_cliente`, `tipo_servicio` | String(128) / String(80), nullable | |
| `sla_prometido` / `sla_entregado` | Numeric(6,3) / Numeric(9,6), nullable | |
| `horas_reclamos_mes`, `horas_carriers_mes`, `horas_reclamos_todos`, `horas_carriers_todos`, `horas_restantes` | Numeric(12,4), nullable | Horas decimales. |
| `abono_usd` | Numeric(14,2), nullable | |
| `cantidad_reclamos_todos` | Integer, nullable | |
| `ingesta_id` | BigInteger, nullable | Sin FK: última ingesta que escribió la fila. |
| `updated_at` | timestamptz, default `now()` | |

**Lectura:** `api/app/routes/servicios.py` arma `sla_historico` de `GET /servicios/detail` con las
fotos de las líneas del servicio, ordenadas por fecha de corte.

La misma migración amplía `app.reclamos` (horas a `Numeric(12,4)`, columnas de carrier, código y
grupo de cierre, `ingesta_id`, `first_seen_at`/`last_seen_at`) y crea la vista `app.v_eventos_sla`
(reclamos agrupados por `numero_evento`).

## Chat del panel web (`chat_sessions`, `chat_messages`)

Historial del chatbot. Sin modelo ORM: las crean `20251007_01` y `20251008_01` con SQL crudo
(`CREATE ... IF NOT EXISTS`) y las lee y escribe `core/chatbot/storage.py` con SQL directo. Detalle
de uso en `docs/chatbot.md`.

- **`chat_sessions`**: `id` SERIAL PK, `user_id` VARCHAR(255) `NOT NULL`, `is_active` (default
  `true`), `created_at` y `last_activity` (`timestamp` sin zona, default `NOW()`). Índices:
  `ix_chat_sessions_user_id_last_activity (user_id, last_activity)`,
  `ix_chat_sessions_last_activity (last_activity DESC)` y el único parcial
  `uq_chat_sessions_user_active (user_id) WHERE is_active IS TRUE` (una sesión activa por usuario).
- **`chat_messages`**: `id` SERIAL PK, `session_id` FK → `chat_sessions.id` `ON DELETE CASCADE`,
  `role` VARCHAR(32), `content` TEXT, `tool_name` VARCHAR(128), `tool_args` y `attachments` JSONB,
  `error_code` VARCHAR(64), `created_at`. Índices `ix_chat_messages_session_created (session_id,
  created_at)` e `ix_chat_messages_role_created (role, created_at DESC)`.

## Inventario de Fibra Óptica (Cromo)

Namespace `cromo_*` en el esquema `app`, aislado del modelo de infraestructura poblado desde los
trackings `.txt` (`app.camaras`, `app.cables`, `app.empalmes`). Ingesta de sólo lectura desde el sistema
externo Cromo Red de Metrotel — LAS-FOCAS nunca escribe en Cromo. Contexto funcional en
`docs/modulo_ingesta_cromo.md`; modelo de datos y autenticación completos (documento interno, no
versionado): `docs/Doc Privada/ingesta_cromo.md`. Definidos en `db/models/cromo.py`.

**Sin FK duras entre familias**: un cable puede apuntar a una botella que todavía no bajó, y un tubo a
un cable que puede no existir aún. Las referencias cruzadas (`*_n_id`, `extremo_a/b_*`) se guardan como
`BigInteger` indexado y se resuelven en la fase de reconciliación de la Etapa 3 (todavía no
implementada). Las únicas FK duras son las cuatro listadas al final de esta sección.

### Tabla `cromo_clases`

Catálogo de clases de objeto de Cromo. Vive en tabla, no en un `CHECK`: incorporar una clase nueva es
un `INSERT`, no una migración.

| Columna | Tipo | Descripción |
|---|---|---|
| `clase` (PK) | SmallInteger | Código de clase tal como lo usa Cromo. |
| `etiqueta` | Text | Etiqueta corta de Cromo (ej. `6-1`), si existe. |
| `entidad` | Text | `BOTELLA` \| `CABLE` \| `TUBO` \| `PELO` \| `FUSION` \| `ODF` \| `PARCELA` \| `CAJA_PON` \| `ROSETA` \| `SPLITTER` \| `PUERTO_SPLITTER` \| `CABLE_BAJADA` \| `NODO` \| `FUSION_ODF`. |
| `ingerible` | Boolean | Si la ingesta debe traer objetos de esta clase. |
| `homologada` | Boolean | `false` para clases estructuralmente válidas pero sin homologar (ej. clase 124, `code: "NO-SABE"`). |
| `motivo_exclusion` | Text | Motivo si `ingerible = false` (ej. clase 120, parcela catastral). |
| `count_cromo` | BigInteger | Último count observado en Cromo. **Ya no es sólo referencial**: desde 2026-09-19 es la fuente del fallback de `fase_conteo` para las clases cuyo `stats[].count` miente (133 y 134 devuelven 0 aunque la colección pagine perfecto; sus totales reales, 20.238 y 154.284, se midieron paginando hasta el final). |
| `count_fecha` | DateTime(tz) | Fecha del último count observado. |

Seed inicial (verificado contra Cromo real el 2026-08-05): clases `68/121/122/123/125` (botella,
ingerible/homologada), `124` (botella, ingerible pero no homologada), `120` (parcela, excluida), `69`
(ODF — punto terminal de fibra donde se conectan clientes), `51` (cable), `129/130/132` (tubo/pelo/fusión,
sin colección propia — llegan siempre dentro de `cable.inner[]`/`botella.inner[]`).

### Tabla `cromo_ingesta_corridas`

Auditoría de una corrida de ingesta completa (Etapa 3, todavía no implementada — la tabla ya existe).

| Columna | Tipo | Descripción |
|---|---|---|
| `id` (PK) | BigInteger | — |
| `usuario` | String(128) | Quién disparó la corrida. |
| `estado` | String(32) | `EN_CURSO` \| `OK` \| `OK_CON_ERRORES` \| `FALLIDA` \| `CANCELADA`. Texto libre, no enum: el vocabulario todavía lo termina de fijar la Etapa 3. |
| `params` | JSONB | Clases, `psize`, `max_paginas` de la corrida, más `modo` cuando difiere de `COMPLETA` (`SOLO_ODF`, `SOLO_SPLITTERS`, `SOLO_PUERTOS_SPLITTER`, `SOLO_CAJAS_PON`, `SOLO_ROSETAS`, `SOLO_CABLES_BAJADA`, `SOLO_CABLES_TERCEROS`) o `tipo` en las corridas sintéticas de mantenimiento (`MANUAL_REPOBLAR_CABLES`, `MANUAL_CATCHUP_SERVICIOS`, `MANUAL_NORMALIZAR_CONSISTENCIA`). La UI lo muestra como columna "Alcance" del histórico. |
| `total_objetivo`, `leidas`, `creadas`, `actualizadas`, `sin_cambios`, `errores`, `refs_colgadas` | Integer | Contadores en vivo. |
| `iniciada_at`, `finalizada_at` | DateTime(tz) | — |

### Tabla `cromo_ingesta_eventos`

Evento puntual por objeto dentro de una corrida. `corrida_id → cromo_ingesta_corridas.id` (`ON DELETE CASCADE`).

| Columna | Tipo | Descripción |
|---|---|---|
| `id` (PK) | BigInteger | — |
| `corrida_id` (FK) | BigInteger | — |
| `n_id`, `clase` | BigInteger, SmallInteger | Identifica el objeto de Cromo afectado. |
| `accion` | String(32) | `CREADA` \| `ACTUALIZADA` \| `OMITIDA` \| `ERROR` \| `REF_COLGADA`, más los de control (`INICIO`, `FASE`, `PAGINA`, `RESUMEN`), los de reanudación (`CABLE_INNER_OK`, `CABLE_SNAPSHOT_OK`) y los de bajas. `SIN_CAMBIOS` ya no se escribe desde 2026-10-27; quedan filas anteriores. |
| `detalle` | Text | Mensaje libre. |
| `created_at` | DateTime(tz) | — |

Índice: `(corrida_id, id)`.

**Sin `SIN_CAMBIOS` (2026-10-27)**: `ingesta.registrar_evento` descarta esa acción. Era el 79 % de una
corrida COMPLETA (≈ 89.000 eventos) y ningún lector la usaba: el total sigue en
`cromo_ingesta_corridas.sin_cambios` (y en el evento `RESUMEN`), y la marca "visto en esta corrida" es
`ultima_ingesta` del objeto. El stream SSE del panel nunca la emitía, y el detalle de una corrida
(`GET /api/admin/ingesta/cromo/corridas/{id}`, últimos 200 eventos) deja de llenarse con ella.

**Retención (2026-10-27)**: `core/services/cromo/retencion_eventos.py` borra los eventos con
`created_at` anterior a `ahora - 90 días` y, con `--incluir-sin-cambios`, todos los `SIN_CAMBIOS`
históricos. Nunca toca eventos de una corrida `EN_CURSO` (la reanudación lee `CABLE_INNER_OK` /
`CABLE_SNAPSHOT_OK`) ni las filas de `cromo_ingesta_corridas`. Borra por rangos de 20.000 `id` (range
scan sobre la PK, commit por lote): en dev, un lote con 19.446 borrados tarda ≈ 200 ms y el conteo
previo es un seq scan de ≈ 160 ms sobre 441.487 filas, así que no lleva índice propio. No hay cron
(el scheduler de ingesta está deshabilitado): se corre a mano con `scripts/cromo_retencion_eventos.py`
(dry-run por defecto, `--aplicar`, `--dias`).

### Tabla `cromo_botellas`

Botella/empalme/ODF. `n_id` es la PK de linaje de Cromo (estable entre versiones); `version_id` es el
`id` de la versión vigente. `clase → cromo_clases.clase` es la única FK dura hacia el catálogo.

| Columna | Tipo | Descripción |
|---|---|---|
| `n_id` (PK) | BigInteger | Linaje estable en Cromo. |
| `version_id` | BigInteger | `id` de la versión vigente. |
| `vmax` | Integer | Detector de cambios. |
| `clase` (FK) | SmallInteger | → `cromo_clases.clase`. |
| `nombre`, `codigo_modelo`, `id_legacy`, `notas`, `calle`, `altura`, `localidad`, `provincia`, `ubicacion_fisica`, `tendido` | Text | Atributos de Cromo, texto libre. |
| `latitud`, `longitud` | Float | WGS84. |
| `pts_raw` | JSONB | Coordenadas Gauss-Krüger originales, sin reproyectar. |
| `payload_raw` | JSONB | Payload crudo completo, para auditoría. |
| `vigente` | Boolean | Baja lógica, nunca `DELETE`. |
| `primera_ingesta`, `ultima_ingesta`, `ultima_modificacion` | DateTime(tz) | — |
| `camara_id` (FK) | Integer, nullable | → `camaras.id` (`ON DELETE SET NULL`). Desde 2026-08-11 (migración `20260811_01`); poblada por `scripts/cromo_backfill_camara_padre.py`, no por la ingesta — deliberadamente excluida de `_BOTELLA_CAMPOS`, sobrevive intacta a reingestas. |
| `estado` | Enum `camara_estado` | `NOT NULL DEFAULT 'LIBRE'` (desde migración `20260813_01`, antes `'NO_OPERATIVA'`). `CHECK` sólo admite `LIBRE`/`OCUPADA`/`BANEADA`/`NO_OPERATIVA` (reusa el mismo tipo Postgres de `camaras.estado`, sin `DETECTADA`/`PENDIENTE_REVISION`, exclusivos del legado). |
| `nombre_editado_manual` | Boolean | `NOT NULL DEFAULT false` (desde 2026-08-21, migración `20260821_01`). Puesta en `True` únicamente desde `PATCH /api/infra/botellas/{n_id}/nombre` (Verificador Cromo, admin). Cuando está en `True`, `core/services/cromo/ingesta.py::_procesar_botella_completa` deja de pisar `nombre` en corridas futuras — protección condicional, distinta de la exclusión estructural de `camara_id`/`estado` (`nombre` sigue viniendo de Cromo para el resto de las botellas). |
| `separada_manualmente`, `separada_motivo`, `separada_por`, `separada_at` | Boolean, Text, String(128), DateTime(tz) | Desde 2026-08-22 (migración `20260822_01`). Puestas por `POST /api/infra/botellas/{n_id}/separar-padre` (admin) al separar una Botella agrupada erróneamente por nombre — ver `core/services/cromo/separacion_service.py`. `scripts/cromo_backfill_camara_padre.py` las excluye de su filtro de idempotencia como blindaje adicional (redundante con `camara_id IS NULL` hoy, pensado para un futuro `--force`). |

Índices: parcial en `id_legacy` (`WHERE id_legacy IS NOT NULL`), compuesto `(latitud, longitud)`,
`camara_id`, y GIN funcional `to_tsvector('spanish', nombre)` para búsqueda de texto.

### Tabla `cromo_cables`

Cable de FO. Extremos (`extremo_a/b_*`) sin FK dura — apuntan a la botella/ODF de cada punta, que puede
no haber bajado todavía.

**Columna `clase` (2026-09-19).** La tabla nunca la tuvo: era implícitamente la 51. Desde el modo
`SOLO_CABLES_BAJADA` aloja además los 19.030 cables de la clase **66** (bajada / drop de la red PON),
que comparten esquema y parser —medido: publican exactamente los mismos `at`, y tienen `vmax`, `tp`
con dos extremos e `inner` con 1 tubo y 1 pelo— pero no son lo mismo. Las 32.790 filas existentes se
backfillearon a 51.

**Cables de terceros (2026-09-29).** Desde el modo `SOLO_CABLES_TERCEROS` (y dentro de `COMPLETA`)
la tabla aloja también las clases **52** (terceros varios), **59** (Telefónica) y **60** (Telecom),
~733 cables, con sus tubos y pelos en `cromo_tubos`/`cromo_pelos`. Catálogo en `cromo_clases` con
`entidad='CABLE'` (migración `20260929_03`). La reconciliación ya filtraba `clase = 51`, así que sus
extremos (cámaras, ODFs) no aparecen como referencias colgadas.

No es cosmética: **`fase_reconciliacion` marca como referencia colgada todo cable cuyo extremo no sea
una botella**, y los extremos de un cable de bajada son una caja PON y una roseta. Sin el filtro
`AND c.clase = 51` en esas dos consultas, cada corrida completa reportaría ~38.000 referencias
colgadas inventadas. El filtro va en la consulta y no en la fase porque esa consulta lee la tabla
entera, no lo que barrió la corrida. Lo mismo en `inventario.buscar_cables`, para que el listado de
Cables no pase de 32.790 a 51.820 filas.

| Columna | Tipo | Descripción |
|---|---|---|
| `n_id` (PK) | BigInteger | — |
| `version_id`, `vmax` | BigInteger, Integer | — |
| `nombre`, `propietario`, `jerarquia`, `tendido`, `id_legacy`, `notas` | Text | — |
| `capacidad` | Text | Crudo (ej. `"72-BRUG"`). |
| `capacidad_pelos` | SmallInteger | Derivado: prefijo numérico de `capacidad`. |
| `distancia_geo`, `distancia_real` | Numeric(12,2) | — |
| `extremo_a_n_id`, `extremo_b_n_id` | BigInteger | Sin FK dura. |
| `extremo_a_clase`, `extremo_b_clase` | SmallInteger | Sin FK dura (puede ser una clase todavía no catalogada). |
| `extremo_a_legacy`, `extremo_a_nombre`, `extremo_b_legacy`, `extremo_b_nombre` | Text | Crudos de `at.28`/`at.34`/`at.29`/`at.37` — **no confiables para el nombre del extremo B**, ver nota abajo. |
| `pts_raw`, `payload_raw` | JSONB | — |
| `vigente`, `primera_ingesta`, `ultima_ingesta` | Boolean, DateTime(tz) | — |

Índices: `nombre`, compuesto `(extremo_a_n_id, extremo_b_n_id)`.

**`extremo_a_nombre`/`extremo_b_nombre` crudos no son confiables** (hallazgo real, Etapa 9c): Cromo
nunca manda `at.37` (0/32.782 cables) — ambos nombres de extremo viajan concatenados en el único
atributo `at.34` (`"LEG_A: dirección_A  LEG_B: dirección_B"`). Todo código de lectura nuevo debe
resolver el nombre real vía `LEFT JOIN app.cromo_botellas` por `extremo_a_n_id`/`extremo_b_n_id` (con
`COALESCE` a la columna cruda sólo si la botella todavía no bajó) — mismo patrón ya aplicado en
`inventario.py`, `verificador.py` y `detalle.py`. No usar `extremo_b_nombre` crudo directamente.

**Lectura:** `core/services/cromo/inventario.py` (Etapa 8b, filtros extendidos en Etapa 9) — búsqueda
paginada (`ILIKE` parcial sobre `nombre`/`jerarquia`/`propietario`/`botella` —ésta contra
`extremo_a_nombre`/`extremo_b_nombre`, ya en la propia fila—, exacto sobre `vigente`/`n_id`, y un
filtro `servicio` vía `n_id IN (subquery no correlacionada)` sobre `cromo_pelos`+
`cromo_servicio_match`+`app.servicios` — no correlacionada a propósito, para que Postgres resuelva el
join una sola vez por request en vez de una vez por fila candidata) con conteo de servicios matcheados
por cable vía `cromo_pelos`/`cromo_servicio_match`. Nota real: los parámetros de filtro necesitan
`CAST(:param AS tipo)` explícito en el SQL — sin eso, `asyncpg` no puede preparar el statement cuando
todos los filtros llegan en `NULL` a la vez (sin ningún filtro puesto) y tira `AmbiguousParameterError`.
Detalle jerárquico completo de un cable puntual (extremos, tubos y pelos con servicio matcheado) en
`core/services/cromo/detalle.py` (Etapa 9) — 3 queries fijas, sin N+1.

### Tablas `cromo_tubos` y `cromo_pelos`

El pelo pertenece al tubo, nunca directamente a la botella. Ambas columnas de parentesco van sin FK
dura (`cable_n_id`, `tubo_n_id`).

| Tabla | Columnas propias | Descripción |
|---|---|---|
| `cromo_tubos` | `n_id` (PK), `cable_n_id`, `orden`, `nombre_color`, `vigente`, `ultima_ingesta` | Índice en `cable_n_id`. |
| `cromo_pelos` | `n_id` (PK), `tubo_n_id`, `cable_n_id` (desnormalizado a propósito), `numero_pelo`, `orden`, `color`, `servicio_raw`, `servicio_numero`, `tipo_asociacion`, `vigente`, `ultima_ingesta` | Índices en `cable_n_id`, `tubo_n_id`, parcial en `servicio_numero`. |

`tipo_asociacion` usa el enum de Postgres `app.cromo_tipo_asociacion_pelo` (`CLIENTE` \| `TRUNK_DWDM` \|
`OLT_LASER` \| `INFRA` \| `LIBRE` \| `INDETERMINADO`, default `LIBRE`), mismo patrón que `camara_estado`.
`servicio_raw` guarda `at.61` crudo (texto libre); `servicio_numero` es el número parseado por regex —
nunca se descarta un pelo si no matchea. El regex (`parser.py::parsear_servicio()`) reconoce los
prefijos `FO`/`TLS`/`DWDM`/`INT`/`EWS`/`RPV`/`TDM`/`ATD`/`VID`/`TRUNK` (ampliado en Etapa 9c —
`app.servicios.tipo_servicio` ya trackea esos mismos tipos con el mismo esquema de numeración que FO).
Backfill de las filas ya ingeridas antes de esa ampliación: `scripts/cromo_backfill_servicio_prefijos.py`
(91.654 pelos re-clasificados a `CLIENTE`, 7.042 con match real).

### Tabla `cromo_fusiones`

Fusión entre dos pelos. Puede llegar embebida en `botella.inner[]` (`parent` = `botella_n_id`) o por
barrido directo de clase 132 (Etapa 8, mismo patrón que cables) — este segundo camino no trae
`parent`, por eso `botella_n_id` es `nullable` (migración `20260807_01`; `NULL` no es una referencia
colgada, es la forma esperada de una fusión ingerida directo).

| Columna | Tipo | Descripción |
|---|---|---|
| `n_id` (PK) | BigInteger | — |
| `botella_n_id` (nullable) | BigInteger | Sin FK dura. Índice simple. `NULL` = ingerida por barrido directo, sin contenedor conocido. |
| `nombre_par`, `tipo` | Text | `tipo` no siempre es `"FUSION"` — se persiste el valor crudo. |
| `pelo_a_n_id`, `pelo_b_n_id` | BigInteger | Índice compuesto. |
| `latitud`, `longitud` | Float | — |
| `vigente`, `ultima_ingesta` | Boolean, DateTime(tz) | — |

### Tabla `cromo_servicio_match`

Puente entre un pelo con servicio parseado y el maestro `app.servicios`. Únicas FK duras de esta tabla:
`pelo_n_id → cromo_pelos.n_id` (`ON DELETE CASCADE`) y `servicio_id → app.servicios.id` (sin cascade).

| Columna | Tipo | Descripción |
|---|---|---|
| `id` (PK) | BigInteger | — |
| `pelo_n_id` (FK) | BigInteger | → `cromo_pelos.n_id`, `ON DELETE CASCADE`. |
| `servicio_numero` | Text | — |
| `servicio_id` (FK, nullable) | Integer | → `app.servicios.id`. `NULL` si no matcheó. |
| `metodo` | String(32) | `REGEX_EXACTO` \| `REGEX_PARCIAL` \| `MANUAL`. |
| `confianza` | SmallInteger | — |
| `created_at` | DateTime(tz) | — |

Índice único compuesto `(pelo_n_id, servicio_numero)`.

**Migración:** `20260805_01_cromo_ingesta.py` — crea las 9 tablas, el enum `cromo_tipo_asociacion_pelo`
y siembra `cromo_clases`.

**Escritura:** `core/services/cromo/ingesta.py` (Etapa 3). Nota de esquema: `CromoPelo.tipo_asociacion`
declara `SQLEnum(..., schema="app", ...)` explícito en el modelo — sin eso, `asyncpg` no resuelve el
tipo porque el `search_path` de la conexión no incluye `app` (confirmado real al validar la Etapa 3).

**Lectura:** `core/services/cromo/verificador.py` (Etapa 6) — consultas de sólo lectura (`text()` SQL
crudo) para responder qué servicios pasan por un cable/tubo/botella. Tolerante a referencias colgadas:
un objeto sin fila propia pero referenciado por otro (pelo, cable) no se trata como inexistente.

### Tabla `cromo_ingesta_config`

Configuración persistente del scheduler del worker dedicado de ingesta (Etapa 7). Fila única (`id=1`),
sembrada por la migración — el worker nunca arranca sin config.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` (PK) | Integer | Siempre `1`. |
| `habilitado` | Boolean | Si `false` (default), el job periódico no corre — sólo el trigger manual. |
| `intervalo_horas` | Integer | Cada cuántas horas se dispara la corrida automática. Default `24`. |
| `hora_inicio` | SmallInteger, nullable | 0-23 (GMT-3), ancla el ciclo. `NULL` = arranca de inmediato. |
| `psize` | Integer | Debe estar en `PSIZE_PERMITIDOS` (`{1,5,10,20,50}`). Default `5`. |
| `max_paginas` | Integer, nullable | `NULL` = corrida real completa, sin límite. |
| `clases` | JSONB | Lista de clases de botella a incluir, ej. `[68,121,122,123,125]`. |
| `ultima_ejecucion` | DateTime(tz), nullable | Actualizado por el worker al terminar cada corrida (manual o programada). |
| `ultimo_error` | Text, nullable | Mensaje de la última corrida fallida, si la hubo. |

**Migración:** `20260806_01_cromo_ingesta_config.py`.

**Lectura y escritura:** `modules/cromo_worker/worker.py` (el worker relee esta fila en cada
`/reload` y actualiza `ultima_ejecucion`/`ultimo_error` al final de cada corrida) y
`web/app/routers/admin_datos.py` (`GET`/`POST /api/admin/ingesta/cromo/config`, panel admin).

### Tabla `cromo_botella_alias` (2026-08-19)

Escudo manual contra la mala calidad de datos de Cromo (botellas duplicadas/triplicadas): cada fila
decide, para un `id_cromo_origen` (n_id de Cromo, basura conocida), si debe ignorarse por completo o
tratarse como el mismo objeto que otro `id_cromo_destino` ("golden record") ya bueno.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` (PK) | Integer | Autoincrement. |
| `id_cromo_origen` | BigInteger, `NOT NULL UNIQUE` | El n_id basura/duplicado. **Sin FK dura** — mismo criterio que el resto del dominio Cromo (`CromoCable.extremo_a_n_id`, `CromoFusion.botella_n_id`, etc.): puede cargarse antes de que Cromo entregue esa fila, que es justamente lo que se busca evitar. |
| `id_cromo_destino` | BigInteger, nullable | El n_id "golden". Obligatorio sólo si `accion='fusionar'`, `NULL` si `accion='ignorar'` (CHECK `ck_cromo_botella_alias_destino_coherente`). |
| `accion` | String(20) | `'fusionar'` \| `'ignorar'`, restringido por CHECK `ck_cromo_botella_alias_accion_valida` (no es un enum de Postgres — mismo criterio que `CromoIngestaEvento.accion`). |
| `motivo` | Text, nullable | Por qué se marcó — única traza de auditoría mientras no exista un CRUD/UI para esta tabla. |
| `creado_por` | String(128), nullable | Quién cargó la fila. |
| `created_at` / `updated_at` | DateTime(tz) | `updated_at` sigue el mismo patrón `onupdate` que `RutaServicio.updated_at`. |

**Migración:** `20260819_01_cromo_botella_alias.py`.

**Uso:** `core/services/cromo/alias_service.py::cargar_alias_vigentes` carga TODAS las filas en
memoria una sola vez por corrida (nunca una query por objeto) y `resolver_referencia` la usa para
reescribir cualquier referencia blanda (`CromoCable.extremo_a_n_id`/`extremo_b_n_id`,
`CromoFusion.botella_n_id`) que apunte al origen: `'fusionar'` la redirige al destino, `'ignorar'` la
anula a `NULL`. `core/services/cromo/ingesta.py` la consulta en `_procesar_cable_directo`,
`_procesar_botella_completa` y `_procesar_fusion_directa` antes de cada upsert — para un `n_id`
aliaseado (cualquiera de las 2 acciones), la propia `CromoBotella` nunca se crea/actualiza.

**Riesgo a tener presente al cargar filas a mano**: si `id_cromo_destino` corresponde a una clase que
este repo nunca ingiere como `CromoBotella` (ODF, o cualquier clase fuera de `CLASES_BOTELLA`), esa
fila queda como `REF_COLGADA` permanente en `fase_reconciliacion` — comportamiento esperado, no un
bug: el destino de una fusión debe ser un n_id de botella real e ingerible.

**Sin CRUD/API todavía** (fuera de alcance de este cambio): las filas se cargan por SQL directo o un
script puntual. Tampoco se retira retroactivamente una `CromoBotella` que ya existía de una corrida
ANTERIOR a que se cargara el alias — "saltar el upsert" sólo detiene escrituras futuras.

### Repoblación de cables con historial "ID dual" (2026-08-21)

Caso real confirmado (Verificador Cromo, botella "B2-FO-CAR", `n_id=9057909`): Cromo versiona
objetos internamente — un `id` de versión queda "vacío" (`tp[]=[]`) cuando la topología pasa a un
`next_id` (`hist[]` de la respuesta de `GET /db/objects/{id}?show=TOPOLOGIES&show=REL_ATTRIBUTE`).
El extremo de un cable conectado a esa botella reporta ese id de VERSIÓN (ej. `9057952`), no el
`n_id` ESTABLE (`9057909`) que usa la fila local de `cromo_botellas` — nunca matchean, así que el
cable puede quedar sin ingerir o vinculado a un id que no existe como Botella local.

`core/services/cromo/repoblacion_service.py` (nuevo) resuelve la cadena `hist[]`/`next_id` en vivo
contra Cromo, ancla cualquier extremo de cable que caiga en esa cadena al `n_id` local (nunca toca
`cromo_botellas`/`cromo_fusiones`, sólo `cromo_cables`/`cromo_tubos`/`cromo_pelos`), y persiste vía
`core/services/cromo/ingesta.py::upsert_versionado`/`upsert_simple` (promovidas a públicas) y una
nueva `upsert_forzado` — necesaria porque el `vmax` de un cable no cambia sólo porque su extremo
apuntaba a un id de versión vieja de la botella, así que `upsert_versionado` normal lo clasificaría
`SIN_CAMBIOS` y nunca corregiría el extremo. Expuesto vía `GET /api/infra/cromo/botellas/{n_id}/cables-detectados`
(sólo lectura) y `POST /api/infra/botellas/{n_id}/repoblar-cables` (admin) — ver `docs/infra.md`.

### Tabla `cromo_servicio_odf_override` (2026-09-08)

Escudo de asociación manual Servicio→ODF: cada fila es un EVENTO de asociación que un operador
confirma cuando el detector automático de "Servicios sin ODF"
(`core/services/cromo/servicios_sin_odf.py`) no puede resolver la ODF real de un Servicio por sí
solo. Alimenta el gestor `AdminServiciosSinOdfViewer.vue` (`/admin/servicios/viewer` → "Servicios sin
ODF").

| Columna | Tipo | Descripción |
|---|---|---|
| `id` (PK) | Integer | Autoincrement. |
| `servicio_id` (FK) | Integer | → `app.servicios.id`, `ON DELETE CASCADE`. Única FK **dura** de la tabla — a diferencia del resto de Cromo, `app.servicios` es un maestro propio de este repo, no un objeto de Cromo. |
| `odf_n_id` | BigInteger | La ODF elegida. **Sin FK dura** — mismo criterio que el resto de las referencias cruzadas a Cromo (`CromoCable.extremo_a_n_id`, `CromoBotellaAlias.id_cromo_destino`, etc.). |
| `pelo_n_id` (nullable) | BigInteger | Pin opcional a un conector físico concreto de la ODF. `NULL` = asociado a la ODF en general, sin pin a una posición específica (límite de alcance aceptado en esta primera iteración). Sin FK dura. |
| `categoria_causa` | Text + CHECK | `'OLT_PON_COMPARTIDO'` \| `'EQUIPO_DOMICILIO_CLIENTE'` \| `'SWITCH_COMPARTIDO_REVISAR'` \| `'SIN_SENAL_PROV'` \| `'OTRO'`. Los 4 primeros son exactamente lo que devuelve `categorizar()` (`CATEGORIAS_POR_PRIORIDAD`); **`'OTRO'` está en el CHECK pero hoy es inalcanzable** — ninguna rama de `categorizar()` lo produce y el gestor persiste siempre la categoría que calculó, así que existe sólo como escape para una categoría futura sin migración de constraint. Congelado como CHECK y no como Enum de Postgres (agregar un valor es `DROP`/`ADD CONSTRAINT`, no `ALTER TYPE`). |
| `subcategoria` (nullable) | Text + CHECK | `NULL` o `'PELO_SIN_CONECTOR_ODF'` \| `'AUSENTE_RED_CROMO'` \| `'BAJA_LOGICA_HEREDADA'` — sólo tiene valor cuando `categoria_causa='SIN_SENAL_PROV'`. |
| `senal_direccion` (nullable) | Text + CHECK | `NULL` o `'coincide'` \| `'no_coincide'` \| `'no_se_pudo_comparar'` — resultado de `direccion_comparacion.comparar_direccion_prov_vs_odf` recalculado y persistido server-side en el momento de la asociación (nunca confía en lo que mande el frontend). Puramente informativo, nunca bloquea el `INSERT`. |
| `usuario` | String(128) | Quién confirmó la asociación. |
| `notas` (nullable) | Text | Texto libre opcional del operador. |
| `creado_en` | DateTime(tz) | `server_default=CURRENT_TIMESTAMP`. |

Índices: `ix_cromo_servicio_odf_override_servicio_id` (btree, `servicio_id`) e
`ix_cromo_servicio_odf_override_odf_n_id` (btree, `odf_n_id`).

**Sin `UNIQUE(servicio_id)` a propósito**: permite reasociar (el operador corrige una asociación
previa) sin perder historial — cada fila es un evento, nunca se pisa con `UPDATE`. La lectura siempre
toma la fila más reciente por `servicio_id` (`ORDER BY creado_en DESC, id DESC`,
`core/services/cromo/servicio_odf_override_service.py::override_vigente_de_servicio`/
`overrides_vigentes_por_odf`) — verificado real que reasociar a otra ODF deja al Servicio sólo bajo
la ODF más nueva, nunca duplicado bajo las dos.

**Migración:** `20260908_01_cromo_servicio_odf_override.py` — crea esta tabla + los 3 CHECK + los 2
índices propios, y además un índice btree **parcial** nuevo sobre una tabla preexistente:
`ix_cromo_odf_conectores_servicio_resuelto` (`cromo_odf_conectores(servicio_resuelto) WHERE
servicio_resuelto IS NOT NULL`) — sólo 5,36% de esas ~205k filas tiene ese campo no nulo, así que un
índice completo hubiera desperdiciado espacio sin cambiar el plan. Fix de performance verificado real
contra `EXPLAIN ANALYZE` (ver `docs/decisiones.md`, entrada 2026-09-09, para la historia completa de
los tres cuellos de botella medidos).

**Migración `20260908_02_servicios_alias_ids_gin.py`:** índice GIN `ix_servicios_alias_ids_gin`
sobre `app.servicios.alias_ids` (`character varying(64)[]`, ya existente) — habilita el self-join
anti-ambigüedad del detector de "Servicios sin ODF" cuando se reescribe a contención (`alias_ids @>
ARRAY[...]`) en vez de `escalar = ANY(columna_array)` (la opclass default de GIN para arrays no
acelera esta última forma). Índice completo, no parcial: `alias_ids` es `NULL` en la mayoría de las
filas y GIN ya no indexa filas nulas por sí mismo.

**Escritura:** `core/services/cromo/servicio_odf_override_service.py::crear_override` — valida que
`odf_n_id` tenga fila PROPIA en `app.cromo_odfs` (criterio ESTRICTO, mismo que exige
`verificador.py::servicios_por_odf`) antes de insertar, para no dejar un override "colgado" contra
una ODF conocida sólo por referencia.

**Lectura:** `core/services/cromo/verificador.py::servicios_por_odf` suma los overrides vigentes de
una ODF al resultado del match automático por texto, deduplicando por `servicio_id` si el mismo
Servicio ya resolvía por el camino automático (gana el automático, que trae datos más ricos). Expuesto
vía `GET /api/infra/cromo/odfs/{odf_n_id}/servicios` (`web/app/routers/cromo.py`) — cada fila con override manual
aparece con `metodo="OVERRIDE_MANUAL"`.

### `cromo_tracking_cache` (caché de trackings con vencimiento, 2026-09-17)

Caché de **salida**, no inventario: guarda el `.txt` ya renderizado por
`core/services/cromo/camino_optico_txt.py::renderizar_tracking_txt`, con vencimiento. Las tablas
`cromo_*` de inventario siguen sin recibir nada derivado de `/path`.

| Columna | Tipo | Notas |
|---|---|---|
| `pelo_n_id` | BigInteger PK | `n_id` de linaje del pelo, **sin FK dura** (mismo criterio que el resto del namespace). La clave es el pelo y no el Servicio, para que dos Servicios que comparten pelo compartan la entrada. |
| `servicio_id` | Integer FK → `app.servicios.id` `ON DELETE CASCADE` | FK dura porque apunta a un maestro propio. Informativo: el último Servicio que lo generó. |
| `nombre_archivo` | String(256) | Nombre base, **sin** el sufijo de desambiguación por pelo: ése lo agrega el endpoint sólo si el Servicio tiene más de una semilla. |
| `contenido` | Text | El `.txt` completo. |
| `duracion_ms` | Integer | Lo que costó generarlo, para diagnóstico. |
| `generado_at` | timestamptz, indexado | Base del TTL. |

**TTL:** 24 h por defecto, ajustable con `CROMO_TRACKING_CACHE_TTL_HORAS`. Vive en la capa de
servicio, no en el esquema: no hay constraint de frescura, la lectura descarta lo vencido y la
escritura purga (aprovecha que el caché sólo crece cuando alguien descarga, así que no hace falta
un job de limpieza). Un valor inválido no rompe la descarga: se registra y se cae al default.

**Motivo medido** (real contra Cromo, 2026-09-17): una llamada a `GET /network/fo/{pelo}/path`
tarda 4,6-14 s, y pasarle varios ids separados por coma **no** devuelve varios caminos — con 3 ids
Cromo contestó un único nodo raíz. Bajar los trackings de un Servicio de 6 pelos costaba 30-85 s en
frío; con el caché, 0,00 s en caliente. Al normalizar una inconsistencia se **invalida** la entrada
del pelo: el `.txt` previo describe un estado de la base que ya cambió.

### Cambios del tracking por tramos y ODF Nodo (2026-10-16)

- **`cromo_odfs`** (`20261016_01`): la clase 86 entra al catálogo `cromo_clases` (ODF_NODO, ingerible)
  y el CHECK de `tipo_elemento` suma `ODF_NODO`.
- **`cromo_odf_conectores.patch_conector_n_id`** (`20261016_01`, BigInteger NULL): `tp[]` de clase 136.
  `pelo_n_id` pasa a llenarse sólo con `tp` de clase 130; el backfill SQL de la migración anula los
  erróneos (no se revierte en el downgrade). El downgrade de `20261016_01` **borra** las filas
  `ODF_NODO` de `cromo_odfs` y sus conectores de `cromo_odf_conectores`.
- **`cromo_tracking_cache.extremos`** (`20261016_02`, JSONB NULL, `none_as_null`): extremos del camino
  (ODF, clase, patchera, conector, `servicio_at62`) y botellas extremas. `NULL` = entrada previa, se regenera.
- **`servicio_odf_confirmada`** (`20261016_03`): `id`, `servicio_id` FK `servicios.id` CASCADE,
  `odf_n_id` BigInteger (referencia blanda a `cromo_odfs.n_id`), `rol` CHECK `EXTREMO`/`TRANSITO`,
  `confirmado_por`, `confirmado_en`, `vigente` (default true). Único parcial
  `(servicio_id, odf_n_id) WHERE vigente` e índice por `servicio_id`. No reemplaza a
  `cromo_servicio_odf_override`.
- **`servicios.trackings_esperados`** (`20261016_03`, SmallInteger NULL, CHECK `> 0`): cantidad declarada por el operador.
- **`cromo_auditoria_huerfanos`** (`20261016_04`): `corrida_id` FK `cromo_ingesta_corridas` SET NULL,
  `servicio_id` FK CASCADE, `pelo_n_id`, `camino_semilla`, `causa` (CHECK: CABLE_DESUSO,
  PELO_DANADO, CAMBIO_CABLE_DANO, MIGRACION_SITIO, SIN_CLASIFICAR), `evidencia` JSONB, `estado`
  (CHECK PENDIENTE/NORMALIZADO/DESCARTADO), `revisado_por`, `detectado_at`, `actualizado_at`.
  UNIQUE `(servicio_id, pelo_n_id)`, índice `(estado, causa)`.
- **`cromo_servicio_pelo_excluido`** (`20261016_04`): `origen` (Text NOT NULL default `MANUAL`,
  CHECK MANUAL/AUDITORIA) y `auditoria_id` FK `cromo_auditoria_huerfanos` SET NULL.

Ver `docs/infra.md` ("ODF Nodo, tracking por tramos y auditoría de huérfanos").

### Inconsistencias de Cromo y cuarentena (2026-10-17)

- **`cromo_odf_conectores.fusion_odf_n_id`** (`20261017_01`, BigInteger NULL): n_id de la fusión de ODF
  (141) por la que el conector llega a su pelo o a otro conector. `NULL` = no pasa por una 141.
- **`cromo_inconsistencia`** (`20261017_02`): `id`, `tipo` (CHECK `ISLA_FUSION`/`CABLE_SIN_EXTREMO`/
  `ELEMENTO_ISLA`), `objeto_n_id` (referencia blanda), `objeto_clase`, `nombre`, `localidad`,
  `revision` (CHECK `AUTO`/`MANUAL`), `estado` (CHECK `PENDIENTE`/`CUARENTENA`/`REPORTADA`/`CORREGIDA`/
  `ACEPTADA`), `evidencia` JSONB, `primera_vez`, `ultima_vez`, `actualizado_por`, `actualizado_en`.
  UNIQUE `(tipo, objeto_n_id)`, índice `(estado, tipo)`.
- **`cromo_inconsistencia_pelo`** (`20261017_02`): PK `(inconsistencia_id, pelo_n_id)`, FK
  `inconsistencia_id` -> `cromo_inconsistencia.id` ON DELETE CASCADE, índice por `pelo_n_id`.
- **`v_cromo_servicio_match_vigente`** (`20261017_03`): vista `SELECT m.*` de `cromo_servicio_match`
  `WHERE NOT EXISTS` (pelo en un caso con `estado = 'CUARENTENA'`). Los lectores del uso leen la vista;
  los escritores siguen sobre la tabla (guarda: `tests/test_cromo_cuarentena_lectores.py`).
- **`config_servicios`** (`20261017_04`): fila `Cromo Inconsistencias`, `intervalo_horas=0`,
  `slack_channels=''`, `activo=false`.

**Orden de despliegue:** `20261017_02` y `20261017_03` deben estar aplicadas **antes** de arrancar el
código nuevo: los lectores consultan la vista, y sin ella fallan con `UndefinedTable`.
Orden completo: 1) `alembic upgrade head`; 2) rebuild + recreate de `cromo_worker` (necesita
`slack_sdk` y el secret de Slack, y conoce los tipos de corrida nuevos: un worker viejo trataría una
corrida de detección como una ingesta); 3) recién después `web`, `api`, `slack_baneo_worker` y
`fo_monitor_worker`.
Ver `docs/infra.md` ("Inconsistencias de Cromo y cuarentena").

**Vista y columnas:** `v_cromo_servicio_match_vigente` usa `SELECT m.*`, y Postgres congela la lista de
columnas al crear la vista. Toda migración que agregue o quite columnas de `cromo_servicio_match` debe
hacer `DROP VIEW` antes y recrearla después.

### Árbitro de Cromo (2026-10-19, migración `20261020_01`)

Cuatro tablas nuevas y dos columnas en el override. Vocabularios como Text + CHECK, y sin FK hacia
objetos de Cromo: sólo hacia maestros propios. Funcionamiento: `docs/modulo_ingesta_cromo.md`,
sección "Árbitro de Cromo".

- **`cromo_regla_correccion`:**
  - `codigo` (PK), `modo` (CHECK `APAGADA`/`SOMBRA`/`AUTO`, default `SOMBRA`), `umbral` smallint
    (CHECK 0-100, default 90), `presupuesto_por_corrida` (CHECK ≥ 0, default 50), `descripcion`,
    `actualizado_por`, `actualizado_en`.
  - Sembrada con las 5 reglas en `SOMBRA`/90/50: `ODF_POR_CAMINO`, `CONTRADICCION_SERVICIO`,
    `GEMELO_VACIO`, `GEMELO_OPERATIVO` y `ODF_GEMELA_ISLA`.
- **`cromo_propuesta`:**
  - Columnas: `id` bigint, `regla` (FK → `cromo_regla_correccion.codigo`), `objeto_tipo` (CHECK
    `SERVICIO`/`BOTELLA`/`ODF`/`CABLE`), `objeto_id` bigint, `accion` (CHECK `ASOCIAR_ODF`/
    `FUSIONAR_GEMELO`/`INFORMAR`), `parametros` y `senales` JSONB, `confianza` (CHECK 0-100),
    `evidencia_hash` (sha256).
  - Estado y trazabilidad: `estado` (CHECK `PROPUESTA`/`EN_OBSERVACION`/`APLICADA`/`RECHAZADA`/
    `REVERTIDA`/`OBSOLETA`), `modo_al_evaluar`, `disparo` (CHECK `INGESTA`/`REGISTRADOR`/`VIEWER`/
    `NORMALIZADOR`), `reversion` JSONB, `nota` (motivo del último intento fallido), `creada_en`,
    `actualizada_en`, `decidida_por`, `decidida_en`, `aplicada_en`.
  - Índices: único parcial `ux_cromo_propuesta_abierta (regla, objeto_tipo, objeto_id) WHERE estado
    IN ('PROPUESTA','EN_OBSERVACION')` (una abierta por objeto y regla) y `ix_cromo_propuesta_estado_regla`.
- **`cromo_evidencia_camino`:**
  - PK `(servicio_id, pelo_n_id)`, FK `servicio_id` → `servicios.id` ON DELETE CASCADE.
  - `completo` bool, `extremos` JSONB (por lado: tipo, clase, `id_cromo`, `odf_id`, `odf_clase`,
    `odf_nombre`, `conector_numero`, `patchera_nombre`, `servicio_at62`, `pelo_conectado`),
    `pelos_camino` bigint[], `fuente` (CHECK `SLACK`/`WEB`/`AUDITORIA_GLOBAL`), `generado_at`.
  - El árbitro sólo usa filas `completo` de los últimos 30 días.
- **`cromo_arbitro_evaluacion`:**
  - Una fila por corrida del motor: `id`, `disparo`, `alcance` JSONB, `reglas` text[] (NULL = todas),
    `estado` (CHECK `EN_COLA`/`EN_CURSO`/`OK`/`OMITIDA`/`FALLIDA`), `resumen` JSONB (con `por_regla`),
    `error`, `solicitada_por`, `encolada_en`, `iniciada_en`, `terminada_en`.
  - Índice `ix_cromo_arbitro_evaluacion_encolada_en` (DESC).
- **`cromo_servicio_odf_override`:**
  - `origen` (CHECK `MANUAL`/`AUTO`, default `MANUAL`).
  - `propuesta_id` (FK → `cromo_propuesta.id` ON DELETE SET NULL).
  - `categoria_causa` suma `EVIDENCIA_CAMINO`.
  - Una fila AUTO es la que escribe el árbitro. Revertir borra sólo filas `origen='AUTO'`, nunca una
    MANUAL.

`downgrade()` borra las filas `EVIDENCIA_CAMINO` del override, restaura su CHECK original y elimina
columnas y tablas.

**Despliegue:** `20261020_01` ya está aplicada en la base dev compartida (`focas_dev`) desde la Task 2
de la rama, antes de integrar. Orden en prod: migración, `cromo_worker`, y después `web`,
`botellas_recalculo_worker` y `slack_baneo_worker`.

### Tabla `servicio_posicion_vigente` (2026-10-21, migración `20261021_01`)

Conector de ODF que un admin declara como la posición por la que hoy va un Servicio; el tracking
siembra desde su `pelo_n_id`. Modelo `ServicioPosicionVigente` (`db/models/cromo.py`), lógica en
`core/services/cromo/servicio_posicion_vigente.py`. Comportamiento (siembra, retiro automático,
avisos) en `docs/infra.md`, sección "Posición vigente por conector, caminos adicionales y `full`".

| Columna | Tipo | Notas |
|---|---|---|
| `id` | Integer PK | |
| `servicio_id` | Integer FK → `servicios.id` `ON DELETE CASCADE`, `NOT NULL` | |
| `conector_n_id` | BigInteger, `NOT NULL` | Referencia blanda (sin FK) a `cromo_odf_conectores.n_id`: Cromo puede reingerir. |
| `odf_n_id`, `bandeja_n_id`, `bandeja_nombre`, `numero_conector` | BigInteger / BigInteger / Text / Text | Foto del conector al declarar, para avisar aunque desaparezca. `odf_n_id` `NOT NULL`. |
| `pelo_n_id` | BigInteger, `NOT NULL` | Pelo declarado (semilla del tracking). |
| `pelos_candidatos` | BigInteger[], nullable | Todos los pelos del conector al declarar; sólo es `PELO_CAMBIO` si el pelo actual no está entre ellos. |
| `declarado_por`, `declarado_en` | String(128) `NOT NULL` / timestamptz default `CURRENT_TIMESTAMP` | |
| `vigente` | Boolean, `NOT NULL`, default `true` | Retirar es `vigente = false`, nunca `DELETE`. |
| `retirado_en`, `retirado_por`, `motivo_retiro` | timestamptz / String(128) (`'auto'` o el usuario) / Text | |
| `detalle_retiro` | JSONB, nullable (`none_as_null`) | |

**Claves y restricciones:** índice único parcial `ux_servicio_posicion_vigente_vigente
(servicio_id, conector_n_id) WHERE vigente` (una declaración vigente por conector), índice
`ix_servicio_posicion_vigente_servicio (servicio_id)`, CHECK `ck_servicio_posicion_vigente_motivo`
(`motivo_retiro` NULL o `MANUAL`, `SIN_PELO`, `PELO_CAMBIO`, `PELO_DANADO`, `CABLE_SIN_USO`,
`CONECTOR_INEXISTENTE`) y CHECK `ck_servicio_posicion_vigente_retiro_coherente` (una fila retirada
tiene `retirado_en` y `motivo_retiro`).

### `cromo_splitters` y `cromo_splitter_puertos` (2026-09-17)

Splitter óptico (clase 133) y sus puertos (clase 134). **Los dos ya venían en el `inner[]` de cada
barrido de botella** y `parse_arbol_botella` los descartaba como "clase inesperada": ingerirlos
cuesta **cero llamadas extra**.

| `cromo_splitters` | Tipo | Notas |
|---|---|---|
| `n_id` | BigInteger PK | Sin FK dura, mismo criterio que el resto del namespace. |
| `botella_n_id` | BigInteger, indexado | Lo aporta el **recorrido del árbol**, no `parent`: `/inner` devuelve los hijos sin él. |
| `nombre` | Text | `at.78` ("S-1269002-2", "SPLITTER1"). |
| `ratio` | Text | `at.83` crudo ("1x8"). **Cromo lo publica**: no se deduce. |
| `salidas` | Integer | El `N` de "1xN" parseado. NULL si el texto no matchea — no se inventa. |

| `cromo_splitter_puertos` | Tipo | Notas |
|---|---|---|
| `n_id` | BigInteger PK | |
| `splitter_n_id` | BigInteger, indexado | `parent`; con `/inner` se infiere sólo si la botella tiene **un** splitter. |
| `botella_n_id` | BigInteger, indexado | Desnormalizado desde el árbol. |
| `nombre` / `sentido` | Text | `at.80` ("E1", "S8") y `at.82` (`ENTRADA`/`SALIDA`, Text + CHECK). |
| `servicios_atributo` | JSONB **`none_as_null=True`** | `at.62`. **Tres estados**: NULL = no se preguntó (el barrido no trae el atributo, sólo `/inner`), `[]` = puerto libre, lista = servicios que sirve. |

`cromo_botellas.splitters_relevados` (Boolean, default `false`) distingue "no tiene splitters" de
"todavía no se barrió con el código que los lee". Sin ese marcador, cero filas sería ambiguo y
`empalmes.py` no podría apagar su heurística sin romper las botellas aún no barridas.

**Por qué existe:** medido sobre 30 botellas reales, la heurística de fan-out de `empalmes.py`
acertó en 18 y falló en 12 —incluido inventar 2 splitters donde Cromo tiene 0— y **nunca** devolvió
un ratio cuando el splitter existía. Ver `docs/decisiones.md` (2026-09-17, seguimiento 3).

**Trampa de SQLAlchemy a no repetir:** sin `none_as_null=True`, Python `None` se serializa como JSON
`null`; entonces `IS NOT NULL` da TRUE, `jsonb_array_length()` aborta la consulta con *"cannot get
array length of a scalar"* y los tres estados se vuelven dos.

**Ampliación 2026-09-19 — `contenedor_n_id` / `contenedor_clase`.** `botella_n_id` asumía que un
splitter cuelga de una Botella. Medido sobre **800 splitters reales**, sólo el 12 % lo hace: el
reparto por clase del contenedor es 137→435, 139→176, 68→84, 138→35, 84→32, 140→21, 122→8, 126→4,
125→2 y 123/121/127→1. Las dos columnas nuevas guardan el contenedor real, sin FK dura porque apunta
a dos tablas según la clase. `botella_n_id` se conserva sin tocar —es por donde consulta
`empalmes.py`— y pasa a poblarse **sólo** cuando el contenedor es de una clase Botella.

### `cromo_pon_elementos` (2026-09-19)

Elementos raíz de la red de acceso PON: **cajas PON** (clases 84, 126, 127, 137, 138, 139, 140) y
**rosetas** (85), en una sola tabla discriminadas por `clase` (FK contra `cromo_clases`).

Una tabla y no ocho porque el esquema medido contra Cromo es idéntico en las ocho: todas son objetos
raíz (`parent` ausente), traen `ll`/`pts`/`vmax` y publican los mismos `at` (16, 20, 34, 35, 40, 41,
45, 46, 47, 67, 68, 69, 91, 203). Lo que separa una caja PON de una roseta es `cromo_clases.entidad`,
que es de donde `camino_optico_service` ya saca la etiqueta del nodo; cada vista de inventario filtra
por su lista de clases.

Versionada (`version_id`/`vmax`/`payload_raw`) como `cromo_odfs`, no liviana como `cromo_splitters`:
`vmax` deja que `upsert_versionado` distinga CREADA/ACTUALIZADA/SIN_CAMBIOS, y `version_id` habilita
la segunda pasada de `camino_optico_service._vincular_local` —sin él, un nodo de `/path` que llega
identificado por su id de versión nunca vincula con la fila local—.

| Columna | Tipo | Descripción |
|---|---|---|
| `n_id` (PK) | BigInteger | Identidad de linaje. |
| `version_id` / `vmax` | BigInteger / Integer | Versión vigente y detector de cambios. |
| `clase` | SmallInteger, FK `cromo_clases` | 84/126/127/137/138/139/140 (caja PON) u 85 (roseta). |
| `nombre`, `codigo_modelo`, `id_legacy`, `notas` | Text | `at.34`, `at.41`, `at.91`, `at.35`. |
| `calle`, `altura`, `localidad`, `provincia`, `ubicacion_fisica`, `tendido` | Text | `at.67`, `at.16`, `at.68`, `at.69`, `at.118`, `at.20` — **mismo mapeo que `parse_botella`**, por eso el parser lo reusa. |
| `propietario` | Text | `at.47` ("Metrotel", "MB", "FANS"). |
| `tipo_conector` | Text | `at.40` ("Fast connect", "Easy Connect", "Conector de campo", "Con casquillo"). |
| `capacidad_puertos` | SmallInteger | `at.46`. Sobre 81 objetos reales tomó **sólo** los valores 8, 16 y 4. |
| `latitud`, `longitud`, `pts_raw` | Float / JSONB | Geo, igual que botellas y ODFs. |
| `payload_raw` | JSONB | Objeto crudo. |
| `vigente`, `primera_ingesta`, `ultima_ingesta`, `ultima_modificacion` | — | Auditoría estándar del módulo. |

**Qué NO tiene columna, y por qué:** `at.45` fue constante ("SI" en los 81 objetos medidos) y
`at.203` devolvió valores incoherentes entre sí ("00000", "0", "115124", "90933"). No se les inventa
semántica: viajan en `payload_raw` hasta que alguien los entienda.

Volumen esperado: 13.482 cajas PON + 17.348 rosetas ≈ 30.800 filas.

### Tabla `api_clients` (OAuth2 M2M, 2026-09-29)

Clientes máquina-a-máquina de la API v1 (un área corporativa por fila). Los administra
`scripts/api_clients.py`; ver `docs/api.md`, sección "API v1 para integraciones interáreas".

| Columna | Tipo | Notas |
|---|---|---|
| `id` | `SERIAL` PK | |
| `client_id` | `String(64)`, `NOT NULL`, único (`ix_api_clients_client_id`) | Formato `lf_<16 hex>`. Es el `sub` del JWT. |
| `client_secret_hash` | `String(255)`, `NOT NULL` | `core/password.py::hash_password` (SHA-256 + bcrypt). El secreto en claro nunca se guarda. |
| `nombre_area` | `String(128)`, `NOT NULL` | Área dueña de la integración. |
| `activo` | `BOOLEAN`, `NOT NULL`, default `true` | Se revalida en cada request: `false` corta los tokens vigentes. |
| `scopes` | `VARCHAR(64)[]`, `NOT NULL`, default `'{}'` | Scopes autorizados: `servicios:read` y/o `cables:read`. |
| `created_at` | `timestamptz`, default `now()` | |
| `ultimo_uso_at` | `timestamptz`, nullable | Última emisión de token. |

## FO Monitor (`fomon_*`, 2026-10-14)

Nueve tablas creadas por `20261014_02_fo_monitor.py`; modelos en `db/models/fo_monitor.py`.
Funcionamiento, estado y operación en `docs/fo_monitor.md`. Estados y fases son `String` + `CHECK`
(no enums de Postgres). `servicio_pk` no tiene FK a `app.servicios` **a propósito**: la fusión por
cadena PROV (`core/services/servicios_fusion_prov.py`) borra filas superadas y el histórico de FO
Monitor no debe romperse. La migración también siembra la fila `fo_monitor` en
`app.config_servicios` (kill switch y canal, **inactiva**, canal `C08UB8ML3LP`); su `downgrade()`
borra todo, incluida esa fila.

| Tabla | Propósito | Columnas, claves e índices relevantes |
|---|---|---|
| `fomon_config` | Singleton de configuración del piloto (editable por admin). | `id` SmallInteger PK con `CHECK id = 1` (`ck_fomon_config_singleton`); `ventana_desde`/`ventana_hasta`; `tope_mensajes_diario` (400), `max_ids_por_mensaje` (10, `CHECK` 1-20), `timeout_base_s` (240), `timeout_por_servicio_s` (20), `concurrencia` (3, `CHECK` 1-10), `burrito_user_id`, `prompt_version`, `canales_ingreso` (coma-separados; default `C08UB8ML3LP`), `ultimo_ingreso_id_procesado` (marca de agua; se siembra con `max(ingresos.id)` para no procesar el histórico), `actualizado_por`/`actualizado_at`. |
| `fomon_config_auditoria` | Quién cambió la configuración y qué. **Append-only.** | `id` BigInteger PK, `usuario`, `cambios` JSONB, `created_at`. |
| `fomon_intervenciones` | Una intervención a verificar (por ingreso de técnico o manual). | `id` PK; `origen` (`CHECK` `INGRESO`/`MANUAL`); `camara_id` FK → `camaras.id` `ON DELETE SET NULL`; `botella_objetivo_n_id`, `cable_n_id_manual`, `tecnico`, `thread_ts_ingreso`, `canal_ingreso`; `estado` (`CHECK` `PRE_PENDIENTE`, `PRE_EN_CURSO`, `EN_CURSO`, `POST_PENDIENTE`, `POST_EN_CURSO`, `CERRADA`, `SIN_EGRESO`, `CANCELADA`); `fecha_ingreso`/`fecha_egreso`; banderas `botella_1_inferida`, `sin_linea_base`, `post_tardio`, `egreso_inferido`, `atribucion_compartida`; `aviso_canal`/`aviso_ts`; `proximo_evento_en`; `iniciada_por`, `creada_at`, `actualizada_at`, `cerrada_at`. Índices por `camara_id`, `estado` y `proximo_evento_en`. |
| `fomon_intervencion_ingresos` | Ingresos de `app.ingresos` asociados a una intervención. | PK `(intervencion_id, ingreso_id)`, ambas FK `ON DELETE CASCADE`; `UNIQUE (ingreso_id)` (`uq_fomon_interv_ingresos_ingreso`): un ingreso pertenece a una sola intervención. |
| `fomon_intervencion_servicios` | Alcance congelado en el PRE: cables y servicios a verificar. | `id` BigInteger PK; `intervencion_id` FK `ON DELETE CASCADE`; `cable_n_id`, `cable_nombre`, `cable_clase`, `botella_n_id`, `es_objetivo`; `servicio_pk` (NULL = cable sin servicios verificables), `servicio_id_externo`, `tipo_servicio`, `categoria`, `cliente`. `UNIQUE (intervencion_id, cable_n_id, servicio_pk)` (`uq_fomon_interv_serv`); índices por `intervencion_id` y `cable_n_id`. |
| `fomon_consultas` | Un mensaje a burritoIA. | `id` PK; `intervencion_id` FK; `fase` (`CHECK` `PRE`/`POST`/`REVERIF`), `intento`; `estado` (`CHECK` `PENDIENTE`, `ENVIADA`, `RESPONDIDA`, `TIMEOUT`, `ERROR`, `CANCELADA`); `servicios_pk` Integer[], `ids_solicitados` String(64)[]; `prompt_version`, `canal`, `slack_ts`, `permalink`, `texto_crudo`, `ref_burrito`, `completa`, `lineas_invalidas`, `error`; `creada_at`, `enviada_at`, `respondida_at`, `proximo_evento_en`. Índices por `intervencion_id`, `estado` y `enviada_at`. |
| `fomon_resultados` | Estado medido de cada servicio en cada fase. **Append-only.** | `id` BigInteger PK; `consulta_id` FK → `fomon_consultas.id`; `intervencion_id` (sin FK); `fase` (`CHECK` como en consultas); `servicio_pk`, `servicio_id_externo`; `estado` (`CHECK` `UP`, `DOWN`, `ADMIN_DOWN`, `DESCONOCIDO`, `NO_SOPORTADO`); `extremo`, `motivo`, `parseado`, `medido_at`. Índices por `consulta_id` e `intervencion_id`. |
| `fomon_reconocimientos` | Reconocimiento manual, con motivo, de una intervención o de uno de sus servicios (`servicio_pk`); lo escribe `core/services/fo_monitor/consultas_web.py::reconocer`. **Append-only.** | `id` PK; `intervencion_id` FK; `servicio_pk`; `usuario`; `motivo` (`CHECK length(trim(motivo)) >= 3`); `created_at`. Índice por `intervencion_id`. |
| `fomon_cable_geo` | Polilínea WGS84 simplificada por cable para el mapa (sin PostGIS). | `cable_n_id` BigInteger PK; `coords` JSONB (`[[lon, lat], ...]`); bbox `min_lon`/`min_lat`/`max_lon`/`max_lat` con índice `ix_fomon_cable_geo_bbox`; `vmax`; `calidad`; `actualizado_at`. La escribe `core/services/fo_monitor/geometria.py::actualizar_geometrias` (incremental por `vmax`, purga los cables no vigentes), que `core/services/cromo/ingesta.py` invoca tras las corridas de los modos de `MODOS_GEOMETRIA_FO` (`COMPLETA`, `SOLO_CABLES`, `SOLO_CABLES_BAJADA`, `SOLO_CABLES_TERCEROS`). |

**Append-only:** `fomon_resultados`, `fomon_reconocimientos` y `fomon_config_auditoria` tienen el
trigger `trg_<tabla>_inmutable` (`BEFORE UPDATE OR DELETE ... FOR EACH ROW`) que ejecuta
`app.fomon_bloquear_mutacion()` y aborta con `RAISE EXCEPTION`, el mismo patrón que
`ingresos_correcciones`.

## Extensiones PostgreSQL requeridas

| Extensión | Motivo |
|-----------|---------|
| `unaccent` | Normalización de acentos en búsquedas ILIKE de cámaras (`camara_busqueda_nombre._buscar_ilike`, `_buscar_tokens`). Se instala via migración `20260427_01`. |

Se agrega además en `db/init.sql` con `CREATE EXTENSION IF NOT EXISTS unaccent;` para que nuevos entornos no requieran correr la migración manualmente.

## Migraciones y despliegue

- Ejecutar migraciones con Alembic apuntando al archivo `db/alembic.ini`. Ejemplo local (fuera de Docker Compose):
	```bash
	source .venv/bin/activate
	export ALEMBIC_URL="postgresql+psycopg://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:$POSTGRES_PORT/$POSTGRES_DB"
	alembic -c db/alembic.ini upgrade head
	```
- El enum `app.camara_estado` se crea sólo si no existe (`create_type=False` + `checkfirst=True`), lo que permite reintentos sin tener que limpiar tipos manualmente.
- En entornos dockerizados, reemplazar `localhost` por el hostname del contenedor (`postgres`) y dejar que Compose gestione las credenciales.

## Autogenerate y drift modelo↔base (2026-10-27, P18)

`db/alembic/env.py` compara contra `Base.metadata` (antes tenía `target_metadata = None`). El
alcance vive en `db/models/autogenerate.py` y lo comparten `env.py`, el script de chequeo y el test:

- sólo el esquema `app` (`public` tiene `alembic_version` y el enum `punto_terminal_tipo`);
- fuera del alcance van `TABLAS_SIN_MODELO`: `chat_messages`, `chat_sessions`, `conversations`,
  `example`, `messages`, `report_history` y `web_users`. Existen y se usan con SQL crudo, pero no
  tienen modelo. La lista es explícita a propósito: una tabla nueva sin modelo aparece como drift;
- se comparan tipos, nulabilidad, `server_default`, comentarios, índices y constraints.

`db/base.py` define la convención de nombres `ix_<tabla>_<columnas>` para `index=True`, la misma
que usan las migraciones. Sin ella, SQLAlchemy nombraba `ix_app_<tabla>_<col>`. Cuando el nombre
real es otro (`ix_cromo_pelos_cable`, `uq_servicios_sync_prov_servicio_id`…), el modelo lo declara
con un `Index(...)` explícito en `__table_args__`.

**Alineación (la base manda).** Antes había 149 diferencias contra dev: 77 índices con otro nombre,
12 índices creados por migración que el modelo no declaraba, 47 `server_default`, 9 comentarios,
2 tipos (`servicios.raw_tracking_data` es `JSONB`, y el enum de `puntos_terminales.tipo` vive en
`public`), la nulabilidad de `rutas_servicio.created_at` y la constraint
`camaras_fontine_id_key`. Ahora hay 0. Se resolvieron declarando todo en los modelos, sin tocar la
base, salvo dos migraciones:

- `20261027_01` borra `ix_camaras_fontine_id`, un índice UNIQUE duplicado exacto de
  `camaras_fontine_id_key` (los dos venían de `20251230_01`);
- `20261027_02` normaliza lo que **dev tiene y la cadena de migraciones no crea**: 6 nombres de
  índice (`incidentes_baneo` ×4, `config_servicios`, `rutas_servicio`), el `DEFAULT true` de
  `incidentes_baneo.activo` y 2 comentarios de `config_servicios`. Cada renombre se aplica sólo si
  el índice existe con el nombre de la cadena y no con el de dev, así que la migración es idempotente
  y prod converge tenga la variante que tenga.

Índices que se declaran pero en dev tienen `idx_scan = 0` (se informan, **no se borran**; dev no es
prod): `ix_cromo_botellas_nombre` (GIN `to_tsvector`, 2,4 MB), `ix_fomon_cable_geo_bbox` (2,1 MB) e
`ix_incidentes_baneo_servicio_activo`.

**Chequeos.** Los tres dan 0 diferencias al 2026-10-27:

```bash
# Contra dev (mismas variables que los tests *_real_db); exit 0 sin drift, 1 con drift, 2 sin conexión
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_DB=focas_dev POSTGRES_USER=FOCALBOT \
  POSTGRES_PASSWORD="$(cat .secrets/Dev_db_password_v1.txt)" python scripts/check_drift_modelos.py --detalle
alembic -c db/alembic.ini check            # con ALEMBIC_URL de dev: "No new upgrade operations detected."
scripts/check_drift_desde_cero.sh          # Postgres efímero: init.sql + cadena completa + drift 0
```

`tests/test_drift_modelos_real_db.py` falla si vuelve el drift contra dev, y
`tests/test_check_drift_modelos.py` cubre la clasificación y el alcance sin base.
`check_drift_desde_cero.sh` corre local: no está en GitHub Actions, por decisión del usuario, para
no gastar minutos.

**Producción** no se leyó (no hubo autorización). Para chequearla cuando se autorice, desde el
checkout de control y en sólo lectura (el script abre una transacción `READ ONLY`):

```bash
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 POSTGRES_DB=FOCALDB POSTGRES_USER=<usuario de prod> \
  POSTGRES_PASSWORD="$(cat .secrets/db_password_v1.txt)" python scripts/check_drift_modelos.py --detalle
```

Qué esperar: con prod en una revisión anterior a `20261027_01`, aparece al menos
`indice_solo_base: camaras.ix_camaras_fontine_id`. Según de dónde salió cada índice, también pueden
aparecer los 6 nombres de `20261027_02` y diferencias por las migraciones de dev que prod todavía no
tiene. Todo eso lo resuelven las dos migraciones del deploy. Cualquier otra diferencia es drift
propio de prod y se decide antes del deploy, nunca con un autogenerate a ciegas.

## Historial de migraciones

Tabla **generada** desde `db/alembic/versions/` por `scripts/gen_tabla_migraciones.py` (solo
lectura: parsea cada archivo con `ast`, sin importarlo). Orden de la cadena `down_revision` →
`revision`; la descripción es el encabezado `# Descripción:` de cada migración. No editarla a mano:

```bash
python scripts/gen_tabla_migraciones.py                       # imprime la tabla; pegarla entre los marcadores
python scripts/gen_tabla_migraciones.py --verificar docs/db.md # exit 1 si el bloque quedó desactualizado
```

Por stderr el script informa raíces, heads, merges, ramas y `down_revision` colgadas. Estado al
generarla (2026-10-26): 72 migraciones en una sola cadena lineal, raíz `20251007_01`, head
`20261023_01`, sin merges ni ramas.

<!-- tabla-migraciones:inicio -->
| Revisión | Revisa a | Fecha | Archivo | Descripción |
|----------|----------|-------|---------|-------------|
| `20251007_01` | — | 2025-10-07 | `20251007_01_chat_tables.py` | Migración inicial para tablas de chat del panel web |
| `20251008_01` | `20251007_01` | 2025-10-08 | `20251008_01_chat_tables_guard.py` | Refuerzo de tablas e índices para chat_sessions y chat_messages |
| `20251013_01` | `20251008_01` | 2025-10-13 | `20251013_01_add_geo_to_cases.py` | Migración para agregar columnas latitude/longitude a app.cases (si existe) |
| `20251014_01` | `20251013_01` | 2025-10-14 | `20251014_01_reclamos.py` | Crea tabla app.reclamos con índices y PK única en numero_reclamo |
| `20251230_01` | `20251014_01` | 2025-12-30 | `20251230_01_infra.py` | Crea tablas de infraestructura (cámaras, cables, empalmes, servicios, ingresos y asociación) |
| `20260108_01` | `20251230_01` | 2026-01-08 | `20260108_01_infra_updates.py` | Actualiza tablas de infraestructura: nuevo estado DETECTADA, enum origen_datos, campos servicio_id |
| `20260110_01` | `20260108_01` | 2026-01-10 | `20260110_01_ruta_servicio.py` | Crea tabla rutas_servicio y asociativa ruta_empalme para versionado de rutas |
| `20260112_01` | `20260110_01` | 2026-01-12 | `20260112_01_incidente_baneo.py` | Migración para crear tabla incidentes_baneo (Protocolo de Protección) |
| `20260112_02` | `20260112_01` | 2026-01-12 | `20260112_02_raw_file_content.py` | Agrega columna raw_file_content a rutas_servicio para guardar TXT original |
| `20260113_01` | `20260112_02` | 2026-01-13 | `20260113_01_puntos_terminales.py` | Agregar puntos terminales, alias_ids a servicios, es_transito a empalmes, cantidad_pelos a rutas |
| `20260127_01` | `20260113_01` | 2026-01-27 | `20260127_01_incidente_baneo_email_fields.py` | Agrega campos de asunto y cuerpo de correo a incidentes de baneo |
| `20260417_01` | `20260127_01` | 2026-04-17 | `20260417_01_config_servicios.py` | Crea tabla config_servicios para configuración de workers automatizados |
| `20260420_01` | `20260417_01` | 2026-04-20 | `20260420_01_camaras_estado_auditoria.py` | Crea tabla de auditoría para cambios manuales del estado de cámaras |
| `20260423_01` | `20260420_01` | 2026-04-23 | `20260423_01_config_servicios_hora_inicio.py` | Agrega columna hora_inicio a app.config_servicios para programar inicio del ciclo en GMT-3 |
| `20260427_01` | `20260423_01` | 2026-04-27 | `20260427_01_unaccent_extension.py` | Instala la extensión unaccent de PostgreSQL requerida por las búsquedas de cámaras |
| `20260428_01` | `20260427_01` | 2026-04-28 | `20260428_01_listener_workflow_ids.py` | Agrega workflow_ids y solo_workflows a config_servicios para el filtro de Workflow ID del listener |
| `20260428_02` | `20260428_01` | 2026-04-27 | `20260428_02_camara_alias_pendiente.py` | Agrega tabla app.camara_alias y el valor PENDIENTE_REVISION al enum camara_estado |
| `20260625_01` | `20260428_02` | 2026-06-25 | `20260625_01_report_history.py` | Crea tabla app.report_history para histórico persistente de informes web |
| `20260713_01` | `20260625_01` | 2026-07-13 | `20260713_01_servicios_sla_fase1.py` | Extiende app.servicios con campos SLA para ingesta y búsqueda paginada |
| `20260805_01` | `20260713_01` | 2026-08-05 | `20260805_01_cromo_ingesta.py` | Crea las tablas app.cromo_* (catálogo, auditoría e inventario) para la Etapa 2 de ingesta desde Cromo Red |
| `20260806_01` | `20260805_01` | 2026-08-06 | `20260806_01_cromo_ingesta_config.py` | Crea app.cromo_ingesta_config — configuración persistente del scheduler de ingesta automática (Etapa 7) |
| `20260807_01` | `20260806_01` | 2026-08-07 | `20260807_01_cromo_fusiones_botella_nullable.py` | cromo_fusiones.botella_n_id pasa a nullable — el fetch directo de clase 132 no trae "parent" (Etapa 8) |
| `20260810_01` | `20260807_01` | 2026-08-10 | `20260810_01_camara_padre_botella.py` | Jerarquía Cámara→Botella — FK auto-referencial camaras.camara_padre_id + valor INFERIDO en camara_origen_datos |
| `20260811_01` | `20260810_01` | 2026-08-11 | `20260811_01_cromo_botella_camara_padre.py` | Vincula Botellas Cromo a una Cámara padre propia (app.camaras) y les da estado operativo — nuevos valores NO_OPERATIVA/INFERIDO_CROMO |
| `20260811_02` | `20260811_01` | 2026-08-11 | `20260811_02_ingresos_sin_match.py` | Tabla app.ingresos_sin_match — reemplaza el auto-registro de Cámara PENDIENTE_REVISION en ingresos de técnicos sin match |
| `20260813_01` | `20260811_02` | 2026-08-13 | `20260813_01_cromo_botella_default_libre.py` | Cambia el server_default de app.cromo_botellas.estado de NO_OPERATIVA a LIBRE |
| `20260814_01` | `20260813_01` | 2026-08-14 | `20260814_01_servicios_categoria_check.py` | CHECK + DEFAULT + NOT NULL sobre app.servicios.categoria (0-6), backfill de las ~1488 filas existentes (100% NULL hoy) a 6 ("sin categorizar") |
| `20260814_02` | `20260814_01` | 2026-08-14 | `20260814_02_servicios_origen_datos.py` | Nuevo enum app.servicio_origen_datos + columna app.servicios.origen_datos — distingue servicios reales (MANUAL/TRACKING/INGEST_EXCEL) de placeholders sintetizados por el matching Cromo (INFERIDO_CROMO) |
| `20260819_01` | `20260814_02` | 2026-08-19 | `20260819_01_cromo_botella_alias.py` | Tabla de aliasing manual de botellas Cromo — permite marcar un n_id junk/duplicado como fusionado a un n_id "golden" o directamente ignorado, y que la ingesta lo honre. |
| `20260821_01` | `20260819_01` | 2026-08-21 | `20260821_01_cromo_botella_nombre_editado_manual.py` | Flag de protección de nombre editado a mano en Botellas Cromo — impide que una re-ingesta futura pise una corrección manual |
| `20260822_01` | `20260821_01` | 2026-08-22 | `20260822_01_cromo_botella_separada_manualmente.py` | Columnas de auditoría para la separación manual de una Botella Cromo de su Cámara padre |
| `20260823_01` | `20260822_01` | 2026-08-23 | `20260823_01_ingreso_seguimiento_empalme.py` | Columnas de seguimiento por hilo en IngresoSinMatch + índice en CromoBotella.nombre |
| `20260825_01` | `20260823_01` | 2026-08-25 | `20260825_01_cromo_pelo_verificacion.py` | Campos de verificación manual (verificable/status/fecha_hora_status) en cromo_pelos |
| `20260825_02` | `20260825_01` | 2026-08-25 | `20260825_02_servicios_verificable.py` | Agrega es_verificable (calculado por tipo_servicio, con backfill) y es_verificable_override (corrección manual) a app.servicios |
| `20260828_01` | `20260825_02` | 2026-08-28 | `20260828_01_cromo_odfs.py` | Nueva tabla app.cromo_odfs — submódulo ODFs de Cromo Red (clase 69), objeto de primer nivel hermano de Cable/Botella, sin columna de agrupamiento por sitio. |
| `20260831_01` | `20260828_01` | 2026-08-31 | `20260831_01_cromo_odf_conectores.py` | Nueva tabla app.cromo_odf_conectores — inventario de conectores/posiciones de patchera de una ODF (Cromo Red clases 135/136), con el servicio resuelto vía atributo directo + regex de pelo, combinados por criterio MAX-based ID final. |
| `20260831_02` | `20260831_01` | 2026-08-31 | `20260831_02_ingreso_cromo_botella.py` | Agregar FK de Cromo Botella a Ingreso para registrar qué botella específica se intervino |
| `20260902_01` | `20260831_02` | 2026-09-02 | `20260902_01_servicios_prov_historial_equipos.py` | Nuevo valor INGEST_PROV en app.servicio_origen_datos + tablas servicios_historial_id y servicios_equipos_ultima_milla para la integración con la API PROV |
| `20260904_01` | `20260902_01` | 2026-09-04 | `20260904_01_ingreso_tipo_movimiento.py` | Nuevo enum app.ingreso_tipo + columna app.ingresos.tipo — distingue INGRESO/EGRESO real de un INTENTO_BLOQUEADO por baneo |
| `20260907_01` | `20260904_01` | 2026-09-07 | `20260907_01_ingreso_sin_match_revalidacion.py` | Columnas de revalidación en IngresoSinMatch (texto_mensaje, resuelto_via_revalidacion, ingreso_id) |
| `20260908_01` | `20260907_01` | 2026-09-08 | `20260908_01_cromo_servicio_odf_override.py` | Tabla escudo cromo_servicio_odf_override (asociación manual Servicio→ODF de Cromo) + índice btree parcial de performance sobre cromo_odf_conectores.servicio_resuelto |
| `20260908_02` | `20260908_01` | 2026-09-08 | `20260908_02_servicios_alias_ids_gin.py` | Índice GIN sobre app.servicios.alias_ids — habilita el self-join anti-ambigüedad reescrito a contención (`alias_ids @> ARRAY[...]`) del detector "Servicios sin ODF" |
| `20260917_01` | `20260908_02` | 2026-09-17 | `20260917_01_cromo_tracking_cache.py` | Nueva tabla app.cromo_tracking_cache — caché de salida, con vencimiento, del tracking .txt de cada pelo, para que la descarga multipelo no pague N llamadas a Cromo. |
| `20260917_02` | `20260917_01` | 2026-09-17 | `20260917_02_cromo_clases_pon.py` | Registra en app.cromo_clases las clases de la red de acceso PON que el camino óptico atraviesa pero la ingesta no barre, para que el diagrama deje de mostrar "CLASE_84" |
| `20260917_03` | `20260917_02` | 2026-09-17 | `20260917_03_cromo_splitters.py` | Tablas app.cromo_splitters y app.cromo_splitter_puertos — el ratio del splitter y sus puertos vienen publicados por Cromo y hasta ahora se descartaban en cada corrida |
| `20260919_01` | `20260917_03` | 2026-09-19 | `20260919_01_cromo_clases_pon_ingeribles.py` | Da de alta las 5 clases de caja PON que faltaban en app.cromo_clases y marca ingeribles las clases de la red de acceso que el submódulo PON pasa a barrer |
| `20260919_02` | `20260919_01` | 2026-09-19 | `20260919_02_cromo_pon_elementos.py` | Crea app.cromo_pon_elementos, la tabla única de cajas PON y rosetas de la red de acceso, discriminadas por clase |
| `20260919_03` | `20260919_02` | 2026-09-19 | `20260919_03_cromo_splitters_contenedor.py` | Agrega contenedor_n_id/contenedor_clase a app.cromo_splitters, porque el 88% de los splitters no cuelga de una Botella sino de una caja PON |
| `20260919_04` | `20260919_03` | 2026-09-19 | `20260919_04_cromo_cables_clase.py` | Agrega clase a app.cromo_cables para poder alojar cables de bajada (66) junto a los de FO (51) sin que se confundan |
| `20260923_01` | `20260919_04` | 2026-09-23 | `20260923_01_ingresos_correcciones.py` | Columnas de hilo en app.ingresos + tabla append-only app.ingresos_correcciones (auditoría de "Forzar ingreso"/"Forzar egreso") |
| `20260923_02` | `20260923_01` | 2026-09-23 | `20260923_02_servicios_sync_prov.py` | Tabla app.servicios_sync_prov — última sincronización exitosa contra PROV por Servicio |
| `20260923_03` | `20260923_02` | 2026-09-23 | `20260923_03_servicios_sync_prov_nullable.py` | app.servicios_sync_prov.ultima_sincronizacion_ok pasa a NULLABLE — fix de la revisión de calidad de la Task 9 (centinela 1970-01-01 reemplazado por NULL) |
| `20260928_01` | `20260923_03` | 2026-09-28 | `20260928_01_ingresos_correcciones_origen_web.py` | Origen (slack/web) y actor web en app.ingresos_correcciones, para auditar el egreso registrado desde el panel |
| `20260929_01` | `20260928_01` | 2026-09-29 | `20260929_01_api_clients.py` | Tabla app.api_clients para OAuth2 client_credentials (M2M) de la API v1 |
| `20260929_02` | `20260929_01` | 2026-09-29 | `20260929_02_cromo_tracking_cache_pelos_camino.py` | Columna pelos_camino en app.cromo_tracking_cache — los pelos que recorre cada tracking, para entregar un .txt por camino distinto y no uno por posición de ODF. |
| `20260929_03` | `20260929_02` | 2026-09-29 | `20260929_03_cromo_clases_cables_terceros.py` | Da de alta en app.cromo_clases las clases de cable de terceros (52, 59 Telefónica, 60 Telecom), requisito de la FK cromo_cables.clase para poder ingerirlas. |
| `20260930_01` | `20260929_03` | 2026-09-30 | `20260930_01_cromo_pelos_atributos_inner.py` | Atributos at.62/at.63 del pelo (sólo vía /inner del cable) y config del barrido semanal SOLO_PELOS_INNER, sembrada deshabilitada. |
| `20261005_01` | `20260930_01` | 2026-10-05 | `20261005_01_cromo_servicio_pelo_excluido.py` | Tabla app.cromo_servicio_pelo_excluido — pelos que Cromo sigue etiquetando con un Servicio pero que el operador sacó de él en local (huérfanos de un camino). |
| `20261005_02` | `20261005_01` | 2026-10-05 | `20261005_02_sla_consumo_historico.py` | Histórico SLA consumido — amplía app.reclamos, crea sla_ingestas, servicio_sla_snapshot y v_eventos_sla |
| `20261014_01` | `20261005_02` | 2026-10-14 | `20261014_01_clientes_categoria.py` | Tablas app.clientes y app.clientes_alias, enum cliente_origen_categoria y categoría SLA/excepción en app.servicios (categoria pasa a nullable sin default) |
| `20261014_02` | `20261014_01` | 2026-10-14 | `20261014_02_fo_monitor.py` | Tablas app.fomon_* de FO Monitor (intervenciones, consultas a burritoIA, resultados append-only, geometría) |
| `20261016_01` | `20261014_02` | 2026-10-16 | `20261016_01_cromo_odf_nodo.py` | Habilita la ingesta de la clase 86 de Cromo (ODF Nodo) en app.cromo_odfs, agrega cromo_odf_conectores.patch_conector_n_id y corrige los pelo_n_id que no eran pelos. |
| `20261016_02` | `20261016_01` | 2026-10-16 | `20261016_02_cromo_tracking_cache_extremos.py` | Columna extremos en app.cromo_tracking_cache — los dos extremos de cada camino y su resumen (ODFs y cables), para clasificarlo como TRAMO o RESIDUAL sin volver a Cromo. |
| `20261016_03` | `20261016_02` | 2026-10-16 | `20261016_03_servicio_odf_confirmada.py` | Tabla app.servicio_odf_confirmada (ODF confirmadas por servicio, con rol EXTREMO o TRANSITO) y columna app.servicios.trackings_esperados (cantidad de trackings que declara el operador). |
| `20261016_04` | `20261016_03` | 2026-10-16 | `20261016_04_cromo_auditoria_huerfanos.py` | Tabla app.cromo_auditoria_huerfanos (pelos de caminos residuales con causa sugerida) y traza de origen (MANUAL / AUDITORIA) en app.cromo_servicio_pelo_excluido. |
| `20261017_01` | `20261016_04` | 2026-10-17 | `20261017_01_cromo_odf_fusion_conector.py` | Columna app.cromo_odf_conectores.fusion_odf_n_id (fusión de ODF clase 141 por la que el conector llega a su pelo o a otro conector). |
| `20261017_02` | `20261017_01` | 2026-10-17 | `20261017_02_cromo_inconsistencias.py` | Tablas app.cromo_inconsistencia (casos del detector de inconsistencias de Cromo) y app.cromo_inconsistencia_pelo (pelos en uso afectados por cada caso) |
| `20261017_03` | `20261017_02` | 2026-10-17 | `20261017_03_cromo_servicio_match_vigente.py` | Vista app.v_cromo_servicio_match_vigente — cromo_servicio_match sin los pelos de casos de inconsistencia de Cromo en CUARENTENA |
| `20261017_04` | `20261017_03` | 2026-10-17 | `20261017_04_config_cromo_inconsistencias.py` | Fila "Cromo Inconsistencias" en app.config_servicios (aviso de casos nuevos a Slack), inactiva y sin canales |
| `20261020_01` | `20261017_04` | 2026-10-20 | `20261020_01_cromo_arbitro.py` | Tablas del árbitro de Cromo (reglas, propuestas, evidencia de camino, evaluaciones) y origen AUTO en el override de ODF |
| `20261021_01` | `20261020_01` | 2026-10-21 | `20261021_01_servicio_posicion_vigente.py` | Tabla app.servicio_posicion_vigente (posición de ODF por conector que un operador declara como la vigente de un Servicio, con la foto del conector y el retiro automático o manual) |
| `20261023_01` | `20261021_01` | 2026-10-23 | `20261023_01_ingresos_anulacion_y_mover.py` | Baja lógica de app.ingresos (anulado_at/por/motivo), origen del movimiento en app.ingresos_correcciones y fin de sus FKs (ids históricos) |
| `20261027_01` | `20261023_01` | 2026-10-27 | `20261027_01_camaras_fontine_id_indice_duplicado.py` | Borra app.ix_camaras_fontine_id, índice UNIQUE duplicado exacto de la constraint camaras_fontine_id_key |
| `20261027_02` | `20261027_01` | 2026-10-27 | `20261027_02_normalizar_esquema_cadena_vs_dev.py` | Normaliza (idempotente) las 9 diferencias entre una base creada desde la cadena de migraciones y la base de dev: 6 nombres de índice, un DEFAULT y 2 comentarios |
<!-- tabla-migraciones:fin -->

**Notas que no entran en la tabla** (leídas de cada migración):

- `20260428_02` declara `Create Date: 2026-04-27`, anterior a su prefijo de revisión.
- `20260928_01`: el `downgrade()` aborta si ya hay filas `origen='web'` en `ingresos_correcciones`.
- `20260929_03`: el `downgrade()` borra los cables de clases 52/59/60 con sus tubos, pelos y matches.
- `20261005_02`: el `UPDATE app.reclamos SET horas_netas = horas_netas / 60.0` corre **después** del
  `alter_column` a `Numeric(12,4)` (fix del 2026-10-14; antes redondeaba a 2 decimales). Test:
  `tests/test_sla_consumo_migracion_orden.py`.
- `20261014_01`: el `downgrade()` devuelve `servicios.categoria` NULL a 6 (con pérdida).
- `20261014_02`: el `downgrade()` borra todas las tablas `fomon_*` y la fila `fo_monitor` de
  `config_servicios`.
- `20261016_01`: el `downgrade()` borra las filas `ODF_NODO` de `cromo_odfs` y sus conectores; el
  backfill de `pelo_n_id` no se revierte.
- `20261023_01`: el `downgrade()` recrea las FKs `ON DELETE SET NULL` de `ingresos_correcciones` y
  aborta si hay ingresos anulados, correcciones con origen o ids huérfanos.

---

### Tabla `camara_alias`

| Columna        | Tipo                | Descripción |
|----------------|---------------------|-------------|
| `id`           | Integer (PK)        | ID autoincremental. |
| `camara_id`    | Integer (FK)        | Referencia a `app.camaras.id` — `ON DELETE CASCADE`. |
| `alias_nombre` | String(255), index  | Nombre alternativo de la cámara. |
| `created_at`   | DateTime(tz)        | Fecha de creación del alias. |

**Uso:** el listener de ingresos y `core/services/camara_busqueda_nombre.py` utilizan esta tabla para empatar
cámaras escritas con nomenclatura alternativa. Un administrador puede registrar aliases
desde el panel `/admin/Servicios/Baneos` → pestaña Revisión → sección *Cámaras Pendientes de Revisión* mediante dos flujos:
- **Convertir en Alias** — vincula el nombre del técnico como alias de una cámara ya existente.
- **Definir Nombre Canón** — crea la cámara con su nombre oficial (`LIBRE`) y guarda automáticamente el nombre original del técnico como alias de la nueva cámara.

Tercer escritor (2026-08-24): `core/services/camara_ingest_service.py::asociar_nombres_a_camara` —
la asociación manual del Revisor Manual de la ingesta Excel de cámaras (`/admin/ingesta/camaras`),
que crea un alias por cada nombre sin match resuelto a mano hacia una Cámara/Botella existente. Esta
tabla **no tiene unique constraint** en `alias_nombre` (sólo `index=True`, ver `db/models/infra.py`) —
la idempotencia de la asociación manual es puramente aplicativa (check-then-insert dentro de la misma
transacción: si ya existe un alias con ese texto se lo reusa como no-op en vez de duplicarlo), no
garantizada por la base.
