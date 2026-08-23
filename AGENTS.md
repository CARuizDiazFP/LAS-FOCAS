# Nombre de archivo: AGENTS.md
# Ubicación de archivo: AGENTS.md
# Descripción: Instrucciones base para Agentes IA en el proyecto LAS-FOCAS

# Project Guidelines

LAS-FOCAS es un sistema modular para informes operativos, chatbot y panel web. Este archivo debe mantenerse breve y útil para cualquier tarea del repo. La documentación detallada vive en `docs/` y las instrucciones especializadas en `.github/agents/`, `.github/prompts/` y `.agentes-comunes/skills/` (con mirrors por plataforma).

## Arquitectura

- `api/`: FastAPI orientada a endpoints REST asíncronos y procesos de ingest/reporting. No mezclar UI aquí.
- `web/`: backend del panel (sesión/autenticación/WebSocket/chat) y frontend SPA en `web/frontend/` con Vue 3 + Vite + TypeScript + CSS modular.
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
- Rama de trabajo habitual: `dev`. Push directo a `main` prohibido desde agentes; los merges a `main` se realizan únicamente por PR revisado.
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
- Cobertura esperada para módulos nuevos: al menos 60%
- Migraciones: `ALEMBIC_URL="..." alembic upgrade head`

## Gotchas

- Existe conflicto potencial entre `api/app` y `web/app`; evitar imports ambiguos y respetar `pytest.ini`.
- Algunos tests y módulos requieren `TESTING=true` antes de importar configuración sensible; revisar patrones existentes en tests.
- El informe SLA depende de la columna U (`Horas Netas Reclamo`) en el Excel legacy; no reintroducir fallbacks a otras columnas.
- La VM y varios defaults asumen la IP `172.18.208.162`; si cambia, revisar configuración y documentación relacionada.
- La topología operativa actual usa proveedores LLM externos vía API; no asumir disponibilidad de Ollama/local LLM salvo trabajo explícito de compatibilidad heredada.

## Seguridad y Operación

- Nunca exponer secretos en código o logs; usar `.env` o secrets de Docker.
- Preferir `expose` sobre `ports`, salvo interfaces públicas necesarias.
- No usar tags `latest` ni dependencias sin pin.
- Aplicar mínimos privilegios y healthchecks cuando corresponda.

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
- PRs diarios: `docs/PR/YYYY-MM-DD.md`
- Documentación privada de la empresa: `docs/Doc Privada/` — **ignorada por git** (ver `.gitignore`), nunca debe commitearse ni subirse al repo
- Ingesta de inventario FO desde Cromo (contexto estructural, sin datos sensibles): `docs/modulo_ingesta_cromo.md`. Modelo de datos y autenticación (privado, no versionado): `docs/Doc Privada/ingesta_cromo.md`

## Agentes y Skills

- Usar agentes de `.github/agents/` cuando el trabajo sea claramente de `api`, `db`, `web`, `bot`, `reports`, `security`, `docker` o `testing`.
- Usar skills de `.agentes-comunes/skills/` como fuente central para workflows repetibles (pytest, alembic, Docker, mantenimiento, sincronización trazable y verificación de arquitectura frontend).
- Mantener mirrors por plataforma (`.github/skills/`, `.gemini/rules/`, `.codex-skills/skills/`, `.claude/skills/`) sincronizados con `.agentes-comunes/skills/`.
- El flujo recursivo SDD/superpowers se mantiene habilitado; optimizar ejecución acotando rondas redundantes (evitar cadenas abiertas de re-review cuando no hay hallazgos nuevos).
- La regla operativa de corte de rondas recursivas está formalizada en `docs/politica_recursion_sdd.md`.
- Para tareas de frontend (agregar rutas, vistas o componentes Vue), usar la skill `frontend-spa-architecture` para verificar el entry point activo y el router unificado antes de escribir código.
- Antes de cerrar cualquier tarea de UI/CSS, usar la skill `nocturne-token-compliance`: audita colores hardcodeados no sólo en la vista tocada sino en todo su árbol de imports (los modales/cards de `components/` repiten el mismo problema por copy-paste), y define cómo verificar el resultado real cuando no hay navegador disponible en la sesión.
- Para revisiones safe-by-design de seguridad, usar `security` junto con `security-scan`, `dependency-audit`, `secret-detection` y `sast-analysis`; priorizar `.env`, `deploy/`, `Keys/`, Docker, red y superficies expuestas.
- Para migrar o rotar Docker Secrets file-based (dev y prod), usar la skill `secrets-rollout`: recreate de a un servicio con verificación de health/DB entre pasos, nunca password como argumento de shell.
- Para trabajar sobre datos ya ingeridos de Cromo Red (`app.cromo_*`), usar la skill `cromo-inventario`. Antes de escribir código nuevo de parseo/ingesta contra Cromo, usar `cromo-diagnostico-real` — el diseño documentado no siempre coincide con el comportamiento real del sistema externo.
- Antes de probar `create_ban`/`lift_ban` o cualquier cascada de estado de `Camara` (jerarquía Cámara→Botella) contra `lasfocasdev-*`, usar la skill `baneo-qa-real` — un servicio de prueba "cualquiera" puede tocar cámaras fuera del grupo objetivo; resolver el blast radius real antes de mutar y revertir sólo vía las funciones reales, nunca `UPDATE` directo.
- El agente `security` se enfoca en APIs y SPAs modernas: XSS en Vue 3, CORS en FastAPI y manejo seguro de tokens/sesiones.
- Para crear nuevos customizations del ecosistema agéntico, usar la tríada `skill-generator` en `.github/agents/skill-generator.agent.md`, `.github/prompts/crear-skill.prompt.md` y `.agentes-comunes/skills/skill-generator/`.
- **Claude Code**: comandos slash disponibles en `.claude/commands/` (`/repo-updater`, `/generar-pr-diario`, `/cierre-sesion`, `/mantenimiento-disco`, `/migracion-alembic`, `/nuevo-modulo`, `/revisar-seguridad`, `/crear-skill`). Catálogo detallado de agentes, skills y comandos en `CLAUDE.md`.
