#!/usr/bin/env bash
# Nombre de archivo: check_no_plaintext_secrets.sh
# Ubicación de archivo: scripts/check_no_plaintext_secrets.sh
# Descripción: Control preventivo contra secretos versionados y passwords en texto plano

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

FAIL=0
# Directorio propio por corrida: con rutas fijas en /tmp, dos sesiones en paralelo se pisaban la salida.
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

report() {
  echo "[ERROR] $1" >&2
  FAIL=1
}

tracked_sensitive="$(git ls-files | grep -E '(^|/)\.env($|\.)|(^|/)Keys/|\.pem$|\.key$' || true)"
tracked_sensitive="$(printf '%s\n' "$tracked_sensitive" | grep -Ev '^deploy/env(\.dev)?\.sample$' || true)"
if [ -n "$tracked_sensitive" ]; then
  report "Hay archivos sensibles versionados:"
  printf '%s\n' "$tracked_sensitive" >&2
fi

if grep -nE 'POSTGRES_PASSWORD[[:space:]]*:' deploy/docker-compose.dev.yml deploy/compose.yml >"$TMP_DIR/compose.txt"; then
  report "Se encontró POSTGRES_PASSWORD en texto plano en el compose; usar POSTGRES_PASSWORD_FILE."
  cat "$TMP_DIR/compose.txt" >&2
fi

if git grep -I -nE 'sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|xapp-[A-Za-z0-9-]{20,}|[0-9]{6,12}:[A-Za-z0-9_-]{30,}' -- . \
  ':!Templates/**' ':!.gemini/**' ':!.github/agents/**' ':!docs/PR/**' ':!deploy/env.sample' ':!deploy/env.dev.sample' >"$TMP_DIR/tokens.txt"; then
  report "Se detectaron patrones compatibles con tokens reales en archivos versionados."
  cat "$TMP_DIR/tokens.txt" >&2
fi

# Una asignación sólo cuenta si su valor es literal: se aceptan vacío, el placeholder `cambiar_por_` y
# los que el shell resuelve al correr (`$(cat .secrets/…)`, `${VAR}`, `$VAR`, con o sin comillas, y la
# comilla invertida de la sustitución clásica, que en Markdown cierra un código vacío). Se
# decide por asignación, no por línea: un literal al lado de un `$(…)` se sigue detectando. Un literal
# falso a propósito (p. ej. en un test) se declara en su línea con `# secreto-ok: <motivo>`.
ASIGNACION_LITERAL='(POSTGRES_PASSWORD|SMTP_PASS|WEB_SECRET_KEY|LAS_FOCAS_API_KEY)=(?!["'"'"']?\$[({A-Za-z_]|`|cambiar_por_|$)|OPENAI_API_KEY=sk-'
if git grep -I -nE 'POSTGRES_PASSWORD=|SMTP_PASS=|WEB_SECRET_KEY=|LAS_FOCAS_API_KEY=|OPENAI_API_KEY=sk-' -- . \
  ':!.gemini/**' ':!.github/agents/**' ':!docs/**' ':!deploy/env.sample' ':!deploy/env.dev.sample' \
  ':!scripts/check_no_plaintext_secrets.sh' \
  | grep -P "$ASIGNACION_LITERAL" | grep -Fv '# secreto-ok:' >"$TMP_DIR/asignaciones.txt"; then
  report "Se detectaron asignaciones sensibles con valores no permitidos."
  cat "$TMP_DIR/asignaciones.txt" >&2
fi

if [ "$FAIL" -ne 0 ]; then
  exit 1
fi

echo "[OK] No se detectaron secretos versionados ni passwords dev en texto plano."
