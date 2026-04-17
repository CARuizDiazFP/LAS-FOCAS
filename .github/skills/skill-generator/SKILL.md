# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/skill-generator/SKILL.md
# Descripción: Meta-skill para crear y estandarizar nuevas skills y customizations del ecosistema agéntico

---
name: skill-generator
description: "Usar cuando haya que crear o estandarizar una skill nueva y, si hace falta, su agente y prompt asociados dentro de .github/"
argument-hint: "Describe la nueva skill o tríada, por ejemplo: crear skill para generar runbooks operativos"
---

# Habilidad: Generador de Skills

Workflow invocable para crear nuevas skills sin mezclar capas pasivas y activas de personalización.

## Cuándo usar

Usar esta skill cuando el usuario pida:

- crear una skill nueva
- crear una tríada `agent + prompt + skill`
- refactorizar o estandarizar customizations existentes
- mejorar discovery, naming o carga de contexto de una customization

## Separación de responsabilidades

- El [agente generador](../../agents/skill-generator.agent.md) analiza el repositorio, diseña la solución y edita archivos.
- El [prompt de creación](../../prompts/crear-skill.prompt.md) estructura el requerimiento y fija criterios de aceptación.
- Esta skill empaqueta el workflow y sirve como punto de entrada reutilizable.

## Procedimiento

1. Confirmar si el pedido requiere una skill sola o una tríada completa.
2. Revisar `.github/agents/`, `.github/prompts/`, `.github/skills/`, `AGENTS.md` y documentación relacionada.
3. Reusar naming consistente y descripciones breves con "Usar cuando...".
4. Crear solo los archivos necesarios para la solución.
5. Validar frontmatter, rutas, enlaces y consistencia documental.
6. Actualizar documentación si cambia la arquitectura agéntica del repo.

## Guardrails

1. No meter procedimientos puntuales en instrucciones globales.
2. No duplicar conocimiento entre prompt, agente y skill.
3. No crear skills monolíticas si basta con una pieza más pequeña.
4. No usar descripciones vagas; la discovery depende de ellas.
5. No dejar archivos sin encabezado obligatorio de 3 líneas.

## Resultado esperado

- Archivos de customization creados o actualizados bajo `.github/`.
- Responsabilidades claras por capa.
- Menor riesgo de saturar la ventana de contexto.
- Documentación relacionada alineada con el estado actual del repo.