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
  Se lee desde la variable de entorno o el archivo `/run/secrets/postgres_password`.

En `deploy/compose.yml` la base de datos solo se expone a otros contenedores mediante `expose: 5432`, evitando publicar el puerto en el host.

La función `db_health` ejecuta una consulta simple `SELECT 1` y obtiene la versión del servidor
para verificar el estado de la base de datos.

Se limpiaron imports innecesarios en los repositorios de conversaciones y mensajes para mantener el código conforme a PEP8.

## Usuarios de la base

El script `db/init.sql` define dos roles diferenciados:

- `lasfocas_app`: usuario de aplicación con privilegios `SELECT`, `INSERT`, `UPDATE` y `DELETE` sobre el esquema `app`.
- `lasfocas_readonly`: usuario con acceso exclusivo de lectura para consultas y dashboards.

Ambos usuarios solo pueden conectarse a la base `lasfocas` y se revocan los permisos predeterminados a `PUBLIC` para aplicar el principio de mínimo privilegio.

## Tabla api_keys

Esta tabla almacena las claves de acceso utilizadas por la API.
Campos:
- `id`: identificador interno.
- `api_key`: clave única para autenticar y aplicar rate limiting.
- `created_at`: fecha de creación.

## Migraciones con Alembic

Las migraciones del esquema se gestionan con **Alembic**. La configuración principal se encuentra en `alembic.ini` y los scripts se almacenan en `db/migrations`.

Pasos básicos para trabajar con migraciones:

1. Generar una revisión: `alembic revision -m "descripcion"`.
2. Editar el archivo creado en `db/migrations/versions/` agregando el encabezado requerido y las operaciones deseadas.
3. Aplicar los cambios: `alembic upgrade head`.

La revisión inicial ejecuta el contenido de `db/init.sql`, creando el esquema `app` y los usuarios de aplicación y solo lectura.
