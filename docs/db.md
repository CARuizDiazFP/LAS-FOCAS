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
| `estado`           | Enum                 | `LIBRE`, `OCUPADA`, `BANEADA`, `DETECTADA`, `PENDIENTE_REVISION`. |
| `origen_datos`     | Enum                 | `MANUAL`, `TRACKING`, `SHEET`, `INFERIDO`. |
| `camara_padre_id`  | FK → camaras, index, nullable | Jerarquía Cámara→Botella (2026-08-10): si está seteado, esta fila es una **Botella** y apunta a su Cámara padre (`camara_padre_id IS NULL`). Exactamente 2 niveles — `CHECK` anti-autoreferencia. Ver `docs/infra.md` sección "Jerarquía Cámara → Botellas". |
| `last_update`      | DateTime(tz)         | Última actualización. |

**Estados:**
- `LIBRE`: cámara disponible para nuevos servicios.
- `OCUPADA`: cámara en uso.
- `BANEADA`: cámara excluida de operaciones.
- `DETECTADA`: cámara creada automáticamente desde tracking (pendiente de validación).
- `PENDIENTE_REVISION`: cámara auto-registrada por el listener de ingresos Slack al recibir una cámara desconocida.  Requiere que un administrador la apruebe (estado → `LIBRE`) o la convierta en alias de otra cámara existente.

**Origen de datos:**
- `MANUAL`: ingresada manualmente.
- `TRACKING`: detectada al procesar un archivo de tracking.
- `SHEET`: importada desde Google Sheets.
- `INFERIDO`: Cámara padre sintetizada automáticamente al agrupar Botellas (backfill o alta en vivo vía `resolver_o_crear_padre`) — no proviene de ningún origen de datos real, es un artefacto de la jerarquía.

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
| `servicio_id`         | String(64), unique | ID del servicio (ej: "111995"). |
| `numero_primer_servicio` | String(64), unique, index | ID lógico padre usado por ingesta SLA. |
| `nombre_cliente`      | String(255)    | Nombre del cliente en origen SLA. |
| `numero_linea`        | String(128), index | Línea asociada al servicio. |
| `tipo_servicio`       | String(128), index | Tipo comercial/técnico del servicio. |
| `sla_prometido`       | String(128)    | SLA comprometido en el origen. |
| `direccion`           | String(255)    | Dirección principal del servicio. |
| `localidad`           | String(128)    | Localidad del servicio. |
| `provincia`           | String(128)    | Provincia del servicio. |
| `direccion_2`         | String(255)    | Dirección complementaria. |
| `estado_servicio`     | String(128), index | Estado actual informado en ingesta SLA. |
| `cliente`             | String(255)    | Nombre del cliente (opcional). |
| `categoria`           | Integer        | Categoría del servicio (opcional). |
| `nombre_archivo_origen`| String(255)   | Nombre del archivo de tracking original. |
| `raw_tracking_data`   | JSON           | Datos crudos del tracking parseado. |

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

| Columna       | Tipo           | Descripción |
|---------------|----------------|-------------|
| `id`          | Integer (PK)   | ID autoincremental. |
| `camara_id`   | FK → camaras   | Cámara de ingreso. |
| `tecnico_id`  | String(128)    | ID del técnico. |
| `fecha_inicio`| DateTime(tz)   | Fecha/hora de inicio. |
| `fecha_fin`   | DateTime(tz)   | Fecha/hora de fin. |

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
- **Restauración inteligente:** al levantar un baneo, cada cámara del grupo se evalúa por separado — vuelve a `LIBRE` u `OCUPADA` según ingresos activos, preserva `DETECTADA` si ese era su estado antes de ser baneada, y se mantiene en `BANEADA` si la última transición a ese estado es anterior al inicio del incidente que se levanta (baneo independiente sin `IncidenteBaneo` que lo respalde — override manual o heredado del backfill de jerarquía). Ver `core/services/protection_service.py::_determinar_estado_restauracion` y `camara_estado_service.obtener_ultima_transicion_a_baneada`.
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
- **Tracking** (`/api/infra/upload_tracking`): procesa archivos TXT de tracking, crea servicios, detecta cámaras nuevas y registra empalmes.

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

Índices: parcial en `id_legacy` (`WHERE id_legacy IS NOT NULL`), compuesto `(latitud, longitud)`, y GIN
funcional `to_tsvector('spanish', nombre)` para búsqueda de texto.

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
desde el panel `/admin/Servicios/Baneos` → sección *Cámaras Pendientes de Revisión* mediante dos flujos:
- **Convertir en Alias** — vincula el nombre del técnico como alias de una cámara ya existente.
- **Definir Nombre Canón** — crea la cámara con su nombre oficial (`LIBRE`) y guarda automáticamente el nombre original del técnico como alias de la nueva cámara.
