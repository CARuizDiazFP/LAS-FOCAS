# Nombre de archivo: init_users.sh
# Ubicación de archivo: db/init_users.sh
# Descripción: Crea usuarios de aplicación y solo lectura usando contraseñas de secrets
#!/bin/bash
set -e

APP_PASS=$(cat "$POSTGRES_APP_PASSWORD_FILE")
READONLY_PASS=$(cat "$POSTGRES_READONLY_PASSWORD_FILE")

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Usuario de aplicación con privilegios mínimos
    CREATE USER lasfocas_app WITH ENCRYPTED PASSWORD '${APP_PASS}';
    REVOKE ALL PRIVILEGES ON DATABASE $POSTGRES_DB FROM PUBLIC;
    REVOKE ALL ON SCHEMA app FROM PUBLIC;
    GRANT CONNECT ON DATABASE $POSTGRES_DB TO lasfocas_app;
    GRANT USAGE ON SCHEMA app TO lasfocas_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO lasfocas_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO lasfocas_app;

    -- Usuario de solo lectura para consultas
    CREATE USER lasfocas_readonly WITH ENCRYPTED PASSWORD '${READONLY_PASS}';
    REVOKE ALL PRIVILEGES ON DATABASE $POSTGRES_DB FROM lasfocas_readonly;
    GRANT CONNECT ON DATABASE $POSTGRES_DB TO lasfocas_readonly;
    GRANT USAGE ON SCHEMA app TO lasfocas_readonly;
    GRANT SELECT ON ALL TABLES IN SCHEMA app TO lasfocas_readonly;
    ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT ON TABLES TO lasfocas_readonly;
EOSQL
