<!-- repository-map: {"source_commit": "fbb7e1ec01d1", "generated_at_utc": "2026-10-26T10:16:18Z", "manifest_sha256": "569a344474f83c654944c82aef9c8f513a245ad33fc4e62b634f7b634ff6d372"} -->
# Nombre de archivo: REPOSITORY_MAP.md
# Ubicación de archivo: docs/REPOSITORY_MAP.md
# Descripción: Mapa canónico del repositorio por dominio (generado; no editar a mano)

# Mapa canónico del repositorio LAS-FOCAS

> Generado desde `config/repository-map.json` con `python scripts/generate_repository_map.py --write`.
> **Leer antes de cualquier búsqueda global**: identificar el dominio de la tarea y buscar
> sólo dentro de sus raíces. Un dominio por contexto (context-splitting).

No indexar nunca: `.venv/`, `web/frontend/node_modules/`, `web/frontend/dist/`, `Logs/`, `.secrets/`, `.env*`, `docs/cierres/`, `docs/PR/`, `docs/superpowers/plans/`, `docs/superpowers/specs/`.

## `governance` — Gobernanza agéntica

Reglas, skills, agentes, worktrees por agente, leases y auditoría del entorno.

- Raíces: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.agentes-comunes/skills/`, `.github/agents/`, `.github/prompts/`, `.claude/commands/`, `scripts/agentes/`, `config/`
- Entradas: `scripts/agent_worktree.py`, `scripts/agent_lock.py`, `scripts/sync_skill_mirrors.py`, `scripts/generate_repository_map.py`, `scripts/audit_agentic_environment.py`
- Docs: `docs/arquitectura_agentes_worktrees.md`, `docs/politica_recursion_sdd.md`, `docs/superpowers/CATALOG.md`
- Tests: `tests/test_agent_worktree.py`, `tests/test_agent_lock.py`, `tests/test_sync_skill_mirrors.py`, `tests/test_generate_repository_map.py`, `tests/test_audit_agentic_environment.py`
- Comandos: `python scripts/audit_agentic_environment.py`, `bash scripts/check_skill_mirror_drift.sh`, `python scripts/agent_worktree.py status`
- No indexar: `.github/skills/`, `.claude/skills/`, `.agents/skills/`, `.gemini/rules/`, `.codex-skills/`

## `api` — API FastAPI

API REST (puerto dev 8011), OAuth2 M2M /api/v1, healthchecks.

- Raíces: `api/`
- Entradas: `api/app/main.py`, `api/app/routes/`, `api/app/oauth.py`
- Docs: `docs/api.md`
- Tests: `tests/test_api_*.py`
- Comandos: `pytest tests/test_api_auth.py -q`

## `cromo-infra` — Infraestructura FO y Cromo Red

Ingesta Cromo, cámaras, botellas, cables, ODFs, tracking de caminos ópticos y servicios PROV.

- Raíces: `core/services/cromo/`, `core/services/`, `core/services/prov/`, `modules/cromo_worker/`, `modules/botellas_recalculo_worker/`
- Entradas: `core/services/cromo/ingesta.py`, `core/services/cromo/tracking_service.py`, `core/services/infra_service.py`
- Docs: `docs/modulo_ingesta_cromo.md`, `docs/infra.md`
- Tests: `tests/test_cromo_*.py`, `tests/test_botella*.py`, `tests/test_prov_*.py`
- Comandos: `pytest tests/test_cromo_ingesta.py -q`
- No indexar: `tests/*_real_db.py`

## `sla-reports` — Informes SLA y Repetitividad

Motor SLA, consumo histórico, repetitividad, parsers de Excel, plantillas DOCX y conversión PDF.

- Raíces: `core/sla/`, `core/sla_consumo/`, `modules/informes_sla/`, `modules/informes_repetitividad/`, `office_service/`, `Templates/`, `modules/common/`, `core/parsers/`
- Entradas: `core/sla/engine.py`, `core/sla/report.py`, `office_service/app/`
- Docs: `docs/informes/`, `docs/office_service.md`
- Tests: `tests/test_sla*.py`, `tests/test_*repetitividad*.py`, `tests/test_office*.py`
- Comandos: `pytest tests/test_sla_processor.py -q`
- No indexar: `Templates/*.docx`

## `web-spa` — Panel web y SPA Vue 3

Backend web (puerto dev 8090, sesión/CSRF/WebSocket) y SPA Vue 3 + Vite.

- Raíces: `web/app/`, `web/frontend/src/`, `web/tools/`
- Entradas: `web/app/main.py`, `web/app/routers/`, `web/app/comun.py`, `web/frontend/src/main.ts`, `web/frontend/src/router/index.ts`
- Docs: `docs/web.md`, `docs/clientes_categoria.md`
- Tests: `tests/test_web*.py`
- Comandos: `pytest tests/test_web_*.py -q`, `cd web/frontend && npm run build  # sólo deploy`
- No indexar: `web/frontend/node_modules/`, `web/frontend/dist/`

## `bots-workers` — Bots, NLP y workers

Bot Telegram, notificador/app de Slack, clasificador de intención y FO Monitor.

- Raíces: `bot_telegram/`, `modules/slack_baneo_notifier/`, `nlp_intent/`, `modules/fo_monitor_worker/`, `core/services/fo_monitor/`
- Entradas: `bot_telegram/app.py`, `nlp_intent/app/`
- Docs: `docs/bot.md`, `docs/slack_app_cables.md`, `docs/nlp/`, `docs/fo_monitor.md`
- Tests: `tests/test_bot*.py`, `tests/test_slack*.py`, `tests/test_fo_monitor*.py`, `nlp_intent/tests/`
- Comandos: `LLM_PROVIDER=heuristic pytest tests/test_slack*.py -q`

## `chatbot-mcp` — Chatbot y MCP

Orquestador de chat del panel, herramientas MCP (varias stub/rotas) y persistencia de conversaciones.

- Raíces: `core/mcp/`, `core/chatbot/`, `core/repositories/`
- Entradas: `core/mcp/registry.py`, `core/chatbot/orchestrator.py`, `web/app/routers/chat.py`
- Docs: `docs/chatbot.md`, `docs/mcp.md`
- Tests: `tests/test_mcp_registry.py`, `tests/test_chat_orchestrator.py`, `tests/test_web_chat*.py`
- Comandos: `LLM_PROVIDER=heuristic pytest tests/test_mcp_registry.py tests/test_chat_orchestrator.py -q`

## `database` — Base de datos

PostgreSQL async, modelos SQLAlchemy del esquema app.* y migraciones Alembic.

- Raíces: `db/`
- Entradas: `db/models/`, `db/session.py`, `db/alembic/versions/`
- Docs: `docs/db.md`
- Tests: `tests/test_*migra*.py`
- Comandos: `alembic -c db/alembic.ini heads`

## `deploy-ops` — Despliegue y operación

Compose prod (lasfocas) y dev (lasfocasdev), Dockerfiles, env de ejemplo, arranque y runbooks.

- Raíces: `deploy/`, `Start`, `scripts/start_dev.sh`, `scripts/build_base.sh`
- Entradas: `deploy/compose.yml`, `deploy/docker-compose.dev.yml`, `deploy/docker/base.Dockerfile`
- Docs: `docs/entorno_dev.md`, `docs/despliegue_produccion.md`, `docs/Seguridad.md`
- Comandos: `docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev ps`
