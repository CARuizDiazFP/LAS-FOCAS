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

| `/repo-updater` | Audita diff, actualiza docs/PR y docs temáticas, genera commit técnico y hace push a la rama efímera activa | alcance o contexto del cambio |
| `/generar-pr-diario` | Crea o actualiza `docs/PR/YYYY-MM-DD.md` con cambios, comandos ejecutados, impacto y riesgos | fecha `YYYY-MM-DD` (por defecto hoy) |
| `/mantenimiento-disco` | Diagnostica uso de disco/Docker/logs y ejecuta limpieza segura con confirmación | umbrales opcionales (disco %, logs MB) |
| `/migracion-alembic` | Crea migración Alembic reversible (autogenerate o manual), valida y aplica | descripción del cambio de esquema |
| `/nuevo-modulo` | Andamia módulo SPA Vue 3 completo: vista, componentes, composable, API client y ruta | nombre del módulo y objetivo funcional |
| `/revisar-seguridad` | Auditoría integral: secretos, CVEs de dependencias, SAST, red/contenedores | alcance (`full`, `secrets`, `dependencies`, etc.) |
| `/crear-skill` | Crea o evoluciona skills/agentes/prompts del ecosistema agéntico con stack y seguridad obligatorios | objetivo y alcance de la skill |
| `/cierre-sesion` | Retrospectiva técnica + evolución agéntica con compuerta de riesgo + auto-merge autónomo de la rama efímera a `dev`, guardada en `docs/cierres/YYYY-MM-DD.md` | palabra clave "Cerrar sesión"/"Cerremos sesión"/"Cierre chat" o alcance/fecha |

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

Definidas en `.agentes-comunes/skills/` (fuente de verdad agnóstica) y espejadas en `.github/skills/` y `.codex-skills/skills/` (formato OpenAI Codex).

> **Para que sean invocables por el `Skill` tool de Claude Code hace falta además un mirror en
> `.claude/skills/<nombre>/SKILL.md`** — no alcanza con existir en `.agentes-comunes/skills/`. Descubierto
> 2026-08-14: `Skill(skill="docker-rebuild")` falló con "Unknown skill" pese a estar catalogada acá,
> porque `.claude/skills/` no existía. `docker-rebuild`, `nocturne-token-compliance`, `cierre-sesion`
> y `dev-workflow` tienen mirror hoy (2026-09-03: `dev-workflow` se agregó junto con el flujo de rama
> efímera obligatoria — antes no era invocable vía `Skill`); el resto de la tabla de abajo **todavía
> no es invocable vía `/nombre-skill` o el tool `Skill` en este entorno** — hay que copiarla a
> `.claude/skills/` (mismo contenido que `.agentes-comunes/skills/`) antes de poder usarla así. Hasta
> entonces, seguir sus procedimientos manualmente vía Bash. Ver `docs/cierres/2026-08-14.md`.

> El flujo recursivo (SDD/superpowers) se mantiene habilitado para trabajos largos; optimizar evitando re-reviews en cascada cuando el delta no introduce hallazgos nuevos.

> Política operativa formal de corte de rondas: `docs/politica_recursion_sdd.md`.

| Skill | Propósito | Guardrail crítico |
|---|---|---|
| `dev-workflow` | Validación obligatoria antes de cualquier cambio | Rama efímera obligatoria por tarea (prohibido commit directo en dev/main), compose dev, nunca push a `main` |
| `frontend-spa-architecture` | Verifica entry point, router activo y archivos huérfanos del SPA | Usar antes de agregar rutas o vistas en `src/router/index.ts` |
| `nocturne-token-compliance` | Audita colores hardcodeados en Vue 3 (vista + árbol de imports) contra `tokens.css`, y cómo verificar sin navegador disponible | Nunca hex/rgba literal para superficie/texto/borde/estado; grepear también los componentes importados, no sólo la vista |
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
| `cromo-inventario` | Consultar/explotar datos ya ingeridos de Cromo Red (`app.cromo_*`) | `jerarquia`/`propietario` siempre `ILIKE`, nunca exacto |
| `cromo-diagnostico-real` | Validar supuestos de ingesta/parseo contra la API o DB real de Cromo | Nunca declarar una fase "correcta" sin diagnóstico contra el sistema real |
| `baneo-qa-real` | Probar create_ban/lift_ban y cascadas de estado de Cámara contra datos reales | Resolver el blast radius completo antes de mutar; revertir sólo vía `aplicar_estado_a_grupo`, nunca `UPDATE` directo |
| `libreoffice-convert` | DOCX/XLSX→PDF via API puerto 8090 | Timeout 30-60s, máx 50 MB |
| `repo-updater` | Commits técnicos a la rama efímera activa con auditoría de docs | Nunca `git push origin main` ni `git push origin dev` directo |
| `repo-update` | Legacy — redirige a `repo-updater` | — |
| `skill-generator` | Crea nuevas skills con stack Vue 3 + FastAPI | Inyección obligatoria de stack y seguridad |
| `cierre-sesion` | Retrospectiva técnica + evolución agéntica con compuerta de riesgo (🔴 detiene y pregunta) + auto-merge autónomo de la rama efímera a `dev` (incluida resolución de conflictos) | Requiere declaración explícita de cierre; sin evidencia no se inventa; ninguna propuesta 🔴 se implementa sin respuesta del usuario |

---

## Entornos Agénticos

| Entorno | Plataforma | Ubicación |
|---|---|---|
| Claude Code | **Este entorno** | `CLAUDE.md` + `.claude/commands/` (slash commands) + `.claude/skills/` (skills invocables — `docker-rebuild`, `nocturne-token-compliance`, `cierre-sesion` y `dev-workflow` mirroradas hoy, ver nota arriba) |
| GitHub Copilot / VS Code | Agentes, prompts, skills | `.github/agents/`, `.github/prompts/`, `.github/skills/` |
| Gemini CLI | Rules flat | `.gemini/rules/` |
| OpenAI Codex | Skills (formato Codex) | `.codex-skills/skills/` |

**Fuente de verdad para sincronización:** `.agentes-comunes/skills/` (skills) + `.github/agents/` y `.github/prompts/` (agentes/prompts) → replicar cambios a `.github/skills/`, `.gemini/`, `.codex-skills/`, `.claude/commands/` y `.claude/skills/` (esta última, agregada 2026-08-14, es la que hace que una skill sea invocable por el tool `Skill` en Claude Code).
