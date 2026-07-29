# Nombre de archivo: CLAUDE.md
# Ubicación de archivo: CLAUDE.md
# Descripción: Contexto y comandos específicos para Claude Code en LAS-FOCAS

# LAS-FOCAS — Claude Code

Sistema operativo de infraestructura de fibra óptica de Metrotel: informes SLA/Repetitividad, chatbot con MCP, bot Telegram, panel web y búsqueda de infraestructura FO.

> Las convenciones de código, arquitectura, build/test, gotchas, seguridad y documentación fuente están en `AGENTS.md`. Este archivo agrega lo exclusivo de Claude Code: comandos slash, catálogo de agentes y catálogo de skills.

---

## Comandos Claude Code

Invocar con `/nombre-comando [argumentos opcionales]`.

| Comando | Propósito | Argumento útil |
|---|---|---|
> Comandos que invocan Python (pytest, alembic, pip-audit) asumen que el virtualenv `.venv/` está activo. Activar con `source .venv/bin/activate` si no lo está.

| `/repo-updater` | Audita diff, actualiza docs/PR y docs temáticas, genera commit técnico y hace push a `dev` | alcance o contexto del cambio |
| `/generar-pr-diario` | Crea o actualiza `docs/PR/YYYY-MM-DD.md` con cambios, comandos ejecutados, impacto y riesgos | fecha `YYYY-MM-DD` (por defecto hoy) |
| `/mantenimiento-disco` | Diagnostica uso de disco/Docker/logs y ejecuta limpieza segura con confirmación | umbrales opcionales (disco %, logs MB) |
| `/migracion-alembic` | Crea migración Alembic reversible (autogenerate o manual), valida y aplica | descripción del cambio de esquema |
| `/nuevo-modulo` | Andamia módulo SPA Vue 3 completo: vista, componentes, composable, API client y ruta | nombre del módulo y objetivo funcional |
| `/revisar-seguridad` | Auditoría integral: secretos, CVEs de dependencias, SAST, red/contenedores | alcance (`full`, `secrets`, `dependencies`, etc.) |
| `/crear-skill` | Crea o evoluciona skills/agentes/prompts del ecosistema agéntico con stack y seguridad obligatorios | objetivo y alcance de la skill |

---

## Agentes Especializados

Definidos en `.github/agents/`. Cada agente tiene dominio, herramientas y handoffs declarados.

| Agente | Dominio | Scope principal | Handoffs |
|---|---|---|---|
| `api` | FastAPI async | Endpoints REST, Pydantic, OpenAPI, healthchecks | db, testing, security |
| `web` | Vue 3 + Vite + TypeScript | SPA, Vue Router, WebSocket, sesión/CSRF | api, mcp-chatbot, security |
| `db` | PostgreSQL async | SQLAlchemy, sesiones, Alembic, esquema `app.*` | api, docker |
| `bot` | Telegram aiogram 3.x | Handlers, FSM, filtros, teclados | nlp, testing, mcp-chatbot |
| `nlp` | Clasificación de intención | Providers heurístico/OpenAI/Ollama, 6 intents | mcp-chatbot, bot |
| `mcp-chatbot` | Model Context Protocol | MCPRegistry, ChatOrchestrator, streaming, tools | nlp, reports, web |
| `infra` | Infraestructura FO Metrotel | Cámaras, rutas Ciena, mapas estáticos | db, api, reports |
| `reports` | Informes SLA y Repetitividad | Plantillas DOCX/PDF, builders, procesadores | office, db, testing |
| `office` | LibreOffice headless | Conversión DOCX/XLSX/PPTX→PDF, API puerto 8090 | reports, docker |
| `docker` | Infraestructura de contenedores | Compose, Dockerfiles, redes, healthchecks | testing, db |
| `security` | Auditoría safe-by-design | Secretos, SAST, deps, CORS/XSS en FastAPI/Vue 3 | web, api, db |
| `testing` | pytest y cobertura | Fixtures, mocks, 60% cobertura mínima, CI | api, bot, reports |
| `skill-generator` | Arquitecto meta-agéntico | Crea agentes/prompts/skills (solo reglas, no app code) | — |

**Intents NLP definidos:** `informe_sla`, `informe_repetitividad`, `buscar_infraestructura`, `saludo`, `ayuda`, `desconocido`

**Herramientas MCP definidas:** `InformeRepetitividad`, `GenerarMapaGeo`, `CompararTrazas`, `ConvertirDoc`, `RegistrarNotion`

---

## Skills Disponibles

Definidas en `.github/skills/` (fuente de verdad) y en `.codex-skills/skills/` (formato OpenAI Codex).

| Skill | Propósito | Guardrail crítico |
|---|---|---|
| `dev-workflow` | Validación obligatoria antes de cualquier cambio | Rama `dev`, compose dev, nunca push a `main` |
| `frontend-spa-architecture` | Verifica entry point, router activo y archivos huérfanos del SPA | Usar antes de agregar rutas o vistas en `src/router/index.ts` |
| `docker-cleanup` | Limpia imágenes/contenedores/cache Docker | Nunca `docker volume prune` |
| `docker-rebuild` | Reconstruye servicios con compose correcto | Versiones fijas, no tocar `postgres_data` |
| `disk-analysis` | Diagnóstico de espacio con umbrales | <70% OK, 70-85% warn, >85% crítico |
| `logs-cleanup` | Trunca logs proyecto y contenedores | No limpiar si hay errores activos |
| `temp-cleanup` | Elimina `__pycache__`, bytecode, caches de tools | Confirmar antes de `devs/output/` |
| `secret-detection` | Detecta credenciales expuestas con ripgrep | Nunca mostrar secreto completo |
| `secrets-rollout` | Migra/rota Docker Secrets file-based en dev y prod | `Dev_` solo en dev; nunca password como argumento de shell |
| `dependency-audit` | `pip-audit` + `npm audit` para CVEs | No recomendar `latest` |
| `sast-analysis` | Revisión estática FastAPI/Vue 3 | Seguir flujo de datos hasta sink |
| `security-scan` | Coordinador integral de auditoría | secret-detection + dependency-audit + sast-analysis |
| `pytest-focas` | Tests con mocks, fixtures async | `LLM_PROVIDER=heuristic` para evitar llamadas reales |
| `alembic-migrations` | Migraciones DB reversibles | Siempre implementar `downgrade()` |
| `db-mcp-postgres` | Consultas read-only via MCP al esquema `app.*` | Solo `SELECT`; migraciones → Alembic |
| `libreoffice-convert` | DOCX/XLSX→PDF via API puerto 8090 | Timeout 30-60s, máx 50 MB |
| `repo-updater` | Commits técnicos a `dev` con auditoría de docs | Nunca `git push origin main` |
| `repo-update` | Legacy — redirige a `repo-updater` | — |
| `skill-generator` | Crea nuevas skills con stack Vue 3 + FastAPI | Inyección obligatoria de stack y seguridad |

---

## Entornos Agénticos

| Entorno | Plataforma | Ubicación |
|---|---|---|
| Claude Code | **Este entorno** | `CLAUDE.md` + `.claude/commands/` |
| GitHub Copilot / VS Code | Agentes, prompts, skills | `.github/agents/`, `.github/prompts/`, `.github/skills/` |
| Gemini CLI | Rules flat | `.gemini/rules/` |
| OpenAI Codex | Skills (formato Codex) | `.codex-skills/skills/` |

**Fuente de verdad para sincronización:** `.github/` → replicar cambios a `.gemini/`, `.codex-skills/` y `.claude/commands/`.
