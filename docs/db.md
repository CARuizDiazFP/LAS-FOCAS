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
	- `camaras`: referencia única `fontine_id`, coordenadas opcionales, estado `LIBRE|OCUPADA|BANEADA` y `last_update`.
	- `cables`: enlaces opcionales entre cámaras (`origen_camara_id`, `destino_camara_id`).
	- `empalmes`: identificador de tracking (`tracking_empalme_id`), FK a cámara y tipo.
	- `servicios`: cliente, categoría y `raw_tracking_data` (JSON) para conservar trazas crudas.
	- `servicio_empalme_association`: tabla intermedia N-a-N entre servicios y empalmes.
	- `ingresos`: vínculo de técnicos a cámaras con `fecha_inicio`/`fecha_fin`.
- Relaciones expuestas: `Camara.empalmes`, `Camara.ingresos`, `Servicio.empalmes` y `Empalme.servicios` permiten navegar las rutas y trazas importadas desde TXT/Sheet.
- Servicio de sincronización: `core/services/infra_sync.py` toma la hoja Google "Camaras" (configurada via `INFRA_SHEET_ID`/`INFRA_SHEET_NAME`) y hace upsert contra `app.camaras` respetando `fontine_id`, actualizando coordenadas y estado; exige `Keys/credentials.json` o `GOOGLE_CREDENTIALS_JSON` con el Service Account.
