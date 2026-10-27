# Nombre de archivo: GEMINI.md
# Ubicación de archivo: GEMINI.md
# Descripción: Índice portable de reglas IDE para Gemini y agentes compatibles en LAS-FOCAS

# Reglas Portables LAS-FOCAS para Gemini/Codex IDE

Este archivo complementa `AGENTS.md`. Usar `AGENTS.md` como instrucciones base del proyecto y cargar las reglas de `.gemini/rules/` cuando la tarea coincida con sus `triggers` o `globs`.

> **Antes de cualquier búsqueda global**, leer `docs/REPOSITORY_MAP.md` (mapa por dominio, ≤ 8 KiB) y
> buscar sólo en las raíces del dominio de la tarea. Reglas de contexto (logs bajo demanda,
> context-splitting, matriz de exclusión) en `AGENTS.md` → "Contexto y tokens".

> **Lazy loading de skills**: cada `.gemini/rules/skill-<n>.md` es un adaptador de ≤ 15 líneas
> (frontmatter con `triggers`/`globs` + puntero). La skill completa vive en
> `.agentes-comunes/skills/<n>/SKILL.md` y se lee **sólo** cuando la regla se activa. El mismo
> contenido está disponible como Agent Skills nativas en `.agents/skills/<n>/SKILL.md`. Para
> Superpowers usar el índice `docs/superpowers/CATALOG.md`; las skills locales prevalecen.

Las fuentes originales viven en `.agentes-comunes/skills/` (skills) y `.github/agents/` + `.github/prompts/` (agentes/prompts); no deben eliminarse ni editarse desde las copias generadas.

> Nota Codex: `.codex/` está montado como solo lectura en esta sesión. Las skills Codex se generaron en `.codex-skills/skills/` con el mismo formato esperado para copiarlas a `.codex/skills/` cuando el entorno lo permita.

## Reglas de Uso

- Skills: workflows reutilizables y comandos operativos.
- Agentes: perfiles de especialidad por subsistema.
- Prompts: contratos de ejecución para tareas repetibles.
- Assets: `.gemini/rules/assets/frontend-specs/` contiene especificaciones JSON asociadas al frontend.
- El flujo recursivo SDD/superpowers se conserva para tareas complejas; priorizar iteraciones cortas y cerrar ciclos cuando no hay hallazgos nuevos.
- Política formal de recursión y corte: `docs/politica_recursion_sdd.md`.

## Skills Migradas

- [skill-agent-worktree](.gemini/rules/skill-agent-worktree.md)
- [skill-alembic-migrations](.gemini/rules/skill-alembic-migrations.md)
- [skill-baneo-qa-real](.gemini/rules/skill-baneo-qa-real.md)
- [skill-cierre-sesion](.gemini/rules/skill-cierre-sesion.md)
- [skill-cromo-diagnostico-real](.gemini/rules/skill-cromo-diagnostico-real.md)
- [skill-cromo-inventario](.gemini/rules/skill-cromo-inventario.md)
- [skill-db-mcp-postgres](.gemini/rules/skill-db-mcp-postgres.md)
- [skill-dependency-audit](.gemini/rules/skill-dependency-audit.md)
- [skill-dev-workflow](.gemini/rules/skill-dev-workflow.md)
- [skill-disk-analysis](.gemini/rules/skill-disk-analysis.md)
- [skill-docker-cleanup](.gemini/rules/skill-docker-cleanup.md)
- [skill-docker-rebuild](.gemini/rules/skill-docker-rebuild.md)
- [skill-frontend-spa-architecture](.gemini/rules/skill-frontend-spa-architecture.md)
- [skill-libreoffice-convert](.gemini/rules/skill-libreoffice-convert.md)
- [skill-logs-cleanup](.gemini/rules/skill-logs-cleanup.md)
- [skill-nocturne-token-compliance](.gemini/rules/skill-nocturne-token-compliance.md)
- [skill-pytest-focas](.gemini/rules/skill-pytest-focas.md)
- [skill-repo-update](.gemini/rules/skill-repo-update.md)
- [skill-repo-updater](.gemini/rules/skill-repo-updater.md)
- [skill-sast-analysis](.gemini/rules/skill-sast-analysis.md)
- [skill-secret-detection](.gemini/rules/skill-secret-detection.md)
- [skill-secrets-rollout](.gemini/rules/skill-secrets-rollout.md)
- [skill-security-scan](.gemini/rules/skill-security-scan.md)
- [skill-skill-generator](.gemini/rules/skill-skill-generator.md)
- [skill-temp-cleanup](.gemini/rules/skill-temp-cleanup.md)

## Agentes Migrados

- [agent-api-agent](.gemini/rules/agent-api-agent.md)
- [agent-db-agent](.gemini/rules/agent-db-agent.md)
- [agent-docker-agent](.gemini/rules/agent-docker-agent.md)
- [agent-infra-agent](.gemini/rules/agent-infra-agent.md)
- [agent-mcp-chatbot-agent](.gemini/rules/agent-mcp-chatbot-agent.md)
- [agent-nlp-agent](.gemini/rules/agent-nlp-agent.md)
- [agent-office-agent](.gemini/rules/agent-office-agent.md)
- [agent-reports-agent](.gemini/rules/agent-reports-agent.md)
- [agent-security-agent](.gemini/rules/agent-security-agent.md)
- [agent-skill-generator-agent](.gemini/rules/agent-skill-generator-agent.md)
- [agent-testing-agent](.gemini/rules/agent-testing-agent.md)
- [agent-web-agent](.gemini/rules/agent-web-agent.md)

## Prompts Migrados

- [prompt-cierre-sesion-prompt](.gemini/rules/prompt-cierre-sesion-prompt.md)
- [prompt-crear-skill-prompt](.gemini/rules/prompt-crear-skill-prompt.md)
- [prompt-generar-pr-diario-prompt](.gemini/rules/prompt-generar-pr-diario-prompt.md)
- [prompt-mantenimiento-disco-prompt](.gemini/rules/prompt-mantenimiento-disco-prompt.md)
- [prompt-migracion-alembic-prompt](.gemini/rules/prompt-migracion-alembic-prompt.md)
- [prompt-nuevo-modulo-prompt](.gemini/rules/prompt-nuevo-modulo-prompt.md)
- [prompt-repo-updater-prompt](.gemini/rules/prompt-repo-updater-prompt.md)
- [prompt-revisar-seguridad-prompt](.gemini/rules/prompt-revisar-seguridad-prompt.md)

## Compatibilidad Codex

Las skills Codex portables están en `.codex-skills/skills/las-focas-*/SKILL.md` con frontmatter de descubrimiento y referencias copiadas cuando existen.
