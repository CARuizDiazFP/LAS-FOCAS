# Nombre de archivo: AGENTS.md
# Ubicación de archivo: AGENTS.md
# Descripción: Instrucciones base para Agentes IA en el proyecto LAS-FOCAS

# Project Guidelines

LAS-FOCAS es un sistema modular para informes operativos, chatbot y panel web. Este archivo debe mantenerse breve y útil para cualquier tarea del repo. La documentación detallada vive en `docs/` y las instrucciones especializadas en `.github/agents/`, `.github/prompts/` y `.github/skills/`.

## Arquitectura

- `api/`: FastAPI orientada a endpoints REST y procesos de ingest/reporting. No mezclar UI aquí.
- `web/`: panel FastAPI con login, vistas, websocket de chat y disparo de informes.
- `bot_telegram/`: bot aiogram que consume flujos y servicios; evitar lógica de negocio duplicada.
- `core/`: configuración, logging, parsers, repositorios y servicios compartidos.
- `modules/`: implementación específica de informes SLA, repetitividad y utilidades comunes.
- `db/`: modelos SQLAlchemy, sesión y migraciones Alembic.
- `nlp_intent/`: microservicio aislado para clasificación de intención por HTTP.
- `office_service/`: microservicio de LibreOffice headless para conversiones.

## Convenciones

- Todo archivo modificable debe empezar con este encabezado de 3 líneas:

```python
# Nombre de archivo: <nombre_del_archivo.ext>
# Ubicación de archivo: <ruta_relativa_en_el_proyecto>
# Descripción: <breve_descripción_del_uso_o_función_del_archivo>
```

- Idioma obligatorio: español en código, commits, PRs y documentación.
- Mantener límites claros: `api` expone lógica por HTTP, `web` resuelve UI/sesión, `bot_telegram` consume servicios, `nlp_intent` no accede directo a la DB.
- Usar `logging`, no `print()`. Seguir el patrón de `core/logging.py`.
- Mantener type hints y estilos cercanos a PEP 8. Las dependencias se versionan de forma estricta.
- No tocar `Legacy/` salvo pedido explícito.

## Build y Test

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
- La VM y varios defaults asumen la IP `192.168.241.28`; si cambia, revisar configuración y documentación relacionada.
- `nlp_intent` puede depender de Ollama externo; no asumir que siempre está disponible.

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

## Agentes y Skills

- Usar agentes de `.github/agents/` cuando el trabajo sea claramente de `api`, `db`, `web`, `bot`, `reports`, `security`, `docker` o `testing`.
- Usar skills de `.github/skills/` para workflows repetibles como pytest, alembic, Docker, mantenimiento y sincronización trazable del repositorio.
- Para crear nuevos customizations del ecosistema agéntico, usar la tríada `skill-generator` en `.github/agents/skill-generator.agent.md`, `.github/prompts/crear-skill.prompt.md` y `.github/skills/skill-generator/`.
