# Nombre de archivo: db.md
# Ubicación de archivo: docs/db.md
# Descripción: Documentación del módulo de conexión a PostgreSQL

El módulo `api/app/db.py` establece una conexión a PostgreSQL utilizando SQLAlchemy y Psycopg 3.
La cadena DSN se construye a partir de variables de entorno:

- `POSTGRES_HOST`: dirección del servidor de base de datos.
- `POSTGRES_PORT`: puerto del servicio.
- `POSTGRES_DB`: nombre de la base de datos.
- `POSTGRES_USER`: usuario para la conexión.
- `POSTGRES_PASSWORD`: contraseña del usuario.

La función `db_health` ejecuta una consulta simple `SELECT 1` y obtiene la versión del servidor
para verificar el estado de la base de datos.

Se limpiaron imports innecesarios en los repositorios de conversaciones y mensajes para mantener el código conforme a PEP8.

## Infraestructura (cámaras, cables y servicios)

- Base común: `db/base.py` expone `Base = declarative_base()` para todos los modelos.
- Nuevas tablas en esquema `app` definidas en `db/models/infra.py`:

### Tabla `camaras`

| Columna       | Tipo                 | Descripción |
|---------------|----------------------|-------------|
| `id`          | Integer (PK)         | ID autoincremental. |
| `fontine_id`  | String(64), unique   | Referencia externa (opcional si se crea desde tracking). |
| `nombre`      | String(255), index   | Nombre/dirección de la cámara (requerido). |
| `latitud`     | Float                | Coordenada latitud (opcional). |
| `longitud`    | Float                | Coordenada longitud (opcional). |
| `direccion`   | String(255)          | Dirección alternativa (opcional). |
| `estado`      | Enum                 | `LIBRE`, `OCUPADA`, `BANEADA`, `DETECTADA`. |
| `origen_datos`| Enum                 | `MANUAL`, `TRACKING`, `SHEET`. |
| `last_update` | DateTime(tz)         | Última actualización. |

**Estados:**
- `LIBRE`: cámara disponible para nuevos servicios.
- `OCUPADA`: cámara en uso.
- `BANEADA`: cámara excluida de operaciones.
- `DETECTADA`: cámara creada automáticamente desde tracking (pendiente de validación).

**Origen de datos:**
- `MANUAL`: ingresada manualmente.
- `TRACKING`: detectada al procesar un archivo de tracking.
- `SHEET`: importada desde Google Sheets.

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
- **Restauración inteligente:** Al levantar baneo, las cámaras vuelven a `LIBRE` u `OCUPADA` según ingresos activos.
- **Cámaras nuevas:** Si se carga un tracking de un servicio baneado, las cámaras nuevas nacen `BANEADAS`.

### Relaciones

- `Camara.empalmes`: lista de empalmes ubicados en la cámara.
- `Camara.ingresos`: historial de ingresos de técnicos.
- `Camara.cables_origen` / `Camara.cables_destino`: cables conectados.
- `Servicio.empalmes`: empalmes por los que pasa el servicio (N-a-N).
- `Empalme.servicios`: servicios que pasan por el empalme (N-a-N).
- `Empalme.camara`: cámara donde se ubica el empalme.

### Servicios de sincronización

- **Google Sheets** (`/sync/camaras`): `core/services/infra_sync.py` sincroniza desde la hoja "Camaras" configurada vía `INFRA_SHEET_ID`/`INFRA_SHEET_NAME`, actualizando `fontine_id`, coordenadas y estado.
- **Tracking** (`/api/infra/upload_tracking`): procesa archivos TXT de tracking, crea servicios, detecta cámaras nuevas y registra empalmes.

## Migraciones y despliegue

- Ejecutar migraciones con Alembic apuntando al archivo `db/alembic.ini`. Ejemplo local (fuera de Docker Compose):
	```bash
	source .venv/bin/activate
	export ALEMBIC_URL="postgresql+psycopg://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:$POSTGRES_PORT/$POSTGRES_DB"
	alembic -c db/alembic.ini upgrade head
	```
- El enum `app.camara_estado` se crea sólo si no existe (`create_type=False` + `checkfirst=True`), lo que permite reintentos sin tener que limpiar tipos manualmente.
- En entornos dockerizados, reemplazar `localhost` por el hostname del contenedor (`postgres`) y dejar que Compose gestione las credenciales.
