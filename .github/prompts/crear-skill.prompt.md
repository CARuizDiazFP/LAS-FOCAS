# Nombre de archivo: crear-skill.prompt.md
# Ubicación de archivo: .github/prompts/crear-skill.prompt.md
# Descripción: Prompt estructurado para crear skills y tríadas de customizations en LAS-FOCAS

---
name: Crear Skill
description: "Crea una skill nueva o una tríada agent+prompt+skill con estructura, validaciones y documentación consistente"
argument-hint: "Describe objetivo, alcance y artefactos, por ejemplo: skill para generar playbooks de incidentes con agent y prompt asociados"
agent: "skill-generator"
---

# Crear Skill para LAS-FOCAS

Crear una skill nueva o una tríada de customizations bajo `.github/` a partir del requerimiento del usuario.

## Objetivo

- estructurar el pedido antes de escribir archivos
- inspeccionar customizations existentes para evitar duplicaciones
- definir responsabilidades claras entre agente, prompt y skill
- generar criterios de aceptación verificables

## Entradas esperadas

- objetivo funcional de la nueva skill
- alcance: skill sola o tríada completa
- disparadores o keywords de descubrimiento
- archivos o recursos complementarios esperados
- restricciones de herramientas o contexto
- documentación que debería actualizarse

## Flujo de trabajo

1. Determinar si el pedido requiere:
   - solo `SKILL.md`
   - `prompt + skill`
   - `agent + prompt + skill`
2. Revisar `.github/agents/`, `.github/prompts/`, `.github/skills/`, `AGENTS.md` y documentación relacionada.
3. Proponer una arquitectura mínima y explícita:
   - nombre de carpeta y naming final
   - archivos a crear o actualizar
   - responsabilidad de cada archivo
4. Crear o actualizar los archivos necesarios.
5. Validar frontmatter, coherencia de descripciones y enlaces.
6. Actualizar documentación relacionada si el ecosistema agéntico cambia.

## Separación obligatoria de responsabilidades

- **Agente**: análisis, diseño, edición y validación.
- **Prompt**: contrato de entrada, pasos y criterios de aceptación.
- **Skill**: workflow invocable y reusable por slash command.

## Plantilla mínima a producir

```markdown
## Contexto
- [hecho relevante]

## Arquitectura propuesta
- [archivo]: [responsabilidad]

## Pasos de implementación
1. [paso]
2. [paso]

## Criterios de aceptación
- [ ] [criterio verificable]

## Riesgos o notas
- [riesgo real o no aplica]
```

## Reglas obligatorias

1. No inventar requisitos ni validaciones no pedidas.
2. No llevar conocimiento puntual a instrucciones globales.
3. Priorizar enlaces y referencias sobre bloques largos duplicados.
4. Mantener nombres consistentes con rutas y convención del repo.
5. Todas las salidas deben quedar en `.md` y en español.

## Salida esperada

1. Arquitectura propuesta.
2. Archivos creados o actualizados.
3. Criterios de aceptación cubiertos.
4. Documentación relacionada actualizada o pendiente explicitada.