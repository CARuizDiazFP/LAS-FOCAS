---
name: "las-focas-skill-generator"
description: "Usar cuando haya que crear o evolucionar skills meta-agénticas con stack SPA/API moderno, seguridad obligatoria y reglas anti-legacy"
metadata:
  short-description: "Usar cuando haya que crear o evolucionar skills meta-agénticas con stack SPA/API moderno, seguridad obligatoria y reglas..."
  source: ".agentes-comunes/skills/skill-generator/SKILL.md"
  triggers:
    - "skill-generator"
    - "habilidad"
    - "generador"
    - "skills"
    - "crear"
    - "evolucionar"
    - "spa"
    - "seguridad"
    - "anti-legacy"
    - "meta-agentico"
  globs:
    - ".github/skills/**"
    - ".github/agents/**"
    - ".github/prompts/**"
    - ".codex-skills/**"
    - ".gemini/rules/**"
  commands:
    []
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-skill-generator/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/skill-generator/SKILL.md

# Skill portable: skill-generator

> Fuente original: `.agentes-comunes/skills/skill-generator/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

# Habilidad: Generador de Skills

Workflow invocable para crear nuevas skills sin mezclar capas pasivas y activas de personalización.

## Cuándo usar

Usar esta skill cuando el usuario pida:

- crear una skill nueva
- crear una tríada `agent + prompt + skill`
- refactorizar o estandarizar customizations existentes
- mejorar discovery, naming o carga de contexto de una customization
- imponer guardrails obligatorios de stack, seguridad y limpieza anti-legacy

## Alcance Estricto

- Esta skill define reglas y prompts para otros agentes.
- No implementa código funcional de aplicación.

## Inyección Obligatoria para Skills de Desarrollo

Debe incluirse siempre:

1. Contexto tecnológico obligatorio del proyecto:
  - Vue 3 (Composition API) + Vite + TypeScript + CSS modular con tokens.
  - FastAPI + Pydantic + SQLAlchemy + Alembic + PostgreSQL.
  - SPA pura vía API REST JSON + WebSocket.
2. Prohibiciones legacy explícitas:
  - No Vanilla JS para UI nueva.
  - No manipulación directa del DOM como patrón principal.
  - No Jinja para frontend moderno.
3. Seguridad mínima obligatoria:
  - XSS: evitar `v-html` con contenido no confiable.
  - CORS: allowlist estricta en FastAPI, sin comodín en producción.
  - Validación Pydantic estricta en entradas/salidas.
4. Criterios universales de aceptación:
  - arquitectura, seguridad, pruebas, observabilidad, documentación y versionado.

## Separación de responsabilidades

- El [agente generador](../../agents/skill-generator.agent.md) analiza el repositorio, diseña la solución y edita archivos.
- El [prompt de creación](../../prompts/crear-skill.prompt.md) estructura el requerimiento y fija criterios de aceptación.
- Esta skill empaqueta el workflow y sirve como punto de entrada reutilizable.

## Procedimiento

1. Confirmar si el pedido requiere una skill sola o una tríada completa.
2. Revisar `.github/agents/`, `.github/prompts/`, `.github/skills/`, `AGENTS.md` y documentación relacionada.
3. Reusar naming consistente y descripciones breves con "Usar cuando...".
4. Inyectar contexto tecnológico obligatorio, seguridad y criterios universales.
5. Crear solo los archivos necesarios para la solución.
6. Validar frontmatter, rutas, enlaces, consistencia documental y cumplimiento anti-legacy.
7. Actualizar documentación y espejos portables cuando aplique.

## Guardrails

1. No meter procedimientos puntuales en instrucciones globales.
2. No duplicar conocimiento entre prompt, agente y skill.
3. No crear skills monolíticas si basta con una pieza más pequeña.
4. No usar descripciones vagas; la discovery depende de ellas.
5. No dejar archivos sin encabezado obligatorio de 3 líneas.
6. No aceptar directivas que mezclen stack SPA moderno con prácticas legacy.
7. No permitir entregables sin criterios de aceptación verificables.

## Resultado esperado

- Archivos de customization creados o actualizados bajo `.github/`.
- Responsabilidades claras por capa.
- Menor riesgo de saturar la ventana de contexto.
- Guardrails de seguridad y arquitectura aplicados de forma uniforme.
- Documentación relacionada alineada con el estado actual del repo.
