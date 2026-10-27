#!/usr/bin/env bash
# Nombre de archivo: check_drift_desde_cero.sh
# Ubicación de archivo: scripts/check_drift_desde_cero.sh
# Descripción: Levanta un Postgres efímero, aplica db/init.sql + toda la cadena Alembic y exige drift 0 contra los modelos (local; no corre en GitHub)

# Complementa a `scripts/check_drift_modelos.py` contra dev: dev no salió sólo de las migraciones,
# así que el chequeo contra dev no prueba que una base nueva quede igual a los modelos. Éste sí.
# No usa el stack compose ni sus volúmenes: el contenedor vive en tmpfs, con labels de efímero, y
# se borra al salir (incluso con error o Ctrl-C). Pesa lo que la imagen de Postgres del compose,
# que ya está en el host. Por decisión del usuario (2026-10-27) no se agrega a .github/workflows:
# los minutos de Actions se reservan.
#
# Uso: scripts/check_drift_desde_cero.sh [--detalle]
# Salida: la de check_drift_modelos.py (0 sin drift, 1 con drift, 2 sin conexión); 3 si falló la
# migración.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

IMAGEN="$(awk '/image: postgres:/ {print $2; exit}' deploy/docker-compose.dev.yml)"
NOMBRE="lasfocas-drift-desde-cero-$$"
CLAVE="drift_$$_$RANDOM"
PUERTO="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
PYTHON="${PYTHON:-python}"
[[ -x .venv/bin/python ]] && PYTHON=".venv/bin/python"

limpiar() { docker rm -f "$NOMBRE" >/dev/null 2>&1 || true; }
trap limpiar EXIT

echo "Postgres efímero ($IMAGEN) en 127.0.0.1:$PUERTO..."
docker run -d --rm --name "$NOMBRE" \
  --label lasfocas.lifecycle=ephemeral --label lasfocas.session=check-drift-desde-cero \
  --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_USER=drift -e POSTGRES_PASSWORD="$CLAVE" -e POSTGRES_DB=focas_test \
  -p "127.0.0.1:$PUERTO:5432" \
  -v "$ROOT_DIR/db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro" \
  "$IMAGEN" >/dev/null

# pg_isready contra 127.0.0.1 evita el falso "listo" del servidor temporal que usa el entrypoint
# mientras corre init.sql (escucha sólo por socket).
for _ in $(seq 1 60); do
  docker exec "$NOMBRE" pg_isready -U drift -d focas_test -h 127.0.0.1 >/dev/null 2>&1 && break
  sleep 1
done

echo "alembic upgrade head desde cero..."
if ! env -u DATABASE_URL ALEMBIC_URL="postgresql+psycopg://drift:$CLAVE@127.0.0.1:$PUERTO/focas_test" \
  "$PYTHON" -m alembic -c db/alembic.ini upgrade head >/dev/null 2>&1; then
  echo "ERROR: la cadena de migraciones no aplica sobre una base vacía" >&2
  env -u DATABASE_URL ALEMBIC_URL="postgresql+psycopg://drift:$CLAVE@127.0.0.1:$PUERTO/focas_test" \
    "$PYTHON" -m alembic -c db/alembic.ini upgrade head 2>&1 | tail -20 >&2 || true
  exit 3
fi

set +e
env -u DATABASE_URL -u ALEMBIC_URL \
  POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$PUERTO" POSTGRES_DB=focas_test POSTGRES_USER=drift \
  POSTGRES_PASSWORD="$CLAVE" "$PYTHON" scripts/check_drift_modelos.py "$@"
codigo=$?
set -e
exit "$codigo"
