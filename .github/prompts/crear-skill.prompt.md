# Nombre de archivo: crear-skill.prompt.md
# Ubicación de archivo: .github/prompts/crear-skill.prompt.md
# Descripción: Prompt estructurado para crear skills y tríadas de customizations en LAS-FOCAS

---
name: Crear Skill
description: "Crea o evoluciona skills meta-agénticas con stack SPA/API moderno, seguridad obligatoria y criterios universales de aceptación"
argument-hint: "Describe objetivo, alcance y restricciones; por ejemplo: skill para módulo web con reglas XSS/CORS/Pydantic y anti-legacy"
agent: "skill-generator"
---

# Crear Skill para LAS-FOCAS

Crear una skill nueva o una tríada de customizations bajo `.github/` a partir del requerimiento del usuario.

## Objetivo

- estructurar el pedido antes de escribir archivos
- inspeccionar customizations existentes para evitar duplicaciones
- definir responsabilidades claras entre agente, prompt y skill
- inyectar stack, seguridad y calidad de forma obligatoria
- generar criterios de aceptación verificables

## Restricción Principal

- Este generador no escribe código de aplicación.
- Su salida debe ser reglas, prompts, guardrails y criterios para que otros agentes implementen código.

## Entradas esperadas

- objetivo funcional de la nueva skill
- alcance: skill sola o tríada completa
- disparadores o keywords de descubrimiento
- archivos o recursos complementarios esperados
- restricciones de herramientas o contexto
- documentación que debería actualizarse

## Contexto Tecnológico Obligatorio (Inyección Requerida)

Toda skill de desarrollo que genere este prompt debe incluir textual y explícitamente:

```markdown
## Contexto Tecnológico Obligatorio LAS-FOCAS

- Frontend obligatorio: Vue 3 (Composition API) + Vite + TypeScript + CSS modular con tokens.
- Backend obligatorio: FastAPI + Pydantic + SQLAlchemy + Alembic + PostgreSQL.
- Arquitectura obligatoria: SPA pura; comunicación exclusivamente por API REST (JSON) y WebSocket.
- Prohibido para nuevas implementaciones: UI en Vanilla JS, manipulación directa del DOM como patrón principal, plantillas Jinja para render de frontend.
- No introducir Tailwind en nuevas directivas salvo solicitud explícita y aprobada por arquitectura.
```

## Reglas de Seguridad y Arquitectura (Inyección Requerida)

Toda skill de desarrollo debe incluir directivas explícitas para:

1. XSS en Vue 3: evitar `v-html` con contenido no confiable; si se usa HTML dinámico, exigir sanitización documentada.
2. CORS en FastAPI: configuración strict allowlist; prohibido comodín en producción.
3. Validación Pydantic: modelos tipados para entrada/salida; rechazo de payloads inválidos.
4. API y sesión: controles de autenticación/autorización consistentes con el módulo.
5. Manejo de secretos: uso de variables de entorno, sin hardcodeo ni exposición en logs.

## Criterios Universales de Aceptación (Inyección Requerida)

Sin importar el dominio de la skill, siempre agregar:

- [ ] Arquitectura alineada al stack vigente y sin prácticas legacy.
- [ ] Seguridad aplicada y verificable (XSS, CORS, validación de datos).
- [ ] Plan de pruebas mínimo (unitarias/integración según alcance) y cobertura esperada para módulos nuevos.
- [ ] Logging, observabilidad y manejo de errores definidos.
- [ ] Documentación relacionada actualizada cuando haya cambios de directiva.
- [ ] Dependencias e imágenes versionadas sin comodines ni `latest`.

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
4. Inyectar el bloque tecnológico obligatorio, reglas de seguridad y criterios universales de aceptación.
5. Crear o actualizar los archivos necesarios.
6. Validar frontmatter, coherencia de descripciones, enlaces y prohibiciones legacy.
7. Actualizar documentación relacionada si el ecosistema agéntico cambia o hay inconsistencias.

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
5. Prohibir explícitamente directivas legacy en toda skill de desarrollo nueva.
6. Todas las salidas deben quedar en `.md` y en español.
7. No redactar código de aplicación; solo reglas/prompts y criterios.

## Salida esperada

1. Arquitectura propuesta.
2. Archivos creados o actualizados.
3. Contexto tecnológico obligatorio inyectado.
4. Reglas de seguridad SPA/API inyectadas.
5. Criterios universales de aceptación cubiertos.
6. Documentación relacionada actualizada o pendiente explicitada.