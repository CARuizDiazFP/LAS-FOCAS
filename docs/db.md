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

### Tabla `servicio_empalme_association`

Tabla intermedia N-a-N entre `servicios` y `empalmes`:

| Columna      | Tipo         | Descripción |
|--------------|--------------|-------------|
| `servicio_id`| FK → servicios (PK) | ID del servicio. |
| `empalme_id` | FK → empalmes (PK)  | ID del empalme. |

### Tabla `ingresos`

| Columna       | Tipo           | Descripción |
|---------------|----------------|-------------|
| `id`          | Integer (PK)   | ID autoincremental. |
| `camara_id`   | FK → camaras   | Cámara de ingreso. |
| `tecnico_id`  | String(128)    | ID del técnico. |
| `fecha_inicio`| DateTime(tz)   | Fecha/hora de inicio. |
| `fecha_fin`   | DateTime(tz)   | Fecha/hora de fin. |

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
