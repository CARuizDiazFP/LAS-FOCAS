#!/usr/bin/env bash
# Nombre de archivo: build_base.sh
# Ubicación de archivo: scripts/build_base.sh
# Descripción: Construye la imagen base focas-base:latest usando multi-stage build.
#              Detecta si common-requirements.txt cambió (por hash SHA-256) para evitar
#              builds innecesarios. Usarlo antes de levantar cualquier stack.
# Uso: ./scripts/build_base.sh [--force] [-h]

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMON_REQ="$ROOT_DIR/common-requirements.txt"
BASE_DOCKERFILE="$ROOT_DIR/deploy/docker/base.Dockerfile"
IMAGE_NAME="focas-base:latest"

FORCE=false

usage() {
  cat <<EOF
Uso: ./scripts/build_base.sh [opciones]

Opciones:
  --force     Fuerza rebuild aunque common-requirements.txt no haya cambiado
  -h, --help  Muestra esta ayuda

La imagen base contiene las 22+ dependencias Python comunes a todos los servicios
(FastAPI, SQLAlchemy, pandas, etc.). Se reconstruye automáticamente solo cuando
common-requirements.txt cambia (detectado por hash SHA-256).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo -e "${RED}Opción desconocida: $1${NC}"; usage; exit 1 ;;
  esac
  shift
done

if [ ! -f "$COMMON_REQ" ]; then
  echo -e "${RED}Error: no se encontró $COMMON_REQ${NC}"
  exit 1
fi

CURRENT_HASH=$(sha256sum "$COMMON_REQ" | cut -d' ' -f1)
EXISTING_HASH=$(docker inspect "$IMAGE_NAME" --format '{{index .Config.Labels "focas.requirements.hash"}}' 2>/dev/null || echo "none")

if [ "$FORCE" = false ] && [ "$CURRENT_HASH" = "$EXISTING_HASH" ]; then
  echo -e "${GREEN}focas-base:latest ya está actualizada (hash ${CURRENT_HASH:0:12}...). Usar --force para reconstruir.${NC}"
  exit 0
fi

echo -e "${GREEN}Construyendo $IMAGE_NAME (multi-stage build)...${NC}"
echo -e "${YELLOW}  Hash de common-requirements.txt: ${CURRENT_HASH:0:12}...${NC}"

docker build \
  --build-arg REQUIREMENTS_HASH="$CURRENT_HASH" \
  -t "$IMAGE_NAME" \
  -f "$BASE_DOCKERFILE" \
  "$ROOT_DIR"

echo -e "${GREEN}$IMAGE_NAME construida exitosamente.${NC}"
