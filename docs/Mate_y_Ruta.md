# Nombre de archivo: Mate_y_Ruta.md
# Ubicación de archivo: docs/Mate_y_Ruta.md
# Descripción: Plan de trabajo e implementaciones (estado actual, roadmap y checklist)

# Mate y Ruta — Plan de trabajo e implementaciones

Fecha de última actualización: 2026-09-03

Este documento centraliza el estado actual del proyecto LAS-FOCAS, el plan de implementación de nuevas funciones, y los checklists de tareas pendientes y realizadas. Es un documento vivo: debe mantenerse al día en cada hito o cambio de alcance.

## 🤖 Sistema Multi-Agente (Nuevo en 2026-03-03)

El proyecto ahora utiliza un ecosistema de agentes especializados para asistir en el desarrollo. La estructura anterior (CODEX monolítico) ha sido modernizada:

Actualización 2026-08-23: las skills se centralizan en `.agentes-comunes/skills/` como fuente agnóstica, manteniendo mirrors por plataforma (`.github/skills/`, `.gemini/rules/`, `.codex-skills/skills/`, `.claude/skills/`). El flujo recursivo SDD/superpowers se mantiene, pero con foco en iteraciones acotadas para evitar loops de validación redundantes.

Auditoría técnica de duplicidades, complementariedad y plan de consolidación: `docs/agentes-auditoria-consolidacion-2026-08-23.md`.

Actualización 2026-08-25: la skill `repo-updater` (7 archivos: fuente `.agentes-comunes/skills/
repo-updater/SKILL.md` + 6 mirrors) ganó dos reglas duras, confirmadas explícitamente por el usuario:
(1) siempre commitear en el worktree real de `dev`, nunca en uno de prod ni en uno aislado creado
para una investigación/tarea puntual; (2) si el working tree mezcla trabajo de la sesión actual con
trabajo previo sin commitear de otro origen, preguntar cómo separar antes de `git add .` — con la
técnica de separación por hunk (`git diff` + `git apply --cached --check`/`--cached`) documentada
paso a paso. Ver `docs/decisiones.md` (2026-08-25) y `docs/cierres/2026-08-25.md`.

Actualización 2026-09-03: **Feature Branching Efímero obligatorio**. `dev-workflow` deja de tratar
`dev` como rama de trabajo: cada tarea arranca creando una rama efímera
(`feat|fix|docs|chore|refactor|test/<slug>`) desde `origin/dev`, y `repo-updater` pushea a esa rama en
vez de a `dev` (los merges a `main` siguen siendo sólo vía Pull Request revisado). La integración a
`dev` pasa a ser responsabilidad exclusiva de `cierre-sesion`, que gana dos pasos nuevos: (1) una
**compuerta de riesgo** que clasifica cada propuesta de evolución agéntica 🟢/🟡/🔴 (misma taxonomía
que `docker-cleanup`) — las 🟢/🟡 se implementan en el mismo cierre, una 🔴 detiene el flujo y exige
respuesta explícita del usuario; y (2) un **flujo de auto-merge autónomo** (incluida la resolución de
conflictos) que integra la rama efímera a `dev`, la borra local y remotamente, y sólo se ejecuta tras
confirmar con `git branch --show-current` que la rama activa matchea el patrón de rama efímera —
guardrail duro para no borrar ni mutar `dev`/`main` si la sesión nunca creó una. La salida al chat
queda reducida a un checklist de 5 líneas (el reporte completo vive en `docs/cierres/`). 23 archivos
de gobernanza actualizados en los 5 entornos (`.agentes-comunes/`, `.github/`, `.claude/`, `.gemini/`,
`.codex-skills/`) más `AGENTS.md`, `CLAUDE.md` y `docs/entorno_dev.md`. Ver
`docs/PR/2026-09-03.md` y `docs/superpowers/plans/2026-09-03-rama-efimera-cierre-sesion.md`.

### Estructura de Archivos

```
.github/
├── agents/          # 12 agentes especializados
│   ├── docker.agent.md
│   ├── testing.agent.md
│   ├── reports.agent.md
│   ├── mcp-chatbot.agent.md
│   ├── bot.agent.md
│   ├── web.agent.md
│   ├── api.agent.md
│   ├── db.agent.md
│   ├── nlp.agent.md
│   ├── office.agent.md
│   ├── security.agent.md
│   └── infra.agent.md
├── prompts/         # Prompts automatizados
│   ├── generar-pr-diario.prompt.md
│   ├── nuevo-modulo.prompt.md
│   ├── migracion-alembic.prompt.md
│   ├── revisar-seguridad.prompt.md
│   └── cierre-sesion.prompt.md
└── skills/          # Habilidades reutilizables
    ├── docker-rebuild/SKILL.md
    ├── pytest-focas/SKILL.md
    ├── alembic-migrations/SKILL.md
    ├── cierre-sesion/SKILL.md
  ├── libreoffice-convert/SKILL.md
  ├── security-scan/SKILL.md
  ├── dependency-audit/SKILL.md
  ├── secret-detection/SKILL.md
  └── sast-analysis/SKILL.md
```

### Agentes Disponibles

| Agente | Especialidad | Handoffs |
|--------|--------------|----------|
| `docker.agent.md` | Despliegue, contenedores, compose | → testing, db |
| `testing.agent.md` | Pytest, mocks, cobertura 60% | → api, bot, reports |
| `reports.agent.md` | Informes SLA/Repetitividad | → office, db, testing |
| `mcp-chatbot.agent.md` | MCP Registry, orquestador | → nlp, reports, web |
| `bot.agent.md` | Telegram (aiogram), flows | → nlp, testing, mcp |
| `web.agent.md` | SPA Vue 3 (Composition API), auth web y consumo API JSON desacoplado | → api, mcp, security |
| `api.agent.md` | FastAPI async, Pydantic, contratos JSON y dependencias | → db, testing, security |
| `db.agent.md` | PostgreSQL async, SQLAlchemy, Alembic y repositorios | → api, docker |
| `nlp.agent.md` | Clasificación de intención | → mcp, bot |
| `office.agent.md` | LibreOffice, conversiones | → reports, docker |
| `security.agent.md` | Seguridad de APIs/SPAs, XSS Vue 3, CORS, tokens | → web, api, db |
| `infra.agent.md` | Cámaras, rutas, servicios | → db, api, reports |
| `skill-generator.agent.md` | Meta-customizations, skills, prompts y agentes | → sin handoff fijo |

### Prompts Automatizados

- **cierre-sesion.prompt.md**: Retrospectiva técnica de cierre de sesión (tareas verificadas, errores, soluciones, mejoras de prevención y aceleración), gateada por declaración explícita de cierre, guardada en `docs/cierres/YYYY-MM-DD.md`
- **crear-skill.prompt.md**: Crea skills nuevas o tríadas completas del ecosistema agéntico
- **generar-pr-diario.prompt.md**: Genera `docs/PR/YYYY-MM-DD.md` automáticamente
- **mantenimiento-disco.prompt.md**: Diagnostica disco y propone limpieza segura
- **repo-updater.prompt.md**: Audita trazabilidad documental, genera commit técnico y hace push a `dev`
- **nuevo-modulo.prompt.md**: Andamiaje estandar de modulo/submodulo SPA (views, components, router, api, composables) con reglas anti-legacy
- **migracion-alembic.prompt.md**: Crear migraciones de base de datos
- **revisar-seguridad.prompt.md**: Auditoría de seguridad del proyecto

### Seguridad Safe-by-Design

- El agente `security` ahora orquesta revisiones de seguridad apoyándose en cuatro skills especializadas: `security-scan`, `dependency-audit`, `secret-detection` y `sast-analysis`.
- El prompt `revisar-seguridad.prompt.md` quedó alineado a ese flujo: prioriza `.env`, `deploy/`, `Keys/`, Docker, red, auth y superficies expuestas antes de emitir hallazgos.
- La regla quedó consolidada también en `AGENTS.md` para que las revisiones del repo sigan el mismo estándar.
- Las directivas de `web.agent.md` y `nuevo-modulo.prompt.md` obligan frontend desacoplado por API REST JSON/WebSocket y prohiben Jinja, DOM directo y Vanilla JS clasico en nuevos desarrollos.
- Las directivas de `api.agent.md`, `db.agent.md` y `security.agent.md` ahora asumen FastAPI async, PostgreSQL async, SQLAlchemy async y foco de seguridad en APIs/SPAs Vue 3.

### Cambios en AGENTS.md

El archivo `AGENTS.md` en raíz ahora contiene solo:
- Arquitectura del proyecto (~100 líneas)
- Regla inquebrantable del encabezado de 3 líneas
- Reglas de seguridad esenciales
- Comandos Docker (`-f deploy/compose.yml`)
- Convenciones de código (PEP8, logging, testing)
- Tabla de referencia a agentes especializados

## Estado actual (al 2026-04-20)

- Infraestructura y orquestación
  - Docker instalado y operativo en la VM.
  - VM operativa migrada a Debian 13 con IP privada `172.18.208.162`.
  - Se desestimó el uso operativo de Ollama/local LLM por limitaciones de hardware; la topología vigente depende de proveedores externos vía API.
  - Publicación del servicio `web` restringida a `172.18.208.162:8080` (ver `deploy/compose.yml`) y script de firewall idempotente disponible en `scripts/firewall_hardening.sh` para aplicar allowlists y `DROP` en `INPUT/DOCKER-USER`.
  - Postgres ahora sólo expuesto en la red interna (`expose: 5432` en `deploy/compose.yml`), sin puerto publicado al host.
  - Esquema de infraestructura listo: modelos SQLAlchemy en `db/models/infra.py` y migración `db/alembic/versions/20251230_01_infra.py` crean `app.camaras`, `app.cables`, `app.empalmes`, `app.servicios`, la tabla puente `app.servicio_empalme_association` y `app.ingresos`.
  - Parser TXT de tracking (`core/parsers/tracking_parser.py`) transforma archivos de rutas en estructuras tipadas listas para poblar `empalmes` y relaciones.
  - Servicio `core/services/infra_sync.py` sincroniza la hoja Google "Camaras" contra DB (upsert por `fontine_id`), soporta credenciales vía `Keys/credentials.json` o `GOOGLE_CREDENTIALS_JSON` y registra métricas `processed/updated/created/skipped`.
  - Endpoint FastAPI `POST /sync/camaras` disponible en `api/app/routes/infra.py` para disparar la sincronización desde la API.
  - Worker `slack_baneo_worker` incorporado al stack para reportes periódicos de cámaras baneadas en Slack, con health check interno, logs centralizados en `Logs/slack_baneo_worker.log` y configuración dinámica persistida en `app.config_servicios`.
- Servicios del repo
  - `api` (FastAPI): endpoints `/health`, `/health/version`, `/db-check`, `POST /ingest/reclamos` (alias `POST /import/reclamos`), `POST /reports/repetitividad` (Excel o DB) y `GET /reports/repetitividad` (métricas JSON).
  - `web` (FastAPI): login básico, Panel con Chat por defecto (HTTP y WS), tabs para flujos (Repetitividad, Comparador VLAN, Comparador FO) + enlace `/sla`, histórico persistente en `/reports-history`, validación de adjuntos y persistencia en DB.
    - Infra/Cámaras: las tarjetas ahora exponen edición manual del `estado` para usuarios `admin`, muestran inconsistencias entre estado persistido y estado sugerido, y consumen endpoints web protegidos por sesión + CSRF para consultar/aplicar overrides.
    - Protocolo de Protección: el badge y el modal de baneos distinguen entre cámaras cubiertas por incidentes y cámaras efectivamente persistidas como `BANEADA`, evitando falsos positivos cuando hay normalización manual.
  - `nlp_intent` (FastAPI): `POST /v1/intent:classify` y `POST /v1/intent:analyze` con `openai` como proveedor LLM por defecto; `heuristic` se mantiene como opción de desarrollo/local test sin dependencia GPU.
  - `bot` (Telegram): definido en `deploy/compose.yml`.
  - `office` (FastAPI + LibreOffice UNO): servicio dockerizado para conversiones de documentos (en preparación).
  - DB: esquema `app` con conversaciones legacy y nuevas tablas de chat web + migraciones Alembic (`db/alembic`).
    - Infra: además de `app.incidentes_baneo`, el dominio ahora cuenta con `app.config_servicios` para workers configurables y `app.camaras_estado_auditoria` para trazabilidad de overrides manuales de cámaras.
  - Ingesta híbrida: parser robusto (tolerante a acentos/mayúsculas; Unidecode con fallback a unicodedata), saneo de fechas y GEO, y upsert en PostgreSQL con `ON CONFLICT DO UPDATE` usando `COALESCE(excluded.col, table.col)` para no perder datos existentes.
    - Repetitividad desde DB o Excel: el endpoint devuelve `map_images`/`assets` (PNGs) junto al DOCX/PDF, admite `with_geo` y `use_db`; la portada del DOCX ahora es dinámica (`Informe Repetitividad — <Mes> <Año>`), cada fila exibe Horas Netas en formato `HH:MM` (normalizadas desde minutos) y se insertan mapas estáticos por servicio ajustados a media hoja A4 cuando hay coordenadas válidas. La UI alterna fuente Excel/DB, habilita GEO, lista cada mapa como descarga directa y expone headers `X-Source`, `X-With-Geo`, `X-PDF-*`, `X-Map-*`, `X-Maps-Count`, `X-Total-*`.
  - SLA: motor completo disponible para Excel y DB; `core/services/sla.compute_from_db` reutiliza la ingesta `app.reclamos` con normalización de columnas y tz. Para Excel se replica el flujo legacy (dos archivos separados "Servicios Fuera de SLA" + "Reclamos SLA", validación de columnas y render con la plantilla Sandy). La vista `/sla` exige ambos archivos, muestra errores legibles y delega en `POST /api/reports/sla` que devuelve rutas docx/pdf limpias. **[2025-11-11]**: Flujo SLA completamente funcional desde la UI web tras corrección de manejo de múltiples archivos en FastAPI y configuración de `TEMPLATES_DIR` en Docker Compose. **[2026-01-13]**: Corrección crítica: la suma de horas por servicio ahora usa exclusivamente la columna "Horas Netas Reclamo" (columna U del Excel), que contiene el tiempo neto de resolución. Se eliminó el fallback incorrecto a "Horas Netas Cierre Problema Reclamo" (columna P).
  - Dependencias geoespaciales estandarizadas: `matplotlib==3.9.2`, `contextily==1.5.2`, `pyproj==3.6.1` y toolchain GDAL/PROJ ya declarados en `requirements*.txt` y Dockerfiles (`api`, `web`, `bot`, `repetitividad_worker`).
  - **Alarmas Ciena** (2025-11-17): Nueva herramienta en el panel web para procesar CSV de alarmas exportados desde gestores de red Ciena (SiteManager y MCP). Detecta automáticamente el formato, limpia datos (padding, placeholders), soporta campos multilínea y genera Excel limpio. Endpoint `POST /api/tools/alarmas-ciena` con validaciones completas, 26 tests cubriendo todos los casos y documentación exhaustiva en `docs/informes/alarmas_ciena.md`.
    - **Actualización PM**: se corrigió el fixture MCP multilínea, se añadió un fixture `web_client_logged` para pruebas autenticadas y `_require_auth` ahora responde HTTP 401, dejando la suite `tests/test_alarmas_ciena.py` totalmente en verde.
  - **Comparador de VLANs** (2025-12-03): Herramienta full-stack en el panel que permite pegar dos configuraciones Cisco IOS, detecta las líneas `switchport trunk allowed vlan`, expande rangos 1-4094, quita duplicados y muestra "Sólo A", "Comunes" y "Sólo B". Endpoint `POST /api/tools/compare-vlans` + helper `web/tools/vlan_comparator.py`, UI dark en `panel.html` y lógica `panel.js` con feedback inmediato. [2025-12-04] Se añadió aria-live en el estado, scroll en los listados y pruebas dedicadas (`tests/test_vlan_comparator.py`) que cubren rangos altos y descarte de valores fuera de límite.
  - **Protocolo de Protección / Baneo de Cámaras** (2026-01-12): Sistema completo para proteger fibra de respaldo cuando hay cortes en fibra principal:
    - **Backend**: Modelo `IncidenteBaneo`, servicio `ProtectionService`, endpoints de baneo (create/lift/active/detail), exportación a CSV/XLSX.
    - **Frontend**: Botón pánico "🚨 Protocolo Protección", wizard de 3 pasos (Identificación/Selección/Confirmación), badge de baneos activos, indicadores visuales en tarjetas (borde rojo, candado 🔒, ticket 🎫), dropdown de exportación, modal de notificaciones.
    - **Migración**: Tabla `app.incidentes_baneo` con índices por servicio y estado.
    - **Lógica inteligente**: Cámaras nuevas heredan baneo si el servicio está baneado; restauración automática a LIBRE/OCUPADA al desbanear.
  - **Normalización Manual de Estado de Cámaras** (2026-04-20): Extensión full-stack del módulo Infra para corregir discrepancias operativas sin tocar incidentes históricos.
    - **Backend**: nuevo servicio `core/services/camara_estado_service.py`, endpoints `GET/POST /api/infra/camaras/{id}/estado`, validación admin + CSRF y auditoría en `app.camaras_estado_auditoria`.
    - **Frontend**: botón `Editar estado` por tarjeta, modal con contexto operativo, incidentes activos relacionados y motivo obligatorio.
    - **Conteos**: `GET /api/infra/ban/active` informa `camaras_count`, `camaras_baneadas_count` y `total_camaras_baneadas` para separar cobertura topológica de estado efectivo.
- Compose
  - Define `postgres`, `api`, `nlp_intent`, `bot` (y `pgadmin` opcional). Red `lasfocas_net`.
  - El puerto 8000 de la VM está actualmente ocupado por otro contenedor externo al stack del repo.
  - Volúmenes `reports_data` y `uploads_data` montados en `web` (`/app/data/...`); parámetros `REPORTS_DIR`, `UPLOADS_DIR`, `WEB_CHAT_ALLOWED_ORIGINS` declarados en `deploy/compose.yml`.
- Tests y calidad
  - Suite actual: PASS (88 pruebas con Alarmas Ciena), con 0 fallas y 2 opcionales de DB habilitables según entorno. Nuevas suites unitarias cubren `core/utils/timefmt`, parser de reclamos, render del informe y procesamiento de alarmas Ciena.
  - Cobertura reciente: `tests/test_web_infra_camera_state.py` valida rol admin, inyección de `USER_ROLE`, consulta de contexto, rechazo CSRF y persistencia del override manual; corrida focal adicional `tests/test_web_infra_camera_state.py tests/test_web_admin.py` en verde (10 pruebas).
  - Se corrigieron rutas y contratos en la API; mapa ahora tiene fallback HTML si falta `folium` en entorno de test/minimal.
  - Documentación actualizada: `README.md` (Prueba rápida y puertos), `docs/api.md` (salud/versión, ingest, modo DB y headers), `docs/informes/alarmas_ciena.md` (formatos Ciena, API, troubleshooting) y PR del día.
- Documentación
  - `README.md`, `docs/` con módulos bot/API/NLP/Informes.
- Seguridad y lineamientos
  - Reglas en `AGENTS.md`: encabezado obligatorio de 3 líneas, PEP8 + type hints, logging, no secrets.

## Próximas implementaciones (prioridad)

0) Endurecimiento de red y firewall
- Aplicar `WEB_ALLOWED_SUBNETS` definitivo y ejecutar `scripts/firewall_hardening.sh` como root con `PERSIST_RULES=true` para guardar en iptables-persistent.
- Verificar `rp_filter`: `all=1`, `default=1`, `ens224=2` (o interfaz definida en `MGMT_IFACE`).
- Revisar servicios escuchando (`ss -tulpen`) y asegurar SSH sólo por red de gestión (clave pública, sin contraseña).

1) Alarmas Ciena - Validación en producción
- Validar con archivos CSV reales de Ciena de operaciones
- Ajustar detección si aparecen variantes de formato
- Evaluar necesidad de aumentar límite de 10MB según uso real
- Considerar integración con MCP (herramienta conversacional)

2) MCP completo + herramientas
- ~~Implementar lógica real de `CompararTrazasFO` y `RegistrarEnNotion`.~~ Retiradas del registro el 2026-10-26 (P13): no hay comparador FO ni configuración de Notion. Junto con `GenerarMapaGeo` (sin `folium` en `web`). Ver `docs/mcp.md`.
- ~~Completar integración de `ConvertirDocAPdf` con `office_service`.~~ Hecho el 2026-10-26: `POST /convert` real en office y la herramienta lo usa (sin colas: las conversiones se serializan en el servicio).
- Definir taxonomía de mensajes/errores estandarizados para herramientas.

3) Gestión de adjuntos y almacenamiento
- Políticas de retención/borrado para archivos de `/api/chat/uploads`.
- Auditoría de descargas y permisos (evaluar endpoint autenticado o URLs firmadas).

4) Comparador FO desde UI
- Completar flujo del comparador en el panel, aprovechando la nueva página SLA minimalista como referencia para feedback y validaciones.

5) Respuestas generativas por API externa
- Consolidar configuración de proveedores HTTP entre `web` y `nlp_intent` sin depender de LLM local en la VM.
- Afinar prompts e indicadores de intención para decidir cuándo invocar herramientas vs. respuestas generativas.

6) Observabilidad y seguridad
- Métricas Prometheus para WS y MCP (latencias, tool-calls, errores).
- Rate limiting específico para WebSocket y endpoints de uploads.
- Checklist de seguridad para publicar `/ws/chat` detrás de proxy (CSP, headers, logs).

## Roadmap por iteraciones

- I1 (MVP UI)
  - [x] Servicio `web` con página dark, barra de botones y chat REST.
  - [x] Endpoint `POST /api/chat/message` con clasificación por `nlp_intent`.
  - [x] Persistencia de mensajes/sesiones en DB (conversaciones legacy).
  - [x] Healthcheck y logging estructurado.
  - [x] Documentación base (`docs/web.md`, README actualizado).

- I2 (Chat avanzado + flujos)
  - [x] WebSocket/streaming en el panel y orquestador MCP con persistencia dedicada.
  - [x] Botones que invocan flujos (SLA/Repetitividad) vía endpoints backend (con feedback UI).
  - [x] Tests de integración WS end-to-end (cliente WebSocket + herramientas reales).
  - [ ] Métricas y rate limiting específico del chat MCP.

- I3 (Trabajos asíncronos y rendimiento)
  - [ ] Worker de tareas (Celery/RQ) y colas para procesos pesados.
  - [ ] Métricas e instrumentación.

- I4 (Autenticación y control de acceso)
  - [ ] Login básico (usuario/contraseña) y roles.
  - [ ] Hardening de endpoints y rate limiting más fino.

## Checklist

### Realizado
- [x] Infra base Docker y Postgres.
- [x] Servicio `api` con health y check de DB.
- [x] Servicio `nlp_intent` con proveedor estándar `openai`, fallback heurístico y compatibilidad heredada para `ollama`.
- [x] Esquema de conversaciones y mensajes en DB.
- [x] Política operativa documentada: sin dependencia a Ollama/local LLM en la topología estándar.
- [x] Servicio `web` (UI) con login básico, sesiones y CSRF.
- [x] Contrato del chat `POST /api/chat/message` (REST) con rate limiting.
- [x] Repositorio Sandy clonado en `Legacy/` para referencia.
- [x] Microservicio LibreOffice/UNO inicializado (`office_service/`) con Dockerfile y health check básico.
- [x] Endpoints admin: crear usuario y cambiar contraseña (roles: admin/ownergroup/invitado).
- [x] UI mínima /admin y tests de login/admin (8 pruebas).
- [x] Hashing centralizado en `core/password.py` para el panel web y scripts (bcrypt only).
- [x] Flujos de repetitividad (web y bot) delegan en `modules.informes_repetitividad.service.generate_report` con pruebas para PDF/DOCX (2025-10-03).
- [x] Chat WebSocket del panel conectado a MCP, con almacenamiento en `app.chat_sessions/app.chat_messages` y cliente streaming (2025-10-07).
- [x] Validación de adjuntos y drag & drop en el chat WebSocket, con control de MIME y límite de 15 MB (2025-10-08).
- [x] Pruebas de integración WebSocket (`tests/test_web_chat.py`) y ampliación de cobertura del orquestador/mcp (2025-10-08).
- [x] Ingesta híbrida Excel→DB con deduplicación por `numero_reclamo` y upsert COALESCE, parser tolerante a acentos/mayúsculas (Unidecode con fallback) — endpoints `POST /ingest/reclamos` y alias `POST /import/reclamos` (2025-10-15).
- [x] Repetitividad desde DB (sin archivo) o Excel (con archivo) en `POST /reports/repetitividad`; `GET /reports/repetitividad` devuelve métricas por período. Fallback de mapa HTML si falta `folium` (2025-10-15).
- [x] Start integra Alembic con `ALEMBIC_URL` desde `.env`; migraciones aplicadas hasta `20251014_01_reclamos` (2025-10-15).
- [x] Panel web actualiza flujo de Repetitividad con toggles GEO/DB y soporte de múltiples mapas (2025-10-15).
- [x] Pruebas del panel web (`test_web_repetitividad_flow.py`) cubren flags `with_geo`/`use_db` y respuesta multi-mapa (2025-10-15).
- [x] `/health/version` en API y documentación actualizada; README con “Prueba rápida” (2025-10-15).
- [x] Portada dinámica del informe de repetitividad y eliminación del flujo interactivo HTML (solo PNG estáticos por servicio en backend/UI) (2025-10-17).
- [x] Utilitario `replace_text_everywhere` (shapes, encabezados, DrawingML) y mapas estáticos estilo Google sin ejes (nuevo `core/maps/static_map.py` + tablas DOCX sin lat/lon y pruebas específicas) (2025-10-17).
- [x] Normalización de Horas Netas a minutos con `core/utils/timefmt`, tablas DOCX en `HH:MM` y nuevas pruebas (`test_timefmt.py`, `test_ingest_parser.py`, `test_repetitividad_docx_render.py`) (2025-10-17).
- [x] Vista web `/sla` minimalista con dropzone (dos archivos obligatorios), período, checkboxes y mensajes claros conectada a `POST /api/reports/sla` (2025-10-29, reforzado 2025-11-05 con validaciones legacy).
- [x] Corrección completa del flujo SLA web: logging centralizado a `Logs/`, parámetro FastAPI corregido de `Union[List, UploadFile, None]` a `List[UploadFile]`, y variable `TEMPLATES_DIR=/app/Templates` agregada en `deploy/compose.yml` (2025-11-11).
- [x] Generación exitosa de informes SLA desde la UI web con formato casi idéntico al legacy de Sandy (ajustes menores pendientes) (2025-11-11).
- [x] Tests de integración end-to-end para `/api/reports/sla`: 7 tests cubriendo flujos Excel/DB, validaciones y errores (`tests/test_web_sla_flow.py`) (2025-11-11).
- [x] Implementación completa de **Alarmas Ciena**: nueva herramienta en el panel web para convertir CSV de alarmas (SiteManager y MCP) a Excel con detección automática de formato, validaciones, tests completos (26 tests) y documentación exhaustiva (2025-11-17).
- [x] Corrección del cálculo de horas en el SLA legacy: `core/sla/legacy_report.py` ahora detecta y usa exclusivamente la columna "Horas Netas Cierre Problema Reclamo" (columna P), prioriza la columna "Número Línea" frente a "Número Primer Servicio", normaliza los IDs (`83241`, `83241.0`, ` 83241 `) y cuenta con pruebas unitarias que cubren matching dual `Número Línea`/`Número Primer Servicio` y errores cuando falta la columna requerida (2025-11-19).
- [x] Documentación y pruebas del comparador de VLANs: endpoint `POST /api/tools/compare-vlans` detallado en `docs/api.md`, mejoras de accesibilidad/UX en `panel.html`, `panel.js`, `styles.css` y nuevo test de rangos altos en `tests/test_vlan_comparator.py` (2025-12-04).
- [x] Base declarativa compartida (`db/base.py`) y reorganización de paquetes `db` para permitir importaciones limpias desde modelos (2025-12-30).
- [x] Modelos de infraestructura (`camaras`, `cables`, `empalmes`, `servicios`, `ingresos`) definidos en `db/models/infra.py` con enums y relaciones completas (2025-12-30).
- [x] Migración Alembic `20251230_01_infra.py` creada para desplegar las tablas y restricciones de infraestructura (2025-12-30).
- [x] Parser TXT de tracking (`core/parsers/tracking_parser.py`) que normaliza las líneas de rutas FO y expone dataclasses listas para persistencia (2025-12-30).
- [x] Servicio de sincronización `core/services/infra_sync.py` que integra Google Sheets (gspread) y actualiza `app.camaras` con logging estructurado y upsert (2026-01-07).
- [x] Endpoint FastAPI `POST /sync/camaras` y wiring en `api/app/main.py` para disparar la sincronización desde la API (2026-01-07).
- [x] Documentación actualizada (`docs/db.md`, `docs/api.md`, `docs/Mate_y_Ruta.md`) y guía de credenciales (`Keys/credentials.json`) reflejada en `deploy/env.sample` (2026-01-07).
- [x] Migración `20251230_01_infra.py` ajustada para ser idempotente (enum con `create_type=False`) y guía de ejecución de Alembic con `ALEMBIC_URL` documentada (2026-01-08).
- [x] **Smart Search** para Infraestructura: búsqueda por texto libre con múltiples términos (AND), endpoint `POST /api/infra/smart-search`, UI con tags visuales y quick chips (2026-01-09).
- [x] **Sistema de Versionado de Rutas FO**: modelos `RutaServicio` con hashes SHA256, flujo analyze→modal→resolve, acciones CREATE_NEW/REPLACE/MERGE_APPEND/BRANCH (2026-01-09).
- [x] **UX del Modal de Conflictos**: corrección de bug (se abría automáticamente), agregado botón "Complementar" (MERGE_APPEND), renombrado a "Camino disjunto", botón "Limpiar servicio" (2026-01-09).
- [x] **Endpoint DELETE empalmes**: `DELETE /api/infra/servicios/{id}/empalmes` para limpiar asociaciones de un servicio desde el frontend (2026-01-09).
- [x] **Protocolo de Protección (Baneo)**: Sistema completo para proteger fibra de respaldo con modelo `IncidenteBaneo`, wizard de 3 pasos, badges visuales, exportación CSV/XLSX, notificaciones por email (2026-01-12).
- [x] **Email Service**: Servicio SMTP (`core/services/email_service.py`) para notificaciones con soporte de adjuntos y EML (2026-01-12).
- [x] **Puntos Terminales y Tracking mejorado**: Parser actualizado para extraer puntas A/B, alias de pelos (C1, C2, O1C1), detección de tránsitos, modelos `PuntoTerminal` y migraciones Alembic (2026-01-13).
- [x] **Detección de Conflictos Inteligente**: Escenarios POTENTIAL_UPGRADE y NEW_STRAND en analyze/resolve de trackings, UI con modales específicos para cada tipo de conflicto (2026-01-13).
- [x] **Corrección crítica SLA**: `core/sla/legacy_report.py` ahora usa exclusivamente columna "Horas Netas Reclamo" (columna U) para el cálculo de horas, eliminando el fallback incorrecto a columna P. Tests actualizados y validados con datos reales (2026-01-13).
- [x] **Sistema Multi-Agente**: Modernización de AGENTS.md a ecosistema modular con 12 agentes especializados, 4 prompts automatizados y 4 habilidades reutilizables en `.github/` (2026-03-03).
- [x] **Trazabilidad Git autónoma**: incorporación de `repo-updater` como workflow para auditar `docs/PR/`, verificar documentación temática en `docs/` y ejecutar `git add`, `git commit` y `git push` hacia `dev` con CLI del sistema (2026-04-17).
- [x] **Reglas portables Codex/Gemini**: migración de 17 skills, 13 agentes y 7 prompts desde `.github/` hacia reglas versionadas en `.gemini/rules/`, índice `GEMINI.md` y skills Codex portables en `.codex-skills/skills/` por bloqueo de escritura en `.codex/` durante la sesión (2026-06-17).
- [x] **Worker Slack de Baneos**: servicio `slack_baneo_worker`, tabla `app.config_servicios`, panel admin `/admin/Servicios/Baneos`, health check interno y logs centralizados en `Logs/slack_baneo_worker.log` (2026-04-17).
- [x] **Edición Manual de Estado de Cámaras**: overrides admin auditados en `app.camaras_estado_auditoria`, modal de edición en Infra/Cámaras y conteo efectivo de baneadas alineado al estado persistido (2026-04-20).
- [x] **Jerarquía Cámara → Botellas**: relación auto-referencial (`camara_padre_id`, 2 niveles) para agrupar botellas bajo su cámara física real, cascada de baneo/estado a todo el grupo (`aplicar_estado_a_grupo`), backfill contra dev (286 padres creados, 424 botellas vinculadas) y fix crítico de restauración de baneo que preservaba mal el estado previo de cámaras de otros grupos. Skill `baneo-qa-real` agregada como metodología obligatoria para probar cascadas de estado sin drift no controlado. Detalle en `docs/PR/2026-08-10.md` (2026-08-10).
- [x] **CI desactivado por defecto**: `.github/workflows/ci.yml` corregido (faltaba instalar `modules/cromo_worker/requirements.txt`, abortaba toda la colección de pytest) y cambiado a `workflow_dispatch` (ejecución manual) para no consumir minutos/créditos en cada push/PR; bump de `jinja2`/`python-dotenv` por CVEs reales (2026-08-10).
- [x] **Auditoría de seguridad + fix de los 2 hallazgos Critical**: `web` dejó de montar `/var/run/docker.sock` (reemplazado por `tecnativa/docker-socket-proxy` en red dedicada) y de correr como root (`api`/`web`/`bot`/`repetitividad_worker` migrados a usuario compartido no-root `focas`); pgAdmin pasó de credenciales `admin`/`admin` hardcodeadas y publicado en `0.0.0.0` a Docker Secret real + bind `127.0.0.1`. Dos incidentes reales de producción durante el rollout (drift de red `/16` vs `/24`, colisión de UID entre `base.Dockerfile` y los workers) resueltos y documentados como guardrails nuevos en las skills `docker-rebuild`/`secrets-rollout` (`.github/`, `.gemini/rules/`, `.codex-skills/skills/`). Detalle en `docs/decisiones.md` y `docs/PR/2026-08-11.md` (2026-08-11).
- [x] **Skill `cierre-sesion`**: formalización del prompt manual de cierre (usado ad-hoc desde 2026-08-11; el archivo original ya no existe en el repo) como tríada completa `.github/prompts/cierre-sesion.prompt.md` + `.github/skills/cierre-sesion/SKILL.md` + `/cierre-sesion` en `.claude/commands/`, replicada a `.codex-skills/skills/las-focas-cierre-sesion/` y `.gemini/rules/`. Genera retrospectiva técnica (tareas, errores, soluciones, propuestas de mejora agéntica) persistida en `docs/cierres/YYYY-MM-DD.md` (2026-08-13). **Vigente**: la fuente de verdad es `.agentes-comunes/skills/cierre-sesion/SKILL.md` (mirrors en `.github/skills/`, `.claude/skills/`, `.agents/skills/`, `.codex-skills/skills/las-focas-cierre-sesion/` y `.gemini/rules/skill-cierre-sesion.md`, regenerados por `scripts/sync_agentes_comunes.sh`) y se invoca con el comando `/cierre-sesion` (`.claude/commands/cierre-sesion.md`).
- [x] **Skill `cierre-sesion` — evolución a dos carriles**: agrega gate de activación explícito (declaración inequívoca de cierre; nombrar la skill o pedir estado ya no dispara la retrospectiva), clasificación de tareas contra evidencia (completada/parcial/bloqueada/no verificada), y separa las mejoras propuestas en carril de **prevención** (obstáculos reales de la sesión) y carril de **aceleración** (pasos repetibles observados que agilizan implementaciones futuras similares, aunque la sesión no haya tenido fricción), cada una con evidencia/frecuencia/beneficio/costo/opción recomendada. De paso cierra el mirror faltante `.claude/skills/cierre-sesion/SKILL.md` (el mismo gap que esta skill documentaba para `docker-rebuild`/`nocturne-token-compliance`), verificado con `Skill(skill="cierre-sesion")` resolviendo a `SKILL.md` en vez de al comando (2026-08-19).
- [x] **Rama efímera obligatoria + auto-merge en `cierre-sesion`**: `dev-workflow` exige crear una rama efímera (`feat|fix|docs|chore|refactor|test/<slug>`) por tarea y `repo-updater` pushea ahí, nunca a `dev`/`main` directo; `cierre-sesion` agrega compuerta de riesgo 🟢/🟡/🔴 sobre las propuestas de evolución agéntica (🔴 detiene y pregunta), flujo de auto-merge autónomo de la rama efímera a `dev` con guardrail de precondición sobre `git branch --show-current` (nunca se ejecuta si la rama activa no matchea el patrón efímero, para no borrar `dev`/`main`), y salida al chat reducida a un checklist de 5 líneas. 23 archivos de gobernanza en los 5 entornos + `AGENTS.md`/`CLAUDE.md`/`docs/entorno_dev.md`. Detalle en `docs/PR/2026-09-03.md` (2026-09-03).

#### Hitos posteriores al 2026-09-03

Resumen por fecha a partir del historial de `dev` y de los títulos de `docs/cierres/`. El estado de producción de cada hito figura en el cierre correspondiente; acá no se afirma.

- [x] **Gestor de Servicios sin ODF** (2026-09-08/09): detección y categorización de Servicios activos sin ODF resuelta, señal de comparación dirección PROV vs ODF y tabla escudo `app.cromo_servicio_odf_override` con su gestor en el panel admin.
- [x] **Camino óptico de Cromo** (2026-09-10/11): resolución del camino por pelo contra `/path` (`core/services/cromo/camino_optico_service.py`), auditoría de consistencia contra lo ingerido, generación del `.txt` de tracking legacy y descarga desde el Detalle de Servicio.
- [x] **Aislamiento multi-agente por Git worktree** (2026-09-14): `scripts/agent_worktree.py` y `scripts/agent_lock.py` (worktree y rama por agente, leases por recurso, integración serializada), propagador de mirrors `scripts/sync_skill_mirrors.py` y hook `scripts/hooks/pre-commit` que bloquea commits directos en `dev`/`main`. Ver `docs/arquitectura_agentes_worktrees.md`.
- [x] **Red de acceso PON** (2026-09-17/19): catálogo de clases PON, splitters con sus puertos, tabla única de cajas PON y rosetas (`app.cromo_pon_elementos`), modos de ingesta de la red de acceso y caché de tracking por pelo de 24 h.
- [x] **Correcciones de ingresos por Slack y frescura PROV** (2026-09-23/24): "Forzar ingreso/egreso" en el hilo con auditoría append-only (`app.ingresos_correcciones`), comandos "Servicios <cable>"/"Servicios <cable> B<N>" con frescura contra PROV (`app.servicios_sync_prov`) y refresco PROV on-demand vía REST.
- [x] **Egreso web, reproceso de ingresos sin match y `track`** (2026-09-28): egreso desde la vista Ingresos del Servicio, reproceso por lote (`scripts/ingresos_reprocesar_sin_match.py`), comando "@bot track <id>" y filtros `C<N>` y `VER`/`NOVER` en "Servicios <cable>".
- [x] **API v1 para otras áreas** (2026-09-29): OAuth2 `client_credentials` (`api/app/routes/v1/`, tabla `app.api_clients`) con consultas de botellas, cables y ODF por servicio y de servicios/pelos por cable; ingesta de cables de terceros (clases 52, 59 y 60).
- [x] **Servicios por pelo y logs persistidos** (2026-09-30 a 10-02): at.62/at.63 de pelos vía `/inner`, alta desde PROV de servicios que Cromo asigna a pelos (`scripts/servicios_alta_prov_desde_cromo.py`), colecta de logs de todos los servicios en `Logs/` y baja lógica de los cables que Cromo borró (`scripts/cromo_bajas_cables_fantasma.py`).
- [x] **Informe SLA consumido con histórico** (2026-10-05): parser de Excel Servicios/Reclamos, engine de SLA consumido por evento/servicio/reclamo (`core/sla_consumo/`), entregables XLSX + DOCX ejecutivo + DOCX exhaustivo, histórico persistido (migración `20261005_02_sla_consumo_historico`) y pestaña de SLA consumido en el detalle de servicio. Ver `docs/informes/sla_consumo.md`.
- [x] **Clientes por categoría C0–C6** (2026-10-14): tabla `app.clientes` con alias (migración `20261014_01_clientes_categoria`), categoría SLA de servicios con excepción por servicio, script `scripts/clientes_categoria_regularizar.py` y vista admin. Ver `docs/clientes_categoria.md`.
- [x] **FO Monitor** (2026-10-14/17): tablas `app.fomon_*` (migración `20261014_02_fo_monitor`), `fo_monitor_worker`, API web `/api/fo-monitor/*` y SPA con mapa offline. Desde el 2026-10-24 la geometría (`app.fomon_cable_geo`) se refresca tras cada ingesta de cables de Cromo (`MODOS_GEOMETRIA_FO` en `core/services/cromo/ingesta.py`). Ver `docs/fo_monitor.md`.
- [x] **Tracking por tramos y calidad de datos de Cromo** (2026-10-16/18): un `.txt` por tramo en Slack y portal, ingesta de la clase 86 (ODF Nodo), ODF confirmadas por servicio (`app.servicio_odf_confirmada`), auditoría de huérfanos (`app.cromo_auditoria_huerfanos`), detector de inconsistencias con cuarentena (`app.cromo_inconsistencia`) y fusiones de ODF (clase 141) en los conectores.
- [x] **Árbitro de Cromo** (2026-10-19/20): motor de propuestas con señales, puntaje y acciones reversibles en modo sombra (`core/services/cromo/arbitro/`, migración `20261020_01_cromo_arbitro`), disparado por la ingesta y el viewer; pestañas Propuestas y Reglas en el viewer de inconsistencias. Hotfix de mapas de Repetitividad (tiles OSM con User-Agent propio) el 2026-10-19.
- [x] **Fases 0–4 de calidad** (2026-10-20/22): gate de calidad local en `agent_worktree.py ready` (`integrate` exige HEAD aprobado) y `web/app/main.py` partido en `web/app/routers/` (sesión, informes, chat, admin de datos, servicios, Cromo, Cámaras) con helpers en `web/app/comun.py`.
- [x] **Posición vigente y track full/odf** (2026-10-21/22): posición vigente declarada por Servicio (`app.servicio_posicion_vigente`, migración `20261021_01_servicio_posicion_vigente`), motor de track full/odf, comando en Slack y panel web de caminos adicionales.
- [x] **Slack, errores tipados y corrección de ingresos** (2026-10-23): identificación de la cámara por Fontaine ID (`id_legacy`) y por "Empalme <n_id>", reescritura de la Cámara en el hilo de un ingreso sin match y sugerencias "¿Quisiste decir…?" sin asignar (`modules/slack_baneo_notifier/`); errores 500 con referencia al log (`error_interno` en `web/app/errores.py` y `api/app/errores.py`) y sesión vía `Depends`; baja lógica y mover de ingresos desde el portal (`anulado_at`/`anulado_por`/`anulado_motivo`, migración `20261023_01_ingresos_anulacion_y_mover`); completado del tracking con red proyectada cuando Cromo corta el camino por un proyecto.

### Pendiente (prioridad)
- [x] ~~Ajustes menores de formato en el informe SLA para coincidencia 100% con el formato legacy de Sandy~~ → Corregido 2026-01-13 (columna U).
- [x] ~~Implementar endpoint `/api/infra/notify/send` para envío SMTP de notificaciones~~ → Resuelto con `POST /api/infra/notify/email` (SMTP vía `core/services/email_service.py`), más `GET /api/infra/notify/email/config` y `POST /api/infra/notify/download-eml`; expuestos en la API (`api/app/routes/infra.py`) y en el panel web (`web/app/routers/camaras.py`).
- [ ] Aplicar en el entorno objetivo la migración `20260420_01_camaras_estado_auditoria` antes de usar la edición manual desde el panel.
- [ ] Validación manual exhaustiva de Alarmas Ciena con archivos reales de producción (2025-11-17).
- [ ] Consolidar configuración de proveedores API y secretos entre `nlp_intent` y `web`.
- [x] Disparadores de flujos desde la UI.
- [x] Documentación en `docs/web.md` de headers `X-PDF-*`/`X-Map-*`, generación de PNG estáticos y ejemplos de respuesta (2025-10-17).
- [ ] Unificar versiones FastAPI/pydantic (root vs `office_service`).
- [ ] Validaciones de tamaño y tipo en `/reports/repetitividad`.
- [x] Pruebas automatizadas para `POST /api/flows/repetitividad` (web) cubriendo paths feliz y errores.
- [ ] Pruebas FSM del flujo Telegram de repetitividad (aiogram) con escenarios de error/éxito.
- [ ] Revisar `docs/api.md` con ejemplos curl de modo DB vs Excel (actualización hecha; validar).
- [ ] Entrada decisiones sobre hashes de plantillas y versión unificada FastAPI.
- [ ] Auth (API key) básica para `/reports/*`.
- [ ] Tests dedicados `core/password.needs_rehash`.
- [x] Casos negativos del endpoint `/reports/repetitividad` (extensiones inválidas, fallos del runner, `incluir_pdf` sin PDF).
- [x] Cobertura adicional para `modules.informes_repetitividad.processor.normalize` y `_detalles`.
- [ ] Autenticación / limits adicionales para `/reports/repetitividad` (API key, tamaño máximo) y pruebas asociadas.
- [x] Herramientas MCP (2026-10-26, P13): `ConvertirDocAPdf` operativa contra `office:8090/convert`; `CompararTrazasFO`, `RegistrarEnNotion` y `GenerarMapaGeo` retiradas del registro.
- [ ] Integrar parser de tracking con persistencia real en `empalmes`/`servicio_empalme_association` y exponer endpoint de importación.
- [ ] Diseñar endpoints de baneo/desbaneo y métricas de ocupación usando el nuevo esquema `app.camaras`.
- [ ] Definir estrategia de limpieza programada para archivos subidos en `/api/chat/uploads`.
- [ ] Añadir métricas/observabilidad específicas del chat MCP (contador de tool-calls, errores, latencias).

### Notas operativas
- Carpeta `Keys/` creada en la raíz e ignorada en git para almacenar llaves/artefactos locales sin exponerlos en el repo.
- Script `./Start` disponible en la raíz para levantar el stack mínimo (Postgres, NLP, API en 8001 y Web en 8080). Para reconstruir sólo los estáticos del panel: `./Start --rebuild-frontend`.
- Carpeta `Legacy/` reservada para referencias del proyecto Sandy; está excluida de git mediante `.gitignore`.

## Cómo actualizar este documento

- Actualizar en cada hito relevante y al menos una vez por jornada, referenciando el PR del día en `docs/PR/YYYY-MM-DD.md`.
- Mantener las secciones: Estado actual, Próximas implementaciones, Roadmap por iteraciones, Checklist (Realizado/Pendiente).
- Registrar decisiones no triviales en `docs/decisiones.md` y enlazarlas aquí cuando corresponda.
- Respetar el encabezado obligatorio de 3 líneas al inicio del archivo.

## Referencias

- `README.md` — visión general y despliegue.
- `AGENTS.md` — instrucciones base para agentes IA (~100 líneas).
- `.github/agents/` — agentes especializados por dominio y meta-agentes de customización.
- `.github/prompts/` — prompts automatizados (creación de skills, PR diario, actualización de repositorio, mantenimiento, nuevos módulos).
- `.github/skills/` — habilidades reutilizables (Docker, pytest, Alembic, repo-updater).
- `deploy/compose.yml` — servicios, redes, puertos y healthchecks.
- `docs/decisiones.md` — registro de decisiones técnicas.
- `docs/PR/` — PR diario con cambios y validaciones.
- `docs/cierres/` — retrospectivas técnicas de cierre de sesión (`/cierre-sesion`): tareas, errores, soluciones y propuestas de mejora agéntica.
- `docs/Seguridad.md` — lineamientos de seguridad.
- `docs/office_service.md` — detalles del microservicio LibreOffice/UNO.
- `Templates/` — repositorio centralizado de plantillas (SLA, Repetitividad y futuras).
- `docs/api.md` — endpoints disponibles (incluye `/reports/repetitividad`).
