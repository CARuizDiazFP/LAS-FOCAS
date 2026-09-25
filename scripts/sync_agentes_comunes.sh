# Nombre de archivo: sync_agentes_comunes.sh
# Ubicación de archivo: scripts/sync_agentes_comunes.sh
# Descripción: Sincroniza skills desde .agentes-comunes hacia mirrors de .github, .gemini y .codex-skills

#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -d ".agentes-comunes/skills" ]]; then
  echo "ERROR: No existe .agentes-comunes/skills" >&2
  exit 1
fi

mkdir -p .github
rm -rf .github/skills
cp -a .agentes-comunes/skills .github/

# Ajusta la línea de ubicación para que los mirrors en .github reflejen su ruta real.
while IFS= read -r file; do
  rel_path="${file#./.github/skills/}"
  rel_path="${rel_path#.github/skills/}"
  sed -i "2s|^# Ubicación de archivo: .*|# Ubicación de archivo: .github/skills/${rel_path}|" "$file"
done < <(find .github/skills -type f -name '*.md' | sort)

# Los mirrors de .claude, .gemini y .codex-skills tienen estructura propia (rutas y
# frontmatter distintos por plataforma), así que los regenera el propagador dedicado.
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="$(command -v python3 || command -v python)"
  fi
fi

"$PYTHON_BIN" scripts/sync_skill_mirrors.py

echo "OK: mirrors sincronizados desde .agentes-comunes/skills"
