# Nombre de archivo: skill-temp-cleanup.md
# Ubicación de archivo: .gemini/rules/skill-temp-cleanup.md
# Descripción: Regla Gemini portable migrada desde .github/skills/temp-cleanup/SKILL.md
---
name: "skill-temp-cleanup"
description: "Usar cuando haya que limpiar archivos temporales, __pycache__, bytecode o caches de desarrollo del repo"
source: ".github/skills/temp-cleanup/SKILL.md"
triggers:
  - "temp-cleanup"
  - "habilidad"
  - "limpieza"
  - "temporales"
  - "limpiar"
  - "pycache"
  - "bytecode"
  - "caches"
  - "desarrollo"
  - "repo"
globs:
  - "**/__pycache__/**"
  - ".pytest_cache/**"
  - ".mypy_cache/**"
  - ".ruff_cache/**"
  - "tmp/**"
commands:
  []
---

# Regla Skill: temp-cleanup

> Fuente original: `.github/skills/temp-cleanup/SKILL.md`. Usar esta regla cuando Gemini/Codex IDE detecte los triggers o globs declarados.

# Habilidad: Limpieza de Temporales

Este skill gestiona la limpieza de cachés y temporales del repo sin mezclarla con recursos persistentes ni datos de trabajo.

## Cuándo usar

- cuando haya que liberar espacio por `__pycache__`, `.pyc` o caches de herramientas
- cuando el repo acumule residuos de pruebas o análisis estático
- cuando se quiera revisar `devs/output/` o temporales del usuario con cautela

## Procedimiento

1. Medir qué temporales existen y cuánto ocupan.
2. Limpiar primero bytecode y caches seguras.
3. Pedir confirmación antes de tocar `devs/output/` o temporales dudosos.
4. Verificar el estado final.

## Referencias

- [Operación detallada](./references/operacion.md)
- [disk-analysis](../disk-analysis/SKILL.md)
- [logs-cleanup](../logs-cleanup/SKILL.md)

## Guardrails

1. No borrar artefactos persistentes ni salidas de trabajo sin confirmación.
2. Limitar `/tmp` a archivos del usuario actual cuando aplique.
3. Si el espacio liberable es marginal, decirlo y no forzar limpieza.
