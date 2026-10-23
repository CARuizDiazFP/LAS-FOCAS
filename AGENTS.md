# Nombre de archivo: AGENTS.md
# Ubicación de archivo: AGENTS.md
# Descripción: Instrucciones base para Agentes IA en el proyecto LAS-FOCAS

# Project Guidelines

LAS-FOCAS es un sistema modular para informes operativos, chatbot y panel web. Este archivo debe mantenerse breve y útil para cualquier tarea del repo. La documentación detallada vive en `docs/` y las instrucciones especializadas en `.github/agents/`, `.github/prompts/` y `.agentes-comunes/skills/` (con mirrors por plataforma).

## Arquitectura

- `api/`: FastAPI orientada a endpoints REST asíncronos y procesos de ingest/reporting. No mezclar UI aquí.
- `web/`: backend del panel (sesión/autenticación/WebSocket/chat) y frontend SPA en `web/frontend/` con Vue 3 + Vite + TypeScript + CSS modular.
- Backend de la SPA: `web/app/main.py` (ensamblador: app, middleware, mounts, websockets, `include_router`, catch-all) + `web/app/routers/<dominio>.py` (sesion, informes, chat, admin_datos, servicios, cromo, camaras) + `web/app/comun.py` (auth, CSRF, config y estado compartidos).
- Regla de routers: importan con `from ..comun import ...` y nunca importan `main`; al mover o parchear nombres en tests, parchear el módulo donde se lee.
- Búsqueda y exportación de Cámaras del panel: `core/services/camaras_consulta.py` (smart search) y `core/services/camaras_exportacion.py`. Las variantes `search_camaras*` y `advanced_search_camaras*` (SPA y API interna) y `smart_search_camaras` y `export_cameras` (API interna) se conservan a propósito: tienen poco uso pero siguen operativas; no se borran sin decisión explícita del usuario.
- `bot_telegram/`: bot aiogram que consume flujos y servicios; evitar lógica de negocio duplicada.
- `core/`: configuración, logging, parsers, repositorios y servicios compartidos.
- `modules/`: implementación específica de informes SLA, repetitividad y utilidades comunes.
- `db/`: modelos SQLAlchemy async, sesión y migraciones Alembic.
- `nlp_intent/`: microservicio aislado para clasificación de intención por HTTP.
- `office_service/`: microservicio de LibreOffice headless para conversiones.
- `deploy/`: `compose.yml` (producción) y `docker-compose.dev.yml` (desarrollo). Puertos: postgres 5432, api 8001→8000, web 8080, nlp_intent 8100, office 8090, pgadmin 5050.
- Arquitectura objetivo de nuevas implementaciones: SPA pura con comunicación por API REST (JSON) y WebSocket.

## Convenciones

- Todo archivo modificable debe empezar con este encabezado de 3 líneas:

```python
# Nombre de archivo: <nombre_del_archivo.ext>
# Ubicación de archivo: <ruta_relativa_en_el_proyecto>
# Descripción: <breve_descripción_del_uso_o_función_del_archivo>
```

- Idioma obligatorio: español en código, commits, PRs y documentación.
- Rama de trabajo: ramas efímeras `<tipo>/<slug>` creadas desde `origin/dev` (obligatorio — prohibido commitear directo en `dev`), en un **worktree propio** creado con `scripts/agent_worktree.py start` (convención `<tipo>/<agent-id>-<task-slug>`; ver "Conciencia agéntica y control de concurrencia"). La integración a `dev` es automática al cierre de sesión (`cierre-sesion`) y está serializada por el lease `git:integrate-dev`. Push directo a `main` prohibido desde agentes; los merges a `main` se realizan únicamente por PR revisado.
- Compose de desarrollo: `deploy/docker-compose.dev.yml`. No usar `deploy/compose.yml` en entorno local ni de agentes.
- Mantener límites claros: `api` expone lógica por HTTP, `web` resuelve UI/sesión, `bot_telegram` consume servicios, `nlp_intent` no accede directo a la DB.
- Usar `logging`, no `print()`. Seguir el patrón de `core/logging.py`.
- Mantener type hints y estilos cercanos a PEP 8. Las dependencias se versionan de forma estricta.
- En nuevas APIs y repositorios usar `async/await` y modelos Pydantic para validar entrada/salida.
- Prohibido en desarrollos nuevos: frontend en Vanilla JS, manipulación directa del DOM como patrón principal y templates Jinja para UI moderna.
- No tocar `Legacy/` salvo pedido explícito.

## Build y Test

- Virtualenv: `source .venv/bin/activate` (activar antes de pytest, pip-audit, alembic y scripts Python)
- Arranque principal desde la raíz: `./Start`
- Iteración rápida: `./Start --no-down`
- Rebuild selectivo: `./Start --rebuild-api`, `./Start --rebuild-frontend`
- Fallback Docker: `docker compose -f deploy/compose.yml up -d|build|logs -f`
- Tests: `pytest`, `pytest -v -k "<filtro>"`, `pytest tests/test_sla_module.py`
- Para evitar llamadas reales a LLM en tests: `LLM_PROVIDER=heuristic pytest -q`
- Los tests de integración (`*_real_db.py`, rutas de Servicios) se **saltean solos** si no hay un
  Postgres respondiendo: `pytest` a secas queda verde pero no los corre. Para correrlos de verdad
  contra el Postgres de dev (publicado en `127.0.0.1:5433`, el `5432` es producción):
  `POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_DB=focas_dev POSTGRES_USER=FOCALBOT \
  POSTGRES_PASSWORD="$(cat .secrets/Dev_db_password_v1.txt)" pytest`. El host `postgres` del
  compose no resuelve desde fuera de la red de Docker. Guard: `tests/soporte_postgres_real.py`.
- Cobertura esperada para módulos nuevos: al menos 60%
- **Pruebas focales vs. regresión**: durante la tarea y al cerrar hacia `dev` (`ready`/`integrate`
  de `cierre-sesion`) se corren **sólo las pruebas focales** de los módulos modificados (más
  `bash scripts/check_skill_mirror_drift.sh` si se tocaron skills), para que la ventana del lease
  `git:integrate-dev` sea mínima. La suite regresiva completa, `npm run build` y los builds de
  imágenes se ejecutan **exclusivamente en el despliegue productivo**. Detalle en `pytest-focas`.
- **Gate de calidad local**: `agent_worktree.py ready` corre `ruff` sobre los `.py` cambiados y
  `pytest` sobre los tests focales (`scripts/agentes/calidad.py`, smoke en `config/quality-gate.json`);
  `integrate` rechaza un HEAD que no lo pasó. Reemplaza a la CI de GitHub, que sólo corre a mano
  (sin créditos de Actions). Emergencia auditada: `ready --sin-gate --motivo "..."`.
  Si el cambio toca `.vue`/`.ts` bajo `web/frontend/src`, el gate también corre
  `npm run type-check` (`vue-tsc --noEmit`, script de `web/frontend/package.json`); sin
  `node_modules` lo saltea con motivo explícito ("correr npm ci"), nunca pasa en silencio.
- Lint: `ruff check .` con la config de `pyproject.toml` (E9 + F + C901 ≤ 20). El repo está en 0
  avisos; las 6 funciones que todavía superan complejidad 20 llevan `# noqa: C901 - <motivo>`.
  `except Exception` → errores tipados y `_require_auth` →
  `Depends` quedan fuera hasta decisión explícita (cambian respuestas).
  Código inalcanzable conservado a propósito, hasta decisión del usuario: el "Intento 3" (sin
  números) de `_buscar_camara_intento` en `modules/slack_baneo_notifier/camara_search.py`. La rama
  `missing_files` del informe SLA se quitó el 2026-10-23 por decisión del usuario.
- Migraciones: `ALEMBIC_URL="..." alembic upgrade head`

## Gotchas

- Existe conflicto potencial entre `api/app` y `web/app`; evitar imports ambiguos y respetar `pytest.ini`.
- Algunos tests y módulos requieren `TESTING=true` antes de importar configuración sensible; revisar patrones existentes en tests.
- El informe SLA depende de la columna U (`Horas Netas Reclamo`) en el Excel legacy; no reintroducir fallbacks a otras columnas.
- La VM y varios defaults asumen la IP `172.18.208.162`; si cambia, revisar configuración y documentación relacionada.
- La topología operativa actual usa proveedores LLM externos vía API; no asumir disponibilidad de Ollama/local LLM salvo trabajo explícito de compatibilidad heredada.
- Los headers HTTP son latin-1: un texto en español con tildes dentro de un header (ej. `WWW-Authenticate: Bearer error_description="token inválido"`) rompe la respuesta con `UnicodeDecodeError` en Starlette (real 2026-09-29, lo detectó `TestClient`). Descripciones legibles van en el cuerpo (`detail`); en headers, sólo ASCII.
- Después de un backfill PROV completo (`scripts/servicios_backfill_prov.py`) o de una ingesta del Excel SLA, correr `scripts/servicios_fusionar_por_cadena_prov.py` (dry-run por defecto; `--apply`; idempotente). El backfill no fusiona filas: si otra fila ya tiene el ID nuevo, lo deja como alias. Real (2026-09-30): quedaron 437 pares duplicados y 625 servicios con 404 en la API v1. El ID vigente es el eslabón `INSTALADO` de PROV, no el número más alto (`PENDIENTE CPS`, `ANULADO` y `SOL BAJA` no lo desplazan).
- `text()` + psycopg3: un mismo bind usado a la vez como `varchar` y como `text` (ej. `SET servicio_id = :op` y `WHERE a <> :op` sobre un `unnest` de `varchar[]`) falla con `AmbiguousParameter: inconsistent types deduced`. Solución: `CAST(:op AS varchar)` en cada uso.
- Una columna `JSONB` de SQLAlchemy **sin `none_as_null=True`** guarda el `None` de Python como el
  escalar JSON `'null'`, no como SQL NULL, y `COALESCE(col, '[]'::jsonb)` **no** lo cubre:
  `jsonb_array_elements_text` corta la query entera con `cannot extract elements from a scalar`. El
  guard que cubre todos los casos es `CASE WHEN jsonb_typeof(col) = 'array' THEN col ELSE '[]'::jsonb END`
  (real 2026-09-19: 176 filas de `app.cromo_odfs` en dev y en prod). Antes de confiar en un
  `COALESCE` sobre JSONB, medir con `SELECT jsonb_typeof(col), count(*) ... GROUP BY 1`.

- Un `docker exec` cortado (límite de tiempo de una tarea en segundo plano del agente) **no** mata el proceso del contenedor. Las corridas largas se lanzan con `setsid nohup ... &`, y antes de relanzar se confirma en la base que la anterior dejó de escribir (real 2026-10-01: dos altas de PROV en paralelo). Detalle en `docs/despliegue_produccion.md`, paso 7.
- `Logs/` (y `Logs/dev/`) no se lee por defecto (ver "Contexto y tokens" → Acceso a Logs Bajo Demanda). Todo servicio Python loguea con `core/logging.py::setup_logging` (archivo `Logs/<servicio>.log` borrable en uso, buffer de ~2 s); tras tocar compose o un entrypoint, verificar con `python scripts/logs_verificar.py --entorno dev`.

## Contexto y tokens

- **Mapa canónico primero**: antes de cualquier búsqueda global (grep/glob sobre todo el repo), leer
  `docs/REPOSITORY_MAP.md` (≤ 8 KiB), identificar el dominio de la tarea y buscar sólo en sus
  raíces. El mapa se genera desde `config/repository-map.json` con
  `python scripts/generate_repository_map.py --write`; si se agregan o mueven rutas de un dominio,
  actualizar el manifiesto y regenerar (`--check` falla si quedó vencido o si una ruta no existe).
- **Context-Splitting por dominio**: un contexto de trabajo carga un solo dominio a la vez —
  `api`, `core/services/cromo` (infra FO), `core/sla*` (informes), `web/frontend` (SPA),
  `bot_telegram`/`modules/slack_baneo_notifier` (bots), `db/alembic` (esquema) y gobernanza
  (skills, agentes, scripts de agentes). Si la tarea cruza dominios, resolver cada parte por
  separado (o con un subagente por dominio) en vez de cargar todo junto.
- **Acceso a Logs Bajo Demanda**: `Logs/` y `*.log` están excluidos del indexado de todos los
  clientes. Sólo se leen en tareas de diagnóstico o limpieza (skill `logs-cleanup`) y siempre de
  forma puntual: `tail -n <N>`, `grep -m <N>`, rangos de líneas o filtro por hora. Nunca `cat`
  completo ni lectura recursiva.
- **Matriz unificada de exclusión**: `.geminiignore`, `.copilotignore`, `.cursorignore` y
  `.aiderignore` tienen el mismo contenido (entornos, `node_modules`/`dist`, `Logs/`, secretos y
  `.env*`, `Templates/*.docx`, `tests/fixtures/`, `docs/cierres/`, `docs/PR/`,
  `docs/superpowers/plans|specs/`). Al cambiar uno, cambiar los cuatro. Algunos clientes (p. ej.
  Copilot) aplican además la exclusión desde la configuración de la organización.
- **Skills bajo demanda**: `.gemini/rules/skill-*.md` son adaptadores de ≤ 15 líneas que apuntan a
  `.agentes-comunes/skills/<n>/SKILL.md`; la skill completa se lee sólo cuando la tarea activa sus
  `triggers`/`globs`. Para Superpowers, usar el índice de una línea `docs/superpowers/CATALOG.md`
  (las skills locales prevalecen) y no cargar los manifiestos completos.

## Seguridad y Operación

- Nunca exponer secretos en código o logs; usar `.env` o secrets de Docker.
- Preferir `expose` sobre `ports`, salvo interfaces públicas necesarias.
- No usar tags `latest` ni dependencias sin pin.
- Aplicar mínimos privilegios y healthchecks cuando corresponda.
- **Recursos Docker efímeros**: todo contenedor, red o volumen temporal creado en una sesión se
  etiqueta con `lasfocas.lifecycle=ephemeral` y `lasfocas.session=<agent_id>`, y al cierre se borra
  **por ID exacto** (`docker container rm -v <id>`, `docker network rm <id>`, `docker volume rm
  <nombre>`) tras comprobar mounts y consumidores. Nunca `docker system prune` ni
  `docker volume prune` para esto.
- **Retención de imágenes en producción**: por servicio se conservan sólo la imagen activa
  (`current`, `lasfocas-<servicio>:latest`) y un único `rollback` inmediato validado
  (`lasfocas-<servicio>:rollback`). Cada despliegue rota `current -> rollback` y retira el rollback
  desplazado por ID exacto, sin `prune`. Procedimiento en la skill `docker-cleanup`.
- El servicio `api` tiene **dos superficies de autenticación que no se mezclan**: rutas internas con `require_api_key` (`api/app/security.py`, la usa la web) y `/api/v1/*` para otras áreas con OAuth2 `client_credentials` (`require_oauth_token(scope)` de `api/app/oauth.py`, scopes `servicios:read`/`cables:read`). Un endpoint nuevo para terceros va bajo `/api/v1` con su scope, nunca detrás de la API key. Referencia: `docs/api.md`, sección "API v1".

## Documentación Fuente

- Seguridad: `docs/Seguridad.md`
- Decisiones técnicas: `docs/decisiones.md`
- API: `docs/api.md`
- DB: `docs/db.md`
- Bot: `docs/bot.md`
- Chatbot y MCP: `docs/chatbot.md`, `docs/mcp.md`
- Web: `docs/web.md`
- Informes: `docs/informes/sla.md`, `docs/informes/repetitividad.md`, `docs/informes/alarmas_ciena.md`
- NLP: `docs/nlp/intent.md`
- Office service: `docs/office_service.md`
- Infraestructura: `docs/infra.md`
- Concurrencia multi-agente (worktrees, leases, integración serializada): `docs/arquitectura_agentes_worktrees.md`
- PRs diarios: `docs/PR/YYYY-MM-DD.md`
- Documentación privada de la empresa: `docs/Doc Privada/` — **ignorada por git** (ver `.gitignore`), nunca debe commitearse ni subirse al repo
- Ingesta de inventario FO desde Cromo (contexto estructural, sin datos sensibles): `docs/modulo_ingesta_cromo.md`. Modelo de datos y autenticación (privado, no versionado): `docs/Doc Privada/ingesta_cromo.md`

## Agentes y Skills

- Usar agentes de `.github/agents/` cuando el trabajo sea claramente de `api`, `db`, `web`, `bot`, `reports`, `security`, `docker` o `testing`.
- Usar skills de `.agentes-comunes/skills/` como fuente central para workflows repetibles (pytest, alembic, Docker, mantenimiento, sincronización trazable y verificación de arquitectura frontend).
- Mantener mirrors por plataforma (`.github/skills/`, `.claude/skills/`, `.agents/skills/`, `.gemini/rules/`, `.codex-skills/skills/`) sincronizados con `.agentes-comunes/skills/`.
- `python scripts/audit_agentic_environment.py` audita de forma determinista los contratos del entorno (archivos de gobernanza y exclusión, mapa vigente, frontmatter de skills, contrato de `cierre-sesion`, drift de mirrors); sale 1 ante un contrato roto y avisa (`warning:stale_lease:*`, `warning:stale_agent:*`) sin bloquear.
- El flujo recursivo SDD/superpowers se mantiene habilitado; optimizar ejecución acotando rondas redundantes (evitar cadenas abiertas de re-review cuando no hay hallazgos nuevos).
- La regla operativa de corte de rondas recursivas está formalizada en `docs/politica_recursion_sdd.md`.
- **Antes de empezar cualquier tarea**, usar la skill `agent-worktree`: crea el worktree y la rama propios del agente, define cuándo hace falta un lease y cómo integrar sin pisar a otras sesiones.
- Para tareas de frontend (agregar rutas, vistas o componentes Vue), usar la skill `frontend-spa-architecture` para verificar el entry point activo y el router unificado antes de escribir código.
- Antes de cerrar cualquier tarea de UI/CSS, usar la skill `nocturne-token-compliance`: audita colores hardcodeados no sólo en la vista tocada sino en todo su árbol de imports (los modales/cards de `components/` repiten el mismo problema por copy-paste), y define cómo verificar el resultado real cuando no hay navegador disponible en la sesión.
- Para revisiones safe-by-design de seguridad, usar `security` junto con `security-scan`, `dependency-audit`, `secret-detection` y `sast-analysis`; priorizar `.env`, `deploy/`, `Keys/`, Docker, red y superficies expuestas.
- Para migrar o rotar Docker Secrets file-based (dev y prod), usar la skill `secrets-rollout`: recreate de a un servicio con verificación de health/DB entre pasos, nunca password como argumento de shell.
- Para trabajar sobre datos ya ingeridos de Cromo Red (`app.cromo_*`), usar la skill `cromo-inventario`. Antes de escribir código nuevo de parseo/ingesta contra Cromo, usar `cromo-diagnostico-real` — el diseño documentado no siempre coincide con el comportamiento real del sistema externo.
- Antes de probar `create_ban`/`lift_ban` o cualquier cascada de estado de `Camara` (jerarquía Cámara→Botella) contra `lasfocasdev-*`, usar la skill `baneo-qa-real` — un servicio de prueba "cualquiera" puede tocar cámaras fuera del grupo objetivo; resolver el blast radius real antes de mutar y revertir sólo vía las funciones reales, nunca `UPDATE` directo.
- El agente `security` se enfoca en APIs y SPAs modernas: XSS en Vue 3, CORS en FastAPI y manejo seguro de tokens/sesiones.
- Para crear nuevos customizations del ecosistema agéntico, usar la tríada `skill-generator` en `.github/agents/skill-generator.agent.md`, `.github/prompts/crear-skill.prompt.md` y `.agentes-comunes/skills/skill-generator/`.
- **Claude Code**: comandos slash disponibles en `.claude/commands/` (`/repo-updater`, `/generar-pr-diario`, `/cierre-sesion`, `/mantenimiento-disco`, `/migracion-alembic`, `/nuevo-modulo`, `/revisar-seguridad`, `/crear-skill`). Catálogo detallado de agentes, skills y comandos en `CLAUDE.md`.

## Conciencia agéntica y control de concurrencia

El ecosistema multi-agente es un sistema concurrente. El aislamiento se resuelve en
capas distintas y complementarias; la referencia completa es
`docs/arquitectura_agentes_worktrees.md`.

### Regla base: un agente = una tarea = una rama = un worktree

- Las tareas concurrentes normales **se aíslan físicamente mediante Git worktrees**, no
  con locks. Cada agente trabaja en su propio working tree, con su propio index, su
  propio `HEAD` y su propia rama efímera. Un `git switch`, `git add`, `git stash` o
  commit de un agente no afecta el directorio de ningún otro.
- El worktree y la rama se crean con
  `python scripts/agent_worktree.py start --agent <id> --type <tipo> --task <slug>`;
  la rama resultante es `<tipo>/<agent-id>-<task-slug>`.
- **El checkout principal se reserva para control/integración**: permanece en `dev` y se
  usa para crear o quitar worktrees, integrar, inspeccionar y coordinar. No es el
  working tree habitual de ningún agente de desarrollo.
- **No existe un lock global sostenido durante toda la tarea.** Dos agentes editando
  `api/foo.py` y `web/bar.vue` trabajan en paralelo sin tomar ningún lease.

### Los leases complementan a los worktrees, no los reemplazan

- Un lease se toma **sólo** para recursos que ningún worktree puede aislar: skills y sus
  mirrors, documentos de gobernanza, migraciones, el venv compartido, el stack Docker.
  Formato `<clase>:<nombre>`; los canónicos son `skill:<nombre>`, `agent:<nombre>`,
  `docs:AGENTS.md`, `governance:claude`, `db:migrations`, `env:python-dependencies`,
  `env:docker-compose`, `git:worktree-lifecycle` y `git:integrate-dev`.
- Ciclo: `acquire` → `heartbeat` → `edit` → `release`
  (`python scripts/agent_lock.py acquire "<recurso>" --agent <id> --reason "<motivo>"`).
- Si el recurso ya tiene dueño con lease vigente, el segundo agente **no sobrescribe**:
  reintenta, delega o pide handoff formal. Robar un lease vigente exige `--force`
  explícito y queda auditado.
- Un lease vencido se readquiere con `acquire` tras verificar el estado real del
  recurso. Un `heartbeat` **no revive** un lease vencido.
- El lock nunca restringe la lectura: sólo la escritura concurrente y el handoff
  conflictivo sobre el mismo recurso.

### Sólo la integración a `dev` se serializa

- `dev` se modifica exclusivamente durante la integración, bajo el lease
  `git:integrate-dev` (`python scripts/agent_worktree.py integrate --agent <id>`).
- Mientras un agente integra, los demás siguen desarrollando en sus worktrees sin
  interrupción. Lo único serializado es la ventana de escritura sobre `dev`.
- Antes de integrar, cada agente incorpora `origin/dev` a su rama **dentro de su propio
  worktree** (`sync`) y resuelve ahí cualquier conflicto.

### El runtime de coordinación vive fuera del historial Git

- Estado compartido: `<git-common-dir>/las-focas-agents/agent_state.sqlite3`
  (`git rev-parse --git-common-dir`). Es visible desde todos los linked worktrees,
  sobrevive a los cambios de rama y **no se versiona nunca**.
- Modela `agent_id`, `task_id`, `status`, `branch`, `worktree_path`, `started_at`,
  `heartbeat_at`, `last_activity_at`; los leases con `resource`, `owner`, `scope`,
  `lease_expires_at` y `heartbeat_at`; los handoffs con `next_action` y `blocked_on`; y
  una bitácora de eventos. No se guardan secretos.
- El mismo principio de serialización que la capa de negocio ya aplica con
  `pg_advisory_xact_lock` en `core/services/camara_hierarchy_service.py`, trasladado a
  la capa de gobernanza.

### Seguridad y recuperación

- Prohibido ejecutar automáticamente `git reset --hard`, `git clean -fd`,
  `git checkout -- .`, `git restore .`, `git push --force` o
  `git worktree remove --force` sobre trabajo no demostrado como descartable.
- Un worktree con `git status --porcelain` no vacío **nunca** se elimina
  automáticamente. Las ramas se borran con `git branch -d`, nunca con `-D`.
- Un agente `stale` (sin heartbeat dentro del TTL) conserva su rama, su worktree y sus
  cambios: `stale` es una señal, no una acción destructiva.
- Ante cualquier inconsistencia (worktree sin registro, registro sin worktree, rama
  desalineada, integración interrumpida): `python scripts/agent_worktree.py doctor`,
  que diagnostica y **no corrige**.

### Puertos y entorno propios por worktree

- `agent_worktree.py start` reserva un offset de puertos (1..90, `--offset N` o el menor libre)
  y crea una **copia privada** de `.env.dev` (0600) con `API_PORT`, `WEB_PORT`, `VITE_PORT`,
  `OFFICE_PORT`, `NLP_PORT` = base + offset, `VITE_API_BASE_URL`, `LAS_FOCAS_AGENT_WORKTREE=1` y
  `LAS_FOCAS_PORT_OFFSET`. Editar esa copia no afecta a otros worktrees. `.venv`, `.env`,
  `.secrets` y `Logs` siguen siendo symlinks al control.
- Los puertos son para procesos locales (uvicorn, vite). El stack compose dev sigue siendo único
  y compartido (`env:docker-compose`).
- `cleanup` no remueve un worktree con procesos vivos dentro ni con archivos ignorados que no sean
  runtime conocido (reportes `.docx`/`.xlsx`, dumps): sale 1 y los lista.

### Cierre y continuidad

- Al cerrar, todo agente deja su estado en `finished` o `handoff` y libera sus leases.
  El flujo completo está en la skill `cierre-sesion`.
- Si una tarea queda bloqueada o interrumpida, se emite un handoff explícito
  (`agent_worktree.py handoff --from <a> --to <b> --next-action "<paso>"`), que conserva
  rama, worktree, último commit, archivos modificados, leases y bloqueo conocido. El
  ownership no cambia de forma silenciosa: el destino lo acepta con `accept-handoff`.
- Un recurso con dueño activo no se reasigna sin consentimiento explícito o expiración
  del lease.

## Reglas de sincronización de mirrors

- La fuente de verdad de skills es `.agentes-comunes/skills/`.
- Los mirrors de `.github/skills/`, `.claude/skills/`, `.agents/skills/`, `.gemini/rules/` y
  `.codex-skills/skills/` se consideran artefactos derivados y deben sincronizarse tras cada
  cambio relevante. `.gemini/rules/skill-*.md` es un adaptador liviano (≤ 15 líneas, sin cuerpo):
  sus `triggers`/`globs` se editan ahí y el propagador los preserva. En `.claude/skills/`,
  `.agents/skills/` y `.codex-skills/skills/` el frontmatter va **antes** del encabezado de 3
  líneas (excepción a la convención de encabezados): esos clientes sólo leen `name`/`description`
  si el archivo empieza con `---`. El auditor lo verifica.
- La ejecución de `scripts/sync_agentes_comunes.sh` es obligatoria en cambios de skills,
  prompts o agentes que impacten a cualquiera de los mirrors. Regenera `.github/skills/` y delega en
  `scripts/sync_skill_mirrors.py`, que mantiene `.claude/skills/`, `.agents/skills/`,
  `.gemini/rules/` y `.codex-skills/skills/` preservando el frontmatter propio de cada plataforma y reescribiendo los
  enlaces relativos entre skills a la ruta que resuelve en cada una.
- `scripts/check_skill_mirror_drift.sh` verifica todos los mirrors y **falla con código 1** si hay
  drift. Ningún cierre de tarea que toque skills puede terminar con ese check en rojo.
- Si hay drift entre la fuente y los mirrors, el flujo de trabajo debe detenerse y
  corregirse antes de cerrar la tarea.
- Editar una skill o sus mirrors requiere el lease `skill:<nombre>`: la propagación
  toca varios directorios y es exactamente el tipo de recurso que un worktree no aísla.
