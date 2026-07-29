#!/usr/bin/env bash
# Nombre de archivo: check_no_plaintext_secrets.sh
# Ubicación de archivo: scripts/check_no_plaintext_secrets.sh
# Descripción: Control preventivo contra secretos versionados y passwords en texto plano

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

FAIL=0

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

if grep -nE 'POSTGRES_PASSWORD[[:space:]]*:' deploy/docker-compose.dev.yml deploy/compose.yml >/tmp/las-focas-postgres-password.txt; then
  report "Se encontró POSTGRES_PASSWORD en texto plano en el compose; usar POSTGRES_PASSWORD_FILE."
  cat /tmp/las-focas-postgres-password.txt >&2
fi
rm -f /tmp/las-focas-postgres-password.txt

if git grep -I -nE 'sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|xapp-[A-Za-z0-9-]{20,}|[0-9]{6,12}:[A-Za-z0-9_-]{30,}' -- . \
  ':!Templates/**' ':!.gemini/**' ':!.github/agents/**' ':!docs/PR/**' ':!deploy/env.sample' ':!deploy/env.dev.sample' >/tmp/las-focas-secret-patterns.txt; then
  report "Se detectaron patrones compatibles con tokens reales en archivos versionados."
  cat /tmp/las-focas-secret-patterns.txt >&2
fi
rm -f /tmp/las-focas-secret-patterns.txt

if git grep -I -nE 'POSTGRES_PASSWORD=|SMTP_PASS=|WEB_SECRET_KEY=|LAS_FOCAS_API_KEY=|OPENAI_API_KEY=sk-' -- . \
  ':!.gemini/**' ':!.github/agents/**' ':!docs/**' ':!deploy/env.sample' ':!deploy/env.dev.sample' \
  ':!scripts/check_no_plaintext_secrets.sh' \
  | grep -Ev '=(cambiar_por_|$)' >/tmp/las-focas-secret-assignments.txt; then
  report "Se detectaron asignaciones sensibles con valores no permitidos."
  cat /tmp/las-focas-secret-assignments.txt >&2
fi
rm -f /tmp/las-focas-secret-assignments.txt

if [ "$FAIL" -ne 0 ]; then
  exit 1
fi

echo "[OK] No se detectaron secretos versionados ni passwords dev en texto plano."
