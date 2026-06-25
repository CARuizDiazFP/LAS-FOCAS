#!/usr/bin/env bash
# Nombre de archivo: setup_local_secrets.sh
# Ubicación de archivo: scripts/setup_local_secrets.sh
# Descripción: Bootstrap idempotente de Docker Secrets locales para desarrollo y CI

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_DIR="$ROOT_DIR/.secrets"
FORCE=false
CI_MODE=false

usage() {
  cat <<'EOF'
Uso: ./scripts/setup_local_secrets.sh [--force] [--ci] [-h]

Opciones:
  --force  Regenera los archivos aunque ya existan.
  --ci     Genera valores determinísticos de prueba para pipelines.
  -h       Muestra esta ayuda.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=true ;;
    --ci) CI_MODE=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

secret_value() {
  local name="$1"
  if $CI_MODE; then
    printf 'ci_%s_secret' "$name"
  else
    python3 - "$name" <<'PY'
import secrets
import sys

name = sys.argv[1]
if name.endswith("_token_v1") or name == "openai_api_key_v1":
    print("")
else:
    print(secrets.token_urlsafe(48))
PY
  fi
}

write_secret() {
  local file="$1"
  local name="${file%.txt}"
  local path="$SECRETS_DIR/$file"

  if [ -f "$path" ] && [ "$FORCE" != true ]; then
    echo "OK existe .secrets/$file"
    return
  fi

  umask 077
  secret_value "$name" > "$path"
  chmod 600 "$path"
  echo "OK generado .secrets/$file"
}

mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

write_secret db_password_v1.txt
write_secret web_secret_key_v1.txt
write_secret api_key_v1.txt
write_secret telegram_bot_token_v1.txt
write_secret openai_api_key_v1.txt
write_secret smtp_password_v1.txt
write_secret slack_bot_token_v1.txt
write_secret slack_app_token_v1.txt

echo "Bootstrap de secretos locales completado."
