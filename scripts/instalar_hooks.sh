#!/usr/bin/env bash
# Nombre de archivo: instalar_hooks.sh
# Ubicación de archivo: scripts/instalar_hooks.sh
# Descripción: Instala los hooks versionados de scripts/hooks configurando core.hooksPath

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HOOKS_DIR="scripts/hooks"

if [[ ! -d "$HOOKS_DIR" ]]; then
  echo "ERROR: no existe $HOOKS_DIR" >&2
  exit 1
fi

ACTUAL="$(git config --get core.hooksPath || true)"
if [[ -n "$ACTUAL" && "$ACTUAL" != "$HOOKS_DIR" ]]; then
  echo "AVISO: core.hooksPath ya apunta a '$ACTUAL'." >&2
  echo "       Se reemplaza por '$HOOKS_DIR'. Revisar si esos hooks siguen siendo necesarios." >&2
fi

# Hooks existentes en .git/hooks (los de ejemplo .sample no cuentan): se avisan porque
# core.hooksPath los deja inactivos.
EXISTENTES="$(find .git/hooks -maxdepth 1 -type f ! -name '*.sample' 2>/dev/null | wc -l)"
if [[ "$EXISTENTES" -gt 0 ]]; then
  echo "AVISO: hay $EXISTENTES hook(s) en .git/hooks que quedarán inactivos:" >&2
  find .git/hooks -maxdepth 1 -type f ! -name '*.sample' -printf '       %f\n' >&2
fi

chmod +x "$HOOKS_DIR"/*
git config core.hooksPath "$HOOKS_DIR"

echo "OK: core.hooksPath = $HOOKS_DIR"
echo "Hooks activos:"
find "$HOOKS_DIR" -maxdepth 1 -type f -printf '  %f\n'
echo
echo "Se aplican al checkout de control y a todos los worktrees de agentes."
echo "Desinstalar: git config --unset core.hooksPath"
