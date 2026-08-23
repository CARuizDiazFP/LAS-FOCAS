# Nombre de archivo: pull_request_template.md
# Ubicación de archivo: .github/pull_request_template.md
# Descripción: Plantilla de PR con checklist técnico y control de redundancia semántica para customizations

## Resumen

- Objetivo del cambio:
- Alcance (módulos/rutas):
- Riesgo estimado (Low/Medium/High):

## Evidencia técnica

- Comandos ejecutados:
- Tests ejecutados:
- Validación manual:

## Checklist general

- [ ] No se introducen secretos, credenciales ni datos sensibles.
- [ ] Se actualizó documentación afectada (`docs/`, PR diario o equivalente).
- [ ] No se alteró comportamiento fuera de alcance sin justificación.

## Checklist de redundancia semántica (customizations)

Aplica si este PR toca `.agentes-comunes/`, `.github/agents`, `.github/prompts`, `.github/skills`, `.gemini/`, `.codex-skills/` o `.claude/`.

- [ ] El cambio no duplica una capacidad ya existente con otro nombre.
- [ ] Si existe solapamiento parcial, quedó documentada la diferencia funcional real.
- [ ] Si se creó alias legacy, redirige al flujo vigente sin lógica paralela.
- [ ] Se revisó complementariedad vs duplicidad (especialmente en flujos críticos).
- [ ] Se ejecutó `bash scripts/check_skill_mirror_drift.sh` y no hubo drift.

## Impacto en flujo recursivo SDD/superpowers

- [ ] No rompe el flujo recursivo.
- [ ] Respeta la política `docs/politica_recursion_sdd.md`.
- [ ] Si hubo re-review extra, está justificada por hallazgo Critical/Important nuevo.

## Notas adicionales

- Pendientes o follow-ups:
