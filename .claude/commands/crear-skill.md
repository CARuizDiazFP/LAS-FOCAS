# Nombre de archivo: crear-skill.md
# Ubicación de archivo: .claude/commands/crear-skill.md
# Descripción: Comando Claude Code para crear skills y tríadas de customizations en LAS-FOCAS

Crea una skill nueva o una tríada de customizations (agent + prompt + skill). Argumento requerido: $ARGUMENTS (objetivo, alcance y restricciones; por ejemplo: "skill para módulo web con reglas XSS/CORS/Pydantic y anti-legacy").

## Restricción principal

Este comando no escribe código de aplicación. Su salida son reglas, prompts, guardrails y criterios para que otros agentes implementen código.

## Objetivo

- estructurar el pedido antes de escribir archivos
- inspeccionar customizations existentes para evitar duplicaciones
- definir responsabilidades claras entre agente, prompt y skill
- inyectar stack, seguridad y calidad de forma obligatoria
- generar criterios de aceptación verificables

## Flujo de trabajo

1. Determinar si el pedido requiere:
   - solo `SKILL.md`
   - `prompt + skill`
   - `agent + prompt + skill`
2. Revisar archivos existentes en `.github/agents/`, `.github/prompts/`, `.github/skills/`, `.claude/commands/` y `AGENTS.md`.
3. Proponer arquitectura mínima y explícita: nombre de carpeta, naming final, archivos a crear o actualizar, responsabilidad de cada archivo.
4. Inyectar el bloque tecnológico obligatorio, reglas de seguridad y criterios universales.
5. Crear o actualizar los archivos necesarios en `.github/` (fuente de verdad) y propagar a `.claude/commands/` si corresponde.
6. Validar frontmatter, coherencia de descripciones, enlaces y prohibiciones legacy.
7. Actualizar `AGENTS.md` y `CLAUDE.md` si el ecosistema agéntico cambia.

## Contexto Tecnológico Obligatorio (inyectar en toda skill de desarrollo)

```markdown
- Frontend obligatorio: Vue 3 (Composition API) + Vite + TypeScript + CSS modular con tokens.
- Backend obligatorio: FastAPI + Pydantic + SQLAlchemy + Alembic + PostgreSQL.
- Arquitectura obligatoria: SPA pura; comunicación exclusivamente por API REST (JSON) y WebSocket.
- Prohibido para nuevas implementaciones: UI en Vanilla JS, manipulación directa del DOM como patrón principal, templates Jinja para render de frontend.
```

## Reglas de Seguridad Obligatorias (inyectar en toda skill de desarrollo)

1. XSS en Vue 3: evitar `v-html` con contenido no confiable; si se usa HTML dinámico, exigir sanitización documentada.
2. CORS en FastAPI: allowlist estricta; prohibido comodín en producción.
3. Validación Pydantic: modelos tipados para entrada/salida; rechazo de payloads inválidos.
4. API y sesión: controles de autenticación/autorización consistentes con el módulo.
5. Manejo de secretos: uso de variables de entorno, sin hardcodeo ni exposición en logs.

## Criterios Universales de Aceptación (inyectar en toda skill)

- [ ] Arquitectura alineada al stack vigente y sin prácticas legacy
- [ ] Seguridad aplicada y verificable (XSS, CORS, validación de datos)
- [ ] Plan de pruebas mínimo y cobertura esperada para módulos nuevos
- [ ] Logging, observabilidad y manejo de errores definidos
- [ ] Documentación relacionada actualizada
- [ ] Dependencias e imágenes versionadas sin comodines ni `latest`

## Separación de responsabilidades

- **Agente** (`.github/agents/*.agent.md`): análisis, diseño, edición y validación.
- **Prompt** (`.github/prompts/*.prompt.md` + `.claude/commands/*.md`): contrato de entrada, pasos y criterios.
- **Skill** (`.github/skills/*/SKILL.md` + `.codex-skills/skills/*/SKILL.md`): workflow invocable y reutilizable.

## Plantilla mínima de salida

```markdown
## Contexto
- [hecho relevante]

## Arquitectura propuesta
- [archivo]: [responsabilidad]

## Pasos de implementación
1. [paso]

## Criterios de aceptación
- [ ] [criterio verificable]

## Riesgos o notas
- [riesgo real o no aplica]
```

## Reglas obligatorias

1. No inventar requisitos ni validaciones no pedidas.
2. Priorizar referencias y enlaces sobre bloques duplicados.
3. Mantener nombres consistentes con rutas y convención del repo.
4. Prohibir explícitamente directivas legacy en toda skill de desarrollo nueva.
5. Todas las salidas deben quedar en `.md` y en español.
6. Propagar cambios a los tres entornos: `.github/`, `.gemini/`, `.codex-skills/` y `.claude/commands/`.

## Salida esperada

1. Arquitectura propuesta.
2. Archivos creados o actualizados con ubicación explícita.
3. Contexto tecnológico obligatorio inyectado.
4. Criterios universales de aceptación cubiertos.
5. Documentación relacionada actualizada o pendiente explicitada.
