---
name: "las-focas-logs-cleanup"
description: "Usar cuando haya que revisar o limpiar logs del proyecto y de contenedores sin perder información necesaria para diagnóstico"
metadata:
  short-description: "Usar cuando haya que revisar o limpiar logs del proyecto y de contenedores sin perder información necesaria para diag..."
  source: ".agentes-comunes/skills/logs-cleanup/SKILL.md"
  triggers:
    - "logs-cleanup"
    - "habilidad"
    - "limpieza"
    - "logs"
    - "limpiar"
    - "contenedores"
    - "perder"
    - "informaci-n"
    - "necesaria"
    - "diagn-stico"
  globs:
    - "Logs/**"
    - "logs/**"
    - "deploy/**"
  commands:
    []
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-logs-cleanup/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/logs-cleanup/SKILL.md

# Skill portable: logs-cleanup

> Fuente original: `.agentes-comunes/skills/logs-cleanup/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

# Habilidad: Limpieza de Logs

Este skill revisa y limpia logs del proyecto y de contenedores sin perder información útil para diagnóstico.

## Cuándo usar

- cuando `Logs/` o los logs Docker crecen demasiado
- cuando hay backups rotativos viejos o archivos activos sobredimensionados
- cuando hace falta verificar rotación antes de limpiar

## Procedimiento

1. Medir tamaño y fuentes principales de logs.
2. Decidir si conviene borrar backups o truncar activos.
3. Preservar evidencia diagnóstica antes de limpiar.
4. Verificar estado final y rotación.

## Referencias

- [Operación detallada](./references/operacion.md)
- [disk-analysis](../disk-analysis/SKILL.md)
- [temp-cleanup](../temp-cleanup/SKILL.md)

## Guardrails

1. No limpiar logs activos si todavía se investigan errores.
2. Preferir truncado o rotación antes que borrado indiscriminado.
3. Advertir cuando la operación requiera `sudo` sobre logs Docker.
