# Nombre de archivo: CLAUDE.md
# Ubicación de archivo: CLAUDE.md
# Descripción: Contexto y comandos específicos para Claude Code en LAS-FOCAS

# LAS-FOCAS — Claude Code

Sistema operativo de infraestructura de fibra óptica de Metrotel: informes SLA/Repetitividad, chatbot con MCP, bot Telegram, panel web y búsqueda de infraestructura FO.

> Las convenciones de código, arquitectura, build/test, gotchas, seguridad y documentación fuente están en `AGENTS.md`. Este archivo agrega lo exclusivo de Claude Code: comandos slash, catálogo de agentes y catálogo de skills.

---

## Cómo debe trabajar Claude Code en este repositorio

**Claude nunca empieza una tarea modificando directamente el checkout `dev`.** El checkout
principal (`/home/support-focal-01/LAS-FOCAS`) es el **checkout de control/integración**: queda en
`dev` y se usa para crear worktrees, integrar e inspeccionar. El trabajo ocurre en un worktree
propio por tarea.

### Al iniciar cualquier tarea

1. **Detectar si ya pertenece a un agent worktree**:
   ```bash
   python scripts/agent_worktree.py status
   git rev-parse --show-toplevel
   ```
   Si el `toplevel` coincide con el `worktree_path` de un agente registrado, continuar ahí.

2. **Si no pertenece, pedir su workspace** (comando `/iniciar-tarea-agente`, o directo):
   ```bash
   python scripts/agent_worktree.py start \
     --agent claude-api --type feat --task busqueda-camaras
   ```
   ```text
   Agente:   claude-api
   Rama:     feat/claude-api-busqueda-camaras
   Worktree: /home/support-focal-01/LAS-FOCAS-agentes/claude-api-busqueda-camaras
   Base:     origin/dev@ba1cf5e9b55d
   Estado:   active
   ```

3. **Trabajar ahí**: todas las ediciones, tests y commits usan esa ruta como raíz.

4. **Registrar heartbeat** en tareas largas (también renueva los leases propios):
   ```bash
   python scripts/agent_worktree.py heartbeat --agent claude-api
   ```

5. **Adquirir leases sólo cuando corresponde** — nunca para archivos ordinarios:
   ```bash
   python scripts/agent_lock.py acquire "db:migrations" \
     --agent claude-api --reason "migración de inventario"
   python scripts/agent_lock.py release "db:migrations" --agent claude-api
   ```
   Recursos canónicos: `skill:<nombre>`, `agent:<nombre>`, `docs:AGENTS.md`, `governance:claude`,
   `db:migrations`, `env:python-dependencies`, `env:docker-compose`, `git:worktree-lifecycle`,
   `git:integrate-dev`.

6. **Cerrar con `/cierre-sesion`**, que ejecuta `sync` → `ready` → `integrate` → `finish` →
   `cleanup`. La integración a `dev` está serializada por `git:integrate-dev`: mientras Claude
   integra, las demás sesiones siguen trabajando sin interrupción.

### Ejemplo real: dos sesiones en paralelo

```bash
# Sesión 1 (API)
python scripts/agent_worktree.py start --agent claude-api --type feat --task busqueda-camaras
cd /home/support-focal-01/LAS-FOCAS-agentes/claude-api-busqueda-camaras

# Sesión 2 (frontend), al mismo tiempo y sin coordinación previa
python scripts/agent_worktree.py start --agent claude-web --type feat --task mapa-camaras
cd /home/support-focal-01/LAS-FOCAS-agentes/claude-web-mapa-camaras

# Cada una ve sólo lo suyo
git -C ../claude-api-busqueda-camaras status --porcelain
git -C ../claude-web-mapa-camaras   status --porcelain
python scripts/agent_worktree.py list
```

### Qué está prohibido

- Trabajar en el checkout de control o dejarlo fuera de `dev`.
- `git reset --hard`, `git clean -fd`, `git checkout -- .`, `git restore .`, `git push --force`,
  `git worktree remove --force` y `git branch -D` de forma automática.
- Eliminar un worktree con cambios sin confirmar, o la rama de otro agente con commits no
  integrados.
- Tratar un agente `stale` como descartable: conserva rama, worktree y cambios.

Referencia completa: `docs/arquitectura_agentes_worktrees.md`. Skill operativa: `agent-worktree`.

---

## Comandos Claude Code

Invocar con `/nombre-comando [argumentos opcionales]`.

| Comando | Propósito | Argumento útil |
|---|---|---|
> Comandos que invocan Python (pytest, alembic, pip-audit) asumen que el virtualenv `.venv/` está activo. Activar con `source .venv/bin/activate` si no lo está.

| `/iniciar-tarea-agente` | Crea (o confirma) el worktree y la rama efímera propios de esta sesión antes de tocar el repo | `agent-id tipo task-slug` |
| `/estado-agentes` | Muestra agentes activos, worktrees, leases y handoffs; `doctor` diagnostica inconsistencias | `doctor` o un `agent_id` |
| `/handoff-agente` | Traspasa la tarea a otro agente conservando rama, worktree, leases y contexto | `origen → destino: siguiente paso` |
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

> **Para que sean invocables por el `Skill` tool de Claude Code hace falta un mirror en
> `.claude/skills/<nombre>/SKILL.md`** — no alcanza con existir en `.agentes-comunes/skills/`.
> Descubierto 2026-08-14: `Skill(skill="docker-rebuild")` falló con "Unknown skill" pese a estar
> catalogada acá, porque `.claude/skills/` no existía (ver `docs/cierres/2026-08-14.md`).
>
> **Cerrado el 2026-09-14**: `scripts/sync_skill_mirrors.py` genera y mantiene los mirrors de las
> cuatro plataformas, así que **todas** las skills de la tabla son invocables. No hay que copiar
> nada a mano: tras editar una skill en `.agentes-comunes/skills/`, correr
> `scripts/sync_agentes_comunes.sh` (que lo invoca) y verificar con
> `scripts/check_skill_mirror_drift.sh`.

> El flujo recursivo (SDD/superpowers) se mantiene habilitado para trabajos largos; optimizar evitando re-reviews en cascada cuando el delta no introduce hallazgos nuevos.

> Política operativa formal de corte de rondas: `docs/politica_recursion_sdd.md`.

| Skill | Propósito | Guardrail crítico |
|---|---|---|
| `agent-worktree` | Trabajo concurrente aislado: worktree y rama propios por agente, leases por recurso compartido, integración serializada a `dev`, handoff y `doctor` | Nunca borrar un worktree sucio ni la rama de otro agente; el checkout principal se reserva para control/integración |
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
| Claude Code | **Este entorno** | `CLAUDE.md` + `.claude/commands/` (slash commands) + `.claude/skills/` (todas las skills de la tabla, mirroradas automáticamente por `scripts/sync_skill_mirrors.py`) |
| GitHub Copilot / VS Code | Agentes, prompts, skills | `.github/agents/`, `.github/prompts/`, `.github/skills/` |
| Gemini CLI | Rules flat | `.gemini/rules/` |
| OpenAI Codex | Skills (formato Codex) | `.codex-skills/skills/` |

**Fuente de verdad para sincronización:** `.agentes-comunes/skills/` (skills) + `.github/agents/` y `.github/prompts/` (agentes/prompts). Los mirrors de `.github/skills/`, `.gemini/rules/`, `.codex-skills/skills/` y `.claude/skills/` los regenera `scripts/sync_agentes_comunes.sh` (que delega en `scripts/sync_skill_mirrors.py`); `scripts/check_skill_mirror_drift.sh` verifica los cuatro y falla si hay drift. `.claude/commands/` se mantiene a mano: son comandos, no mirrors de skills.
