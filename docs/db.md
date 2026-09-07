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
| `categoria`           | Integer, `NOT NULL DEFAULT 6`, `CHECK BETWEEN 0 AND 6` | **Nivel Cliente del Excel SLA** ("C0" a "C6", columna "Nivel Cliente"), repurpuesto desde 2026-08-26 — antes era una prioridad de reporting manual sin relación con el Excel. Se alimenta en cada `POST /servicios/ingest` (validado contra el mismo rango 0-6 antes del upsert; un valor fuera de rango degrada al valor previo y queda loggeado, no tumba la ingesta) y sigue siendo editable a mano vía `PATCH /servicios/{id}/categoria`/`PATCH /servicios/bulk-categoria` — una edición manual queda pisada por la próxima ingesta real, comportamiento aceptado explícitamente (no tiene mecanismo de override como `es_verificable_override`). Los valores legacy (0 = placeholder Cromo, 6 = sin categorizar) se dejan como están hasta que llegue un Excel real para esa fila — sin backfill retroactivo. El filtro default del listado (`ServiciosView.vue`) es "sin filtro" (antes `categoria=6`), para no ocultar filas tras la primera ingesta real. |
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

### Tabla `servicio_empalme_association` (Legacy)

Tabla intermedia N-a-N entre `servicios` y `empalmes`. Mantenida por retrocompatibilidad.
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
| `hash_contenido`      | String(64)          | SHA256 del contenido normalizado del tracking. |
| `activa`              | Boolean             | Si la ruta está activa (true por defecto). |
| `nombre_archivo_origen`| String(255)        | Nombre del archivo de tracking original. |
| `contenido_original`  | Text                | Contenido raw del tracking para debugging. |
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

### Relaciones del modelo de rutas

- `Servicio.rutas`: Lista de rutas del servicio (1-a-N).
- `RutaServicio.servicio`: Servicio al que pertenece (N-a-1).
- `RutaServicio.empalmes`: Empalmes de la ruta en orden (N-a-N).
- `Empalme.rutas`: Rutas que pasan por el empalme (N-a-N).

### Propiedades helper en Servicio

- `servicio.ruta_principal`: Retorna la ruta de tipo PRINCIPAL activa (o None).
- `servicio.rutas_activas`: Lista de rutas activas del servicio.
- `servicio.todos_los_empalmes`: Set único de todos los empalmes de todas las rutas.

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

### Tabla `ingresos_sin_match` (2026-08-11)

Reemplaza el auto-registro `PENDIENTE_REVISION` en ingresos sin match (ver `docs/infra.md`, sección
homónima) — no crea ninguna `Camara`, es sólo información de sólo lectura para revisión manual y
mejora del regex de búsqueda. Poblada por `modules/slack_baneo_notifier/listener.py` (bot de Slack),
`web/app/main.py::upload_tracking_web` (carga de tracking) y, desde 2026-08-24,
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
| `entidad` | Text | `BOTELLA` \| `CABLE` \| `TUBO` \| `PELO` \| `FUSION` \| `ODF` \| `PARCELA`. |
| `ingerible` | Boolean | Si la ingesta debe traer objetos de esta clase. |
| `homologada` | Boolean | `false` para clases estructuralmente válidas pero sin homologar (ej. clase 124, `code: "NO-SABE"`). |
| `motivo_exclusion` | Text | Motivo si `ingerible = false` (ej. clase 120, parcela catastral). |
| `count_cromo` | BigInteger | Último count observado en Cromo (`stats[].count`), referencial. |
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
| `params` | JSONB | Clases, `psize`, `max_paginas`, `show` de la corrida. |
| `total_objetivo`, `leidas`, `creadas`, `actualizadas`, `sin_cambios`, `errores`, `refs_colgadas` | Integer | Contadores en vivo. |
| `iniciada_at`, `finalizada_at` | DateTime(tz) | — |

### Tabla `cromo_ingesta_eventos`

Evento puntual por objeto dentro de una corrida. `corrida_id → cromo_ingesta_corridas.id` (`ON DELETE CASCADE`).

| Columna | Tipo | Descripción |
|---|---|---|
| `id` (PK) | BigInteger | — |
| `corrida_id` (FK) | BigInteger | — |
| `n_id`, `clase` | BigInteger, SmallInteger | Identifica el objeto de Cromo afectado. |
| `accion` | String(32) | `CREADA` \| `ACTUALIZADA` \| `SIN_CAMBIOS` \| `ERROR` \| `REF_COLGADA`. |
| `detalle` | Text | Mensaje libre. |
| `created_at` | DateTime(tz) | — |

Índice: `(corrida_id, id)`.

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
`web/app/main.py` (`GET`/`POST /api/admin/ingesta/cromo/config`, panel admin).

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

## Extensiones PostgreSQL requeridas

| Extensión | Motivo |
|-----------|---------|
| `unaccent` | Normalización de acentos en búsquedas ILIKE de cámaras (`camara_search._buscar_ilike`, `_buscar_tokens`). Se instala via migración `20260427_01`. |

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

## Historial de migraciones

| Revisión | Archivo | Descripción |
|----------|---------|-------------|
| `20260127_01` | `20260127_01_incidente_baneo_email_fields.py` | Campos de email en incidentes de baneo |
| `20260417_01` | `20260417_01_config_servicios.py` | Tabla `app.config_servicios` para worker Slack |
| `20260420_01` | `20260420_01_camaras_estado_auditoria.py` | Tabla `app.camaras_estado_auditoria` + enum `camara_estado` |
| `20260423_01` | `20260423_01_config_servicios_hora_inicio.py` | Columna `hora_inicio` en `app.config_servicios` |
| `20260427_01` | `20260427_01_unaccent_extension.py` | Extensión `unaccent` para búsquedas sin acento |
| `20260428_01` | `20260428_01_listener_workflow_ids.py` | Columnas `workflow_ids` y `solo_workflows` en `app.config_servicios` |
| `20260428_02` | `20260428_02_camara_alias_pendiente.py` | Tabla `app.camara_alias` + valor `PENDIENTE_REVISION` en enum `camara_estado` |
| `20260805_01` | `20260805_01_cromo_ingesta.py` | Tablas `app.cromo_*` (catálogo + auditoría + inventario) y enum `cromo_tipo_asociacion_pelo`, para la Etapa 2 de ingesta desde Cromo Red |
| `20260806_01` | `20260806_01_cromo_ingesta_config.py` | Tabla `app.cromo_ingesta_config` (fila única, config del scheduler del worker dedicado), para la Etapa 7 de ingesta desde Cromo Red |
| `20260807_01` | `20260807_01_cromo_fusiones_botella_nullable.py` | `cromo_fusiones.botella_n_id` pasa a nullable — el fetch directo de clase 132 no trae `parent`, para la Etapa 8 de ingesta desde Cromo Red |
| `20260810_01` | `20260810_01_camara_padre_botella.py` | Columna `camaras.camara_padre_id` (FK auto-referencial + índice + `CHECK` anti-autoreferencia) y valor `INFERIDO` en enum `camara_origen_datos`, para la jerarquía Cámara→Botella (ver `docs/infra.md`) |
| `20260811_01` | `20260811_01_cromo_botella_camara_padre.py` | Columnas `cromo_botellas.camara_id` (FK a `camaras.id`) y `estado` (+ `CHECK`), valores `NO_OPERATIVA` en `camara_estado` e `INFERIDO_CROMO` en `camara_origen_datos` — vincula Botellas Cromo a una Cámara padre propia (ver `docs/infra.md`, sección "Cámara padre para Botellas Cromo") |
| `20260811_02` | `20260811_02_ingresos_sin_match.py` | Tabla `app.ingresos_sin_match` — reemplaza el auto-registro `PENDIENTE_REVISION` en ingresos sin match (ver `docs/infra.md`, sección homónima) |
| `20260813_01` | `20260813_01_cromo_botella_default_libre.py` | `ALTER COLUMN cromo_botellas.estado SET DEFAULT 'LIBRE'` (antes `'NO_OPERATIVA'`) — reversión de la política fail-closed del `20260811_01`, metadata-only (ver `docs/decisiones.md`) |
| `20260814_01` | `20260814_01_servicios_categoria_check.py` | Backfill `servicios.categoria` NULL→6, luego `SET DEFAULT 6` + `SET NOT NULL` + `CHECK ck_servicios_categoria_valida (categoria BETWEEN 0 AND 6)` — la columna ya existía sin restricciones, 100% NULL (ver `docs/decisiones.md`) |
| `20260814_02` | `20260814_02_servicios_origen_datos.py` | Enum `app.servicio_origen_datos` (`MANUAL`/`TRACKING`/`INGEST_EXCEL`/`INFERIDO_CROMO`) + columna `servicios.origen_datos NOT NULL DEFAULT 'MANUAL'`, mismo patrón que `camara_origen_datos` |
| `20260819_01` | `20260819_01_cromo_botella_alias.py` | Tabla `app.cromo_botella_alias` — escudo manual de aliasing para botellas duplicadas/basura (ver sección "Tabla `cromo_botella_alias`" arriba) |
| `20260821_01` | `20260821_01_cromo_botella_nombre_editado_manual.py` | Columna `cromo_botellas.nombre_editado_manual BOOLEAN NOT NULL DEFAULT false` — protege un nombre corregido a mano (Verificador Cromo) de que una corrida futura lo pise (ver sección "Repoblación de cables con historial 'ID dual'" arriba) |
| `20260822_01` | `20260822_01_cromo_botella_separada_manualmente.py` | Columnas de auditoría `cromo_botellas.separada_manualmente/separada_motivo/separada_por/separada_at` — separación manual de Botella agrupada erróneamente por nombre bajo una Cámara padre compartida |
| `20260825_02` | `20260825_02_servicios_verificable.py` | Columnas `servicios.es_verificable BOOLEAN NOT NULL` (backfill por `tipo_servicio` sobre las filas existentes) y `servicios.es_verificable_override BOOLEAN` nullable — trazabilidad de IDs y verificabilidad de Servicios SLA (ver sección "Tabla `servicios`" arriba y `docs/decisiones.md`) |

---

### Tabla `camara_alias`

| Columna        | Tipo                | Descripción |
|----------------|---------------------|-------------|
| `id`           | Integer (PK)        | ID autoincremental. |
| `camara_id`    | Integer (FK)        | Referencia a `app.camaras.id` — `ON DELETE CASCADE`. |
| `alias_nombre` | String(255), index  | Nombre alternativo de la cámara. |
| `created_at`   | DateTime(tz)        | Fecha de creación del alias. |

**Uso:** el listener de ingresos y `camara_search.py` utilizan esta tabla para empatar
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
