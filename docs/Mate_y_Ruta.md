# Nombre de archivo: Mate_y_Ruta.md
# Ubicación de archivo: docs/Mate_y_Ruta.md
# Descripción: Plan de trabajo e implementaciones (estado actual, roadmap y checklist)

# Mate y Ruta — Plan de trabajo e implementaciones

Fecha de última actualización: 2026-04-20

Este documento centraliza el estado actual del proyecto LAS-FOCAS, el plan de implementación de nuevas funciones, y los checklists de tareas pendientes y realizadas. Es un documento vivo: debe mantenerse al día en cada hito o cambio de alcance.

## 🤖 Sistema Multi-Agente (Nuevo en 2026-03-03)

El proyecto ahora utiliza un ecosistema de agentes especializados para asistir en el desarrollo. La estructura anterior (CODEX monolítico) ha sido modernizada:

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
│   └── revisar-seguridad.prompt.md
└── skills/          # Habilidades reutilizables
    ├── docker-rebuild/SKILL.md
    ├── pytest-focas/SKILL.md
    ├── alembic-migrations/SKILL.md
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
| `web.agent.md` | Panel web, auth, frontend | → api, mcp, security |
| `api.agent.md` | Endpoints FastAPI | → db, testing, security |
| `db.agent.md` | SQLAlchemy, Alembic, PostgreSQL | → api, docker |
| `nlp.agent.md` | Clasificación de intención | → mcp, bot |
| `office.agent.md` | LibreOffice, conversiones | → reports, docker |
| `security.agent.md` | Hardening, secrets, auditoría | → docker, web, api |
| `infra.agent.md` | Cámaras, rutas, servicios | → db, api, reports |
| `skill-generator.agent.md` | Meta-customizations, skills, prompts y agentes | → sin handoff fijo |

### Prompts Automatizados

- **crear-skill.prompt.md**: Crea skills nuevas o tríadas completas del ecosistema agéntico
- **generar-pr-diario.prompt.md**: Genera `docs/PR/YYYY-MM-DD.md` automáticamente
- **mantenimiento-disco.prompt.md**: Diagnostica disco y propone limpieza segura
- **repo-updater.prompt.md**: Audita trazabilidad documental, genera commit técnico y hace push a `main`
- **nuevo-modulo.prompt.md**: Scaffolding de módulo con tests y docs
- **migracion-alembic.prompt.md**: Crear migraciones de base de datos
- **revisar-seguridad.prompt.md**: Auditoría de seguridad del proyecto

### Seguridad Safe-by-Design

- El agente `security` ahora orquesta revisiones de seguridad apoyándose en cuatro skills especializadas: `security-scan`, `dependency-audit`, `secret-detection` y `sast-analysis`.
- El prompt `revisar-seguridad.prompt.md` quedó alineado a ese flujo: prioriza `.env`, `deploy/`, `Keys/`, Docker, red, auth y superficies expuestas antes de emitir hallazgos.
- La regla quedó consolidada también en `AGENTS.md` para que las revisiones del repo sigan el mismo estándar.

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
  - Contenedor de Ollama activo (`ollama-llama3`) con modelo disponible: `llama3:latest` (4.7 GB).
  - Nota: el puerto 11434 no está publicado al host en el contenedor observado; evaluar exposición o incorporación de Ollama al `compose` del proyecto.
  - Publicación del servicio `web` restringida a `192.168.241.28:8080` (ver `deploy/compose.yml`) y script de firewall idempotente disponible en `scripts/firewall_hardening.sh` para aplicar allowlists y `DROP` en `INPUT/DOCKER-USER`.
  - Postgres ahora sólo expuesto en la red interna (`expose: 5432` en `deploy/compose.yml`), sin puerto publicado al host.
  - Esquema de infraestructura listo: modelos SQLAlchemy en `db/models/infra.py` y migración `db/alembic/versions/20251230_01_infra.py` crean `app.camaras`, `app.cables`, `app.empalmes`, `app.servicios`, la tabla puente `app.servicio_empalme_association` y `app.ingresos`.
  - Parser TXT de tracking (`core/parsers/tracking_parser.py`) transforma archivos de rutas en estructuras tipadas listas para poblar `empalmes` y relaciones.
  - Servicio `core/services/infra_sync.py` sincroniza la hoja Google "Camaras" contra DB (upsert por `fontine_id`), soporta credenciales vía `Keys/credentials.json` o `GOOGLE_CREDENTIALS_JSON` y registra métricas `processed/updated/created/skipped`.
  - Endpoint FastAPI `POST /sync/camaras` disponible en `api/app/routes/infra.py` para disparar la sincronización desde la API.
  - Worker `slack_baneo_worker` incorporado al stack para reportes periódicos de cámaras baneadas en Slack, con health check interno, logs centralizados en `Logs/slack_baneo_worker.log` y configuración dinámica persistida en `app.config_servicios`.
- Servicios del repo
  - `api` (FastAPI): endpoints `/health`, `/health/version`, `/db-check`, `POST /ingest/reclamos` (alias `POST /import/reclamos`), `POST /reports/repetitividad` (Excel o DB) y `GET /reports/repetitividad` (métricas JSON).
  - `web` (FastAPI): login básico, Panel con Chat por defecto (HTTP y WS), tabs para flujos (Repetitividad, Comparador VLAN, Comparador FO) + enlace `/sla`, listado histórico en `/reports-history`, validación de adjuntos y persistencia en DB.
    - Infra/Cámaras: las tarjetas ahora exponen edición manual del `estado` para usuarios `admin`, muestran inconsistencias entre estado persistido y estado sugerido, y consumen endpoints web protegidos por sesión + CSRF para consultar/aplicar overrides.
    - Protocolo de Protección: el badge y el modal de baneos distinguen entre cámaras cubiertas por incidentes y cámaras efectivamente persistidas como `BANEADA`, evitando falsos positivos cuando hay normalización manual.
  - `nlp_intent` (FastAPI): `POST /v1/intent:classify` con proveedores `heuristic | ollama | openai`. Usa `OLLAMA_URL` (default `http://ollama:11434`).
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
- Implementar lógica real de `CompararTrazasFO` y `RegistrarEnNotion`.
- Completar integración de `ConvertirDocAPdf` con `office_service` (manejo de errores y colas si es necesario).
- Definir taxonomía de mensajes/errores estandarizados para herramientas.

3) Gestión de adjuntos y almacenamiento
- Políticas de retención/borrado para archivos de `/api/chat/uploads`.
- Auditoría de descargas y permisos (evaluar endpoint autenticado o URLs firmadas).

4) Comparador FO desde UI
- Completar flujo del comparador en el panel, aprovechando la nueva página SLA minimalista como referencia para feedback y validaciones.

5) Conectividad Ollama y respuestas generativas
- Unificar consumo de Ollama entre `web` y `nlp_intent` (service mesh o contenedor dedicado).
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
- [x] Servicio `nlp_intent` con proveedores `heuristic/ollama/openai`.
- [x] Esquema de conversaciones y mensajes en DB.
- [x] Modelo `llama3` presente en contenedor de Ollama.
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
- [x] **Trazabilidad Git autónoma**: incorporación de `repo-updater` como workflow para auditar `docs/PR/`, verificar documentación temática en `docs/` y ejecutar `git add`, `git commit` y `git push` hacia `main` con CLI del sistema (2026-04-17).
- [x] **Worker Slack de Baneos**: servicio `slack_baneo_worker`, tabla `app.config_servicios`, panel admin `/admin/Servicios/Baneos`, health check interno y logs centralizados en `Logs/slack_baneo_worker.log` (2026-04-17).
- [x] **Edición Manual de Estado de Cámaras**: overrides admin auditados en `app.camaras_estado_auditoria`, modal de edición en Infra/Cámaras y conteo efectivo de baneadas alineado al estado persistido (2026-04-20).

### Pendiente (prioridad)
- [x] ~~Ajustes menores de formato en el informe SLA para coincidencia 100% con el formato legacy de Sandy~~ → Corregido 2026-01-13 (columna U).
- [ ] Implementar endpoint `/api/infra/notify/send` para envío SMTP de notificaciones.
- [ ] Aplicar en el entorno objetivo la migración `20260420_01_camaras_estado_auditoria` antes de usar la edición manual desde el panel.
- [ ] Validación manual exhaustiva de Alarmas Ciena con archivos reales de producción (2025-11-17).
- [ ] Conectividad limpia con Ollama desde `nlp_intent`/`web`.
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
- [ ] Completar implementación de herramientas MCP (`CompararTrazasFO`, `ConvertirDocAPdf`, `RegistrarEnNotion`).
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
- `docs/Seguridad.md` — lineamientos de seguridad.
- `docs/office_service.md` — detalles del microservicio LibreOffice/UNO.
- `Templates/` — repositorio centralizado de plantillas (SLA, Repetitividad y futuras).
- `docs/api.md` — endpoints disponibles (incluye `/reports/repetitividad`).
