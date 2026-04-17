# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/logs-cleanup/SKILL.md
# Descripción: Skill para gestión y limpieza de archivos de log del proyecto y contenedores Docker

---
name: logs-cleanup
description: "Usar cuando haya que revisar o limpiar logs del proyecto y de contenedores sin perder información necesaria para diagnóstico"
argument-hint: "Describe alcance, por ejemplo: limpiar backups de Logs y revisar tamaño de logs Docker"
---

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
