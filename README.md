# Nombre de archivo: README.md
# Ubicación de archivo: README.md
# Descripción: Puerta de entrada al proyecto: qué es, cómo está armado y a qué documento ir para cada tema

# LAS-FOCAS

Sistema operativo de la infraestructura de fibra óptica de Metrotel: informes SLA y de
Repetitividad, inventario FO sincronizado desde Cromo Red, panel web (SPA), bot de Slack,
chatbot con herramientas MCP y una API para otras áreas.

> Este README es una puerta de entrada corta. El detalle vive en `docs/`; para orientarse por
> dominio, empezar por [docs/REPOSITORY_MAP.md](docs/REPOSITORY_MAP.md). Las reglas para agentes
> IA están en [AGENTS.md](AGENTS.md) (y [CLAUDE.md](CLAUDE.md) para Claude Code).

## Qué hace

| Área | Qué hay | Documento |
|---|---|---|
| Panel web | SPA Vue 3 + Vite + TypeScript servida por FastAPI (`web/`), con sesión y CSRF | [docs/web.md](docs/web.md) |
| Informes | SLA (incluido el informe de consumo), Repetitividad y alarmas Ciena en DOCX | [docs/informes/](docs/informes/) |
| Inventario FO | Ingesta de Cromo Red (cámaras, botellas, cables, ODF), tracking de servicios | [docs/modulo_ingesta_cromo.md](docs/modulo_ingesta_cromo.md), [docs/infra.md](docs/infra.md) |
| FO Monitor | Verificación PRE/POST de servicios por cable y mapa | [docs/fo_monitor.md](docs/fo_monitor.md) |
| Slack | Bot de cables/servicios/track, baneos e ingresos (`modules/slack_baneo_notifier/`) | [docs/slack_app_cables.md](docs/slack_app_cables.md), [docs/bot.md](docs/bot.md) |
| Chatbot y MCP | Chat del panel, clasificación de intención (`nlp_intent/`) y herramientas MCP | [docs/chatbot.md](docs/chatbot.md), [docs/mcp.md](docs/mcp.md), [docs/nlp/intent.md](docs/nlp/intent.md) |
| API | API interna con API key y API v1 OAuth2 (`client_credentials`) para otras áreas | [docs/api.md](docs/api.md) |

## Arquitectura

Servicios de `deploy/compose.yml` (producción, proyecto `lasfocas`):

```
usuarios ──► web :8080 (FastAPI + SPA) ──► api :8001→8000 (FastAPI)
               │                               │
               ├──► nlp_intent :8100           ▼
               ├──► redis :6379 ◄──────┐    postgres :5432 ◄── todos los servicios con datos
               └──► docker-socket-proxy :2375 (red interna aparte; el panel gestiona el worker de Slack)

workers:  cromo_worker (ingesta Cromo Red)          ─┐
          botellas_recalculo_worker (duplicados)     ├─ usan redis
          slack_baneo_worker (bot de Slack)         ─┘
          fo_monitor_worker (FO Monitor, sólo postgres)
otros:    office :8090 (LibreOffice/UNO)
          pgadmin :5050 (profile pgadmin)
```

- **Redis es obligatorio** (colas y estado de `cromo_worker`, `botellas_recalculo_worker`,
  `slack_baneo_worker` y el panel). No hay Celery ni RQ.
- Sólo `web` (`172.18.208.162:8080`), `api` (8001), `postgres` y `pgadmin` (estos dos en
  `127.0.0.1`) publican puertos; el resto usa `expose`.
- **PDF de informes**: hoy los informes se entregan en DOCX. La conversión a PDF usa `soffice` en
  el propio contenedor y las imágenes `web`/`api` no traen LibreOffice; el `/convert` de `office`
  es un placeholder. Ver [docs/office_service.md](docs/office_service.md).

Stack: Python 3.11, FastAPI, SQLAlchemy + Alembic, PostgreSQL 16, Redis 7, Vue 3, Docker Compose.

## Estructura

```
api/            FastAPI interna + API v1 (OAuth2)
web/            backend del panel (web/app/main.py + web/app/routers/) y SPA (web/frontend/)
core/           configuración, logging, parsers, repositorios, servicios, MCP y chatbot
modules/        informes, utilidades comunes y workers (cromo, botellas, fo_monitor, slack)
db/             modelos SQLAlchemy y migraciones Alembic
nlp_intent/     microservicio de intención
office_service/ microservicio LibreOffice
deploy/         compose de prod y dev, Dockerfiles, env de ejemplo
scripts/        operación, diagnóstico y tooling de agentes
Templates/      plantillas DOCX de los informes
docs/           documentación (empezar por REPOSITORY_MAP.md)
tests/          pytest
```

## Entornos

| | Producción | Desarrollo |
|---|---|---|
| Compose | `deploy/compose.yml` (proyecto `lasfocas`) | `deploy/docker-compose.dev.yml` (proyecto `lasfocasdev`) |
| Panel web | `172.18.208.162:8080` | `localhost:8090` |
| API docs | `:8001/docs` | `:8011/docs` |
| PostgreSQL | `127.0.0.1:5432` | `127.0.0.1:5433` |
| Cómo se levanta | runbook [docs/despliegue_produccion.md](docs/despliegue_produccion.md) | `./scripts/start_dev.sh`, ver [docs/entorno_dev.md](docs/entorno_dev.md) |

Siempre con `--env-file`: `docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev ...`.
La configuración de ejemplo está en `deploy/env.sample` (prod) y `deploy/env.dev.sample` (dev); los
secretos van como Docker Secrets en `.secrets/` (ver [docs/Seguridad.md](docs/Seguridad.md)). No
copiar valores de ejemplo a un entorno real.

Verificación rápida (sin credenciales):

```bash
curl -sS http://localhost:8001/health                 # API (prod)
curl -sS http://172.18.208.162:8080/health/version    # versión de build del panel
```

`/db-check` y el resto de la API interna exigen API key (`Authorization: Bearer` o `X-API-Key`);
ver [docs/api.md](docs/api.md).

## Desarrollo

```bash
source .venv/bin/activate
LLM_PROVIDER=heuristic pytest -q        # sin llamadas reales a LLM
ruff check .
```

- Cada tarea trabaja en una rama efímera y un worktree propio (`scripts/agent_worktree.py start`);
  prohibido commitear directo en `dev` o `main`. Detalle en
  [docs/arquitectura_agentes_worktrees.md](docs/arquitectura_agentes_worktrees.md).
- **CI**: `.github/workflows/ci.yml` corre **sólo a mano** (`workflow_dispatch`). El control
  efectivo es el gate local de `agent_worktree.py ready` (ruff + tests focales + `vue-tsc`).
- PRs diarios en `docs/PR/YYYY-MM-DD.md`; cierres de sesión en `docs/cierres/`.

## Licencia

MIT: libre uso/modificación con aviso de copyright.
