# Nombre de archivo: README.md
# Ubicación de archivo: .agentes-comunes/README.md
# Descripción: Fuente central agnóstica de skills y política de sincronización multi-plataforma

# .agentes-comunes

Directorio central para capacidades reutilizables del ecosistema agéntico del proyecto.

## Objetivo

- Unificar la fuente de verdad de skills en un único lugar agnóstico.
- Mantener compatibilidad con Copilot, Claude, Gemini y Codex mediante mirrors.
- Preservar el flujo recursivo SDD/superpowers sin forzar loops innecesarios.

## Fuente de verdad

- Skills: `.agentes-comunes/skills/`
- Agentes: `.github/agents/`
- Prompts: `.github/prompts/`

## Mirrors esperados

- `.github/skills/`
- `.gemini/rules/` (archivos `skill-*.md`)
- `.codex-skills/skills/las-focas-*/SKILL.md`
- `.claude/skills/<nombre>/SKILL.md` (solo los que se quieran invocables por `Skill` tool)

## Política de flujo recursivo

El flujo recursivo (SDD/superpowers) está permitido para tareas largas y de alto riesgo.
Para optimizar tiempos y evitar sesiones interminables:

1. Cerrar ciclo cuando una re-review no trae hallazgos nuevos.
2. Evitar encadenar más de una re-review por el mismo diff salvo hallazgo crítico nuevo.
3. Consolidar fixes relacionados en una única fix wave cuando sea posible.
4. Mantener evidencia verificable (tests, lint, diff) en cada ciclo.

Referencia normativa detallada: `docs/politica_recursion_sdd.md`.

## Sincronización recomendada

Ejecutar:

```bash
bash scripts/sync_agentes_comunes.sh
```

El script sincroniza skills desde `.agentes-comunes/skills/` hacia `.github/skills/` y actualiza referencias `source:` en mirrors Gemini y Codex.

## Nota de trazabilidad

- Algunos encabezados heredados dentro de `.agentes-comunes/skills/` todavía referencian rutas originales bajo `.github/skills/`.
- Es una deuda documental identificada en la auditoría `docs/agentes-auditoria-consolidacion-2026-08-23.md`; no afecta ejecución, pero debe normalizarse para evitar ambigüedad de mantenimiento.
