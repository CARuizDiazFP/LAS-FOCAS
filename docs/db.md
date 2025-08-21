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

En `deploy/compose.yml` la base de datos solo se expone a otros contenedores mediante `expose: 5432`, evitando publicar el puerto en el host.

La función `db_health` ejecuta una consulta simple `SELECT 1` y obtiene la versión del servidor
para verificar el estado de la base de datos.

Se limpiaron imports innecesarios en los repositorios de conversaciones y mensajes para mantener el código conforme a PEP8.

## Usuario de solo lectura

El script `db/init.sql` crea el usuario `lasfocas_readonly` con permisos restringidos:

- Conexión únicamente a la base `lasfocas`.
- Acceso `SELECT` sobre todas las tablas del esquema `app`.

Este usuario permite realizar consultas y dashboards sin riesgo de modificación de datos.
