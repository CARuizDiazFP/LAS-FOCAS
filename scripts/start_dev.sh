#!/usr/bin/env bash
# Nombre de archivo: start_dev.sh
# Ubicación de archivo: scripts/start_dev.sh
# Descripción: Script para levantar el entorno de DESARROLLO (Dev) de LAS-FOCAS en puertos alternativos.
# Uso: ./scripts/start_dev.sh [--clone-db] [--no-build] [--down] [-h]

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_COMPOSE_FILE="$ROOT_DIR/deploy/docker-compose.dev.yml"
ENV_DEV_FILE="$ROOT_DIR/.env.dev"
COMPOSE_DEV=(docker compose -f "$DEV_COMPOSE_FILE" --env-file "$ENV_DEV_FILE")

SERVICES=(postgres nlp_intent api web office slack_baneo_worker)

CLONE_DB=false
NO_BUILD=false
DO_DOWN=false

usage() {
  cat <<EOF
Uso: ./scripts/start_dev.sh [opciones]

Opciones:
  --clone-db    Clona la base de datos de producción a focas_dev antes de levantar
  --no-build    No rebuildenar imágenes (usa caché existente)
  --down        Detiene el stack dev antes de levantar (útil para reinicio limpio)
  -h, --help    Muestra esta ayuda

Ejemplos:
  ./scripts/start_dev.sh                  Levanta el stack dev (con build)
  ./scripts/start_dev.sh --clone-db       Clona DB prod → dev y levanta
  ./scripts/start_dev.sh --no-build       Levanta sin rebuildar imágenes
  ./scripts/start_dev.sh --down           Detiene y vuelve a levantar el stack dev

Acceso al panel:  http://localhost:8090
API docs:         http://localhost:8011/docs
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clone-db) CLONE_DB=true ;;
    --no-build) NO_BUILD=true ;;
    --down)     DO_DOWN=true ;;
    -h|--help)  usage; exit 0 ;;
    *) echo -e "${RED}Opción desconocida: $1${NC}"; usage; exit 1 ;;
  esac
  shift
done

echo -e "${GREEN}=== LAS-FOCAS :: Start DEV ===${NC}"

########################################
# 1) Verificaciones previas            #
########################################
command -v docker >/dev/null 2>&1 || { echo -e "${RED}Docker no está instalado.${NC}"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo -e "${RED}Plugin 'docker compose' (v2) no encontrado.${NC}"; exit 1; }

if [ ! -f "$ENV_DEV_FILE" ]; then
  echo -e "${YELLOW}No existe .env.dev en la raíz. Creando desde deploy/env.dev.sample...${NC}"
  cp "$ROOT_DIR/deploy/env.dev.sample" "$ENV_DEV_FILE"
  echo -e "${YELLOW}IMPORTANTE: Completá las credenciales en .env.dev (especialmente SLACK_BOT_TOKEN y SLACK_APP_TOKEN) antes de continuar.${NC}"
fi

# Crear directorio de logs dev si no existe
mkdir -p "$ROOT_DIR/Logs/dev"

########################################
# 2) Down opcional                      #
########################################
if $DO_DOWN; then
  echo -e "${GREEN}Deteniendo stack dev anterior...${NC}"
  "${COMPOSE_DEV[@]}" down --remove-orphans || true
fi

########################################
# 2.5) Imagen base focas-base           #
########################################
echo -e "${GREEN}Verificando/construyendo imagen base focas-base...${NC}"
"$ROOT_DIR/scripts/build_base.sh"

########################################
# 3) Build & Up                         #
########################################
if $NO_BUILD; then
  echo -e "${GREEN}Levantando servicios dev (sin rebuild)...${NC}"
  "${COMPOSE_DEV[@]}" up -d "${SERVICES[@]}"
else
  echo -e "${GREEN}Levantando servicios dev (con build)...${NC}"
  "${COMPOSE_DEV[@]}" up -d --build "${SERVICES[@]}"
fi

########################################
# 4) Espera Postgres healthy            #
########################################
echo -e "${GREEN}Esperando que Postgres dev esté listo...${NC}"
MAX_TRIES=40
DELAY=3
for i in $(seq 1 $MAX_TRIES); do
  status=$(docker inspect -f '{{.State.Health.Status}}' lasfocasdev-postgres 2>/dev/null || echo "unknown")
  if [ "$status" = "healthy" ]; then
    echo -e "${GREEN}Postgres dev healthy.${NC}"
    break
  fi
  echo -e "${YELLOW}Esperando Postgres dev (estado: $status) $i/$MAX_TRIES...${NC}"
  sleep $DELAY
done

########################################
# 4.5) Clonar DB prod → dev (opcional)  #
########################################
if $CLONE_DB; then
  echo -e "${YELLOW}=== Clonando DB prod → dev ===${NC}"

  PROD_CONTAINER="lasfocas-postgres"
  DEV_CONTAINER="lasfocasdev-postgres"

  if ! docker ps --format '{{.Names}}' | grep -q "^${PROD_CONTAINER}$"; then
    echo -e "${RED}ERROR: El contenedor prod '${PROD_CONTAINER}' no está corriendo. Abortando clone.${NC}"
    exit 1
  fi

  # Leer credenciales prod desde .env (sin exportar para no contaminar el entorno)
  set +u
  PROD_USER=$(grep -E '^POSTGRES_USER=' "$ROOT_DIR/.env" | cut -d= -f2- | tr -d '"' || echo "FOCALBOT")
  PROD_DB_NAME=$(grep -E '^POSTGRES_DB=' "$ROOT_DIR/.env" | cut -d= -f2- | tr -d '"' || echo "FOCALDB")
  # Leer credenciales dev desde .env.dev
  DEV_USER=$(grep -E '^POSTGRES_USER=' "$ENV_DEV_FILE" | cut -d= -f2- | tr -d '"' || echo "FOCALBOT")
  DEV_DB=$(grep -E '^POSTGRES_DB=' "$ENV_DEV_FILE" | cut -d= -f2- | tr -d '"' || echo "focas_dev")
  DEV_PASS=$(grep -E '^POSTGRES_PASSWORD=' "$ENV_DEV_FILE" | cut -d= -f2- | tr -d '"' || echo "LASFOCAS_DEV_2026!")
  set -u

  echo -e "${GREEN}pg_dump '${PROD_DB_NAME}' (prod) | pg_restore '${DEV_DB}' (dev)...${NC}"
  docker exec "$PROD_CONTAINER" \
    pg_dump -U "$PROD_USER" -d "$PROD_DB_NAME" -F c --no-owner --no-acl \
  | docker exec -i "$DEV_CONTAINER" \
    sh -c "PGPASSWORD='${DEV_PASS}' pg_restore -U '${DEV_USER}' -d '${DEV_DB}' --clean --if-exists --no-owner --no-acl" \
  && echo -e "${GREEN}Clone completado exitosamente.${NC}" \
  || echo -e "${YELLOW}WARN: El clone finalizó con advertencias (puede ser normal si la DB dev estaba vacía).${NC}"
fi

########################################
# 5) Migraciones Alembic                #
########################################
# Leer variables dev con grep para no contaminar el entorno del script
DEV_PG_USER=$(grep -E '^POSTGRES_USER=' "$ENV_DEV_FILE" | cut -d= -f2- | tr -d '"' || echo "FOCALBOT")
DEV_PG_PASS=$(grep -E '^POSTGRES_PASSWORD=' "$ENV_DEV_FILE" | cut -d= -f2- | tr -d '"' || echo "LASFOCAS_DEV_2026!")
DEV_PG_DB=$(grep -E '^POSTGRES_DB=' "$ENV_DEV_FILE" | cut -d= -f2- | tr -d '"' || echo "focas_dev")
ALEMBIC_URL="postgresql+psycopg://${DEV_PG_USER}:${DEV_PG_PASS}@postgres:5432/${DEV_PG_DB}"

echo -e "${GREEN}Ejecutando migraciones Alembic en dev...${NC}"
MIG_OK=false
for i in $(seq 1 5); do
  if "${COMPOSE_DEV[@]}" exec -T api sh -lc "ALEMBIC_URL='$ALEMBIC_URL' alembic -c /app/db/alembic.ini upgrade head"; then
    MIG_OK=true
    echo -e "${GREEN}Migraciones aplicadas correctamente.${NC}"
    break
  else
    echo -e "${YELLOW}Intento de migración $i/5 fallido. Reintentando en 4s...${NC}"
    sleep 4
  fi
done
if [ "$MIG_OK" != true ]; then
  echo -e "${RED}No se pudieron aplicar las migraciones Alembic.${NC}"; exit 2
fi

########################################
# 6) Health checks básicos              #
########################################
echo -e "${GREEN}Comprobando health de servicios dev...${NC}"

check_http() {
  local name="$1" url="$2" max=20 delay=3
  for i in $(seq 1 $max); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo -e "  ${GREEN}OK${NC} $name → $url"; return 0
    fi
    echo -e "  ${YELLOW}Esperando $name $i/$max...${NC}"; sleep "$delay"
  done
  echo -e "  ${RED}FAIL${NC} $name ($url)"; return 1
}

check_internal() {
  local name="$1" svc="$2" url="$3" max=20 delay=3
  for i in $(seq 1 $max); do
    if "${COMPOSE_DEV[@]}" exec -T "$svc" python - "$url" <<'PY' >/dev/null 2>&1; then
import sys, urllib.request
try:
  with urllib.request.urlopen(sys.argv[1], timeout=5) as r:
    sys.exit(0 if r.status == 200 else 1)
except Exception:
  sys.exit(1)
PY
      echo -e "  ${GREEN}OK${NC} $name"; return 0
    fi
    echo -e "  ${YELLOW}Esperando $name (interno) $i/$max...${NC}"; sleep "$delay"
  done
  echo -e "  ${RED}FAIL${NC} $name"; return 1
}

FAIL=0
check_http     "API dev"         "http://localhost:8011/health"              || ((FAIL++)) || true
check_internal "Web dev"         "web"               "http://localhost:8080/health" || ((FAIL++)) || true
check_internal "NLP dev"         "nlp_intent"        "http://localhost:8100/health" || ((FAIL++)) || true
check_internal "LibreOffice dev" "office"            "http://localhost:8090/health" || ((FAIL++)) || true
check_internal "SlackWorker dev" "slack_baneo_worker" "http://localhost:8095/health" || ((FAIL++)) || true

########################################
# 7) Resumen                            #
########################################
echo ""
if [ $FAIL -gt 0 ]; then
  echo -e "${RED}$FAIL servicio(s) no respondieron. Ver logs con:${NC}"
  echo "  docker compose -f deploy/docker-compose.dev.yml logs -f"
  exit 2
fi

echo -e "${GREEN}Stack dev listo.${NC}"
echo -e "  Panel:   http://localhost:8090/"
echo -e "  API:     http://localhost:8011/docs"
echo -e "  pgAdmin: docker compose -f deploy/docker-compose.dev.yml --profile pgadmin up -d  →  http://localhost:5051"
echo ""
echo -e "${YELLOW}Para detener:${NC} docker compose -f deploy/docker-compose.dev.yml down"
