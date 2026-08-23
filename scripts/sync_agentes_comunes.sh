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

while IFS= read -r file; do
  sed -i 's#source: "\\.github/skills/#source: ".agentes-comunes/skills/#g' "$file"
done < <(find .gemini/rules -maxdepth 1 -type f -name 'skill-*.md' | sort)

while IFS= read -r file; do
  sed -i 's#source: "\\.github/skills/#source: ".agentes-comunes/skills/#g' "$file"
  sed -i 's#Fuente original: `\\.github/skills/#Fuente original: `.agentes-comunes/skills/#g' "$file"
done < <(find .codex-skills/skills -type f -name 'SKILL.md' | sort)

while IFS= read -r file; do
  sed -i 's#mirror de \\.github/skills/#mirror de .agentes-comunes/skills/#g' "$file"
done < <(find .claude/skills -type f -name 'SKILL.md' | sort)

echo "OK: mirrors sincronizados desde .agentes-comunes/skills"
