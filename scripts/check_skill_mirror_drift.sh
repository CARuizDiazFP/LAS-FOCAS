# Nombre de archivo: check_skill_mirror_drift.sh
# Ubicación de archivo: scripts/check_skill_mirror_drift.sh
# Descripción: Verifica drift entre .agentes-comunes/skills y todos sus mirrors (.github, .claude, .gemini, .codex-skills)

#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SRC_DIR=".agentes-comunes/skills"
MIRROR_DIR=".github/skills"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "ERROR: Falta $SRC_DIR" >&2
  exit 1
fi

if [[ ! -d "$MIRROR_DIR" ]]; then
  echo "ERROR: Falta $MIRROR_DIR" >&2
  exit 1
fi

TMP_SRC="$(mktemp -d)"
TMP_MIRROR="$(mktemp -d)"
trap 'rm -rf "$TMP_SRC" "$TMP_MIRROR"' EXIT

cp -a "$SRC_DIR/." "$TMP_SRC/"
cp -a "$MIRROR_DIR/." "$TMP_MIRROR/"

# Ignora diferencias esperadas en la línea 2 del encabezado (ubicación de archivo).
while IFS= read -r file; do
  sed -i '2d' "$file"
done < <(find "$TMP_SRC" "$TMP_MIRROR" -type f -name '*.md' | sort)

if ! diff -qr "$TMP_SRC" "$TMP_MIRROR" >/tmp/skills_drift.diff; then
  echo "ERROR: Drift detectado entre $SRC_DIR y $MIRROR_DIR" >&2
  cat /tmp/skills_drift.diff >&2
  exit 1
fi

echo "OK: Sin drift semántico entre $SRC_DIR y $MIRROR_DIR"

# Los mirrors de .claude, .gemini y .codex-skills no son copias literales (cada
# plataforma tiene su propia estructura de rutas y su frontmatter), así que su drift lo
# verifica el propagador, que aplica las mismas transformaciones deterministas.
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="$(command -v python3 || command -v python)"
  fi
fi

"$PYTHON_BIN" scripts/sync_skill_mirrors.py --check
