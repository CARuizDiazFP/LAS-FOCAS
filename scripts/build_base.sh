#!/usr/bin/env bash
# Nombre de archivo: build_base.sh
# Ubicación de archivo: scripts/build_base.sh
# Descripción: Construye la imagen base focas-base (tag req-<hash> + alias latest) usando multi-stage build.
#              Detecta si common-requirements.txt cambió (por hash SHA-256 del contenido normalizado,
#              sin comentarios ni líneas vacías) para evitar builds innecesarios. Usarlo antes de levantar
#              cualquier stack.
# Uso: ./scripts/build_base.sh [--force] [--print-hash] [-h]

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMON_REQ="$ROOT_DIR/common-requirements.txt"
BASE_DOCKERFILE="$ROOT_DIR/deploy/docker/base.Dockerfile"
IMAGE_REPO="focas-base"
# Los Dockerfiles usan `latest` como alias; el tag versionado identifica qué base corre cada imagen.
IMAGE_NAME="$IMAGE_REPO:latest"

FORCE=false
PRINT_HASH=false

usage() {
  cat <<EOF
Uso: ./scripts/build_base.sh [opciones]

Opciones:
  --force       Fuerza rebuild aunque common-requirements.txt no haya cambiado
  --print-hash  Imprime el hash de common-requirements.txt y sale (sin Docker)
  -h, --help    Muestra esta ayuda

La imagen base contiene las 22+ dependencias Python comunes a todos los servicios
(FastAPI, SQLAlchemy, pandas, etc.). Se reconstruye automáticamente solo cuando
common-requirements.txt cambia (hash SHA-256 sin comentarios, líneas vacías ni
espacios finales: editar un comentario no reconstruye la base).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=true ;;
    --print-hash) PRINT_HASH=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo -e "${RED}Opción desconocida: $1${NC}"; usage; exit 1 ;;
  esac
  shift
done

if [ ! -f "$COMMON_REQ" ]; then
  echo -e "${RED}Error: no se encontró $COMMON_REQ${NC}"
  exit 1
fi

# Hash sobre el contenido que pip lee: sin comentarios (de línea completa o en línea, como pip: `#` al
# inicio o precedido de espacio), sin espacios finales ni líneas vacías. Antes era el sha256sum del archivo
# entero y un cambio de comentario (P19, 2026-10-28) habría reconstruido la base con los mismos paquetes.
requirements_hash() {
  sed -E 's/(^|[[:space:]]+)#.*$//; s/[[:space:]]+$//' "$1" | sed '/^$/d' | sha256sum | cut -d' ' -f1
}

CURRENT_HASH=$(requirements_hash "$COMMON_REQ")
if [ "$PRINT_HASH" = true ]; then
  echo "$CURRENT_HASH"
  exit 0
fi
EXISTING_HASH=$(docker inspect "$IMAGE_NAME" --format '{{index .Config.Labels "focas.requirements.hash"}}' 2>/dev/null || echo "none")
# Versión por contenido: los mismos paquetes dan el mismo tag (un --force lo mueve a la imagen nueva).
VERSION_TAG="$IMAGE_REPO:req-${CURRENT_HASH:0:12}"

if [ "$FORCE" = false ] && [ "$CURRENT_HASH" = "$EXISTING_HASH" ]; then
  docker image inspect "$VERSION_TAG" >/dev/null 2>&1 || docker tag "$IMAGE_NAME" "$VERSION_TAG"
  echo -e "${GREEN}focas-base:latest ya está actualizada (hash ${CURRENT_HASH:0:12}...). Usar --force para reconstruir.${NC}"
  exit 0
fi

echo -e "${GREEN}Construyendo $IMAGE_NAME (multi-stage build)...${NC}"
echo -e "${YELLOW}  Hash de common-requirements.txt: ${CURRENT_HASH:0:12}...${NC}"

docker build \
  --build-arg REQUIREMENTS_HASH="$CURRENT_HASH" \
  -t "$IMAGE_NAME" \
  -t "$VERSION_TAG" \
  -f "$BASE_DOCKERFILE" \
  "$ROOT_DIR"

echo -e "${GREEN}$IMAGE_NAME construida exitosamente (alias de $VERSION_TAG).${NC}"
