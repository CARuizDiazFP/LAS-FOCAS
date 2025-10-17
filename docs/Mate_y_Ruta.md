# Nombre de archivo: Mate_y_Ruta.md
# Ubicación de archivo: docs/Mate_y_Ruta.md
# Descripción: Plan de trabajo e implementaciones (estado actual, roadmap y checklist)

# Mate y Ruta — Plan de trabajo e implementaciones

Fecha de última actualización: 2025-10-17

Este documento centraliza el estado actual del proyecto LAS-FOCAS, el plan de implementación de nuevas funciones, y los checklists de tareas pendientes y realizadas. Es un documento vivo: debe mantenerse al día en cada hito o cambio de alcance.

## Estado actual (al 2025-10-15)

- Infraestructura y orquestación
  - Docker instalado y operativo en la VM.
  - Contenedor de Ollama activo (`ollama-llama3`) con modelo disponible: `llama3:latest` (4.7 GB).
  - Nota: el puerto 11434 no está publicado al host en el contenedor observado; evaluar exposición o incorporación de Ollama al `compose` del proyecto.
- Servicios del repo
  - `api` (FastAPI): endpoints `/health`, `/health/version`, `/db-check`, `POST /ingest/reclamos` (alias `POST /import/reclamos`), `POST /reports/repetitividad` (Excel o DB) y `GET /reports/repetitividad` (métricas JSON).
  - `web` (FastAPI): login básico, Panel con Chat por defecto (HTTP y WS), tabs para flujos (Repetitividad/SLA/FO), listado histórico en `/reports-history`, validación de adjuntos y persistencia en DB.
  - `nlp_intent` (FastAPI): `POST /v1/intent:classify` con proveedores `heuristic | ollama | openai`. Usa `OLLAMA_URL` (default `http://ollama:11434`).
  - `bot` (Telegram): definido en `deploy/compose.yml`.
  - `office` (FastAPI + LibreOffice UNO): servicio dockerizado para conversiones de documentos (en preparación).
  - DB: esquema `app` con conversaciones legacy y nuevas tablas de chat web + migraciones Alembic (`db/alembic`).
  - Ingesta híbrida: parser robusto (tolerante a acentos/mayúsculas; Unidecode con fallback a unicodedata), saneo de fechas y GEO, y upsert en PostgreSQL con `ON CONFLICT DO UPDATE` usando `COALESCE(excluded.col, table.col)` para no perder datos existentes.
  - Repetitividad desde DB o Excel: el endpoint devuelve `map_images`/`assets` (PNGs) junto al DOCX/PDF, admite `with_geo` y `use_db`; la portada del DOCX ahora es dinámica (`Informe Repetitividad — <Mes> <Año>`), cada fila exibe Horas Netas en formato `HH:MM` (normalizadas desde minutos) y se insertan mapas estáticos por servicio ajustados a media hoja A4 cuando hay coordenadas válidas. La UI alterna fuente Excel/DB, habilita GEO, lista cada mapa como descarga directa y expone headers `X-Source`, `X-With-Geo`, `X-PDF-*`, `X-Map-*`, `X-Maps-Count`, `X-Total-*`.
  - Dependencias geoespaciales estandarizadas: `matplotlib==3.9.2`, `contextily==1.5.2`, `pyproj==3.6.1` y toolchain GDAL/PROJ ya declarados en `requirements*.txt` y Dockerfiles (`api`, `web`, `bot`, `repetitividad_worker`).
- Compose
  - Define `postgres`, `api`, `nlp_intent`, `bot` (y `pgadmin` opcional). Red `lasfocas_net`.
  - El puerto 8000 de la VM está actualmente ocupado por otro contenedor externo al stack del repo.
  - Volúmenes `reports_data` y `uploads_data` montados en `web` (`/app/web_app/data/...`); parámetros `REPORTS_DIR`, `UPLOADS_DIR`, `WEB_CHAT_ALLOWED_ORIGINS` declarados en `deploy/compose.yml`.
- Tests y calidad
  - Suite actual: PASS (62 pruebas), con 0 fallas y 2 opcionales de DB habilitables según entorno. Nuevas suites unitarias cubren `core/utils/timefmt`, parser de reclamos y render del informe.
  - Se corrigieron rutas y contratos en la API; mapa ahora tiene fallback HTML si falta `folium` en entorno de test/minimal.
  - Documentación actualizada: `README.md` (Prueba rápida y puertos), `docs/api.md` (salud/versión, ingest, modo DB y headers), y PR del día.
- Documentación
  - `README.md`, `docs/` con módulos bot/API/NLP/Informes.
- Seguridad y lineamientos
  - Reglas en `AGENTS.md`: encabezado obligatorio de 3 líneas, PEP8 + type hints, logging, no secrets.

## Próximas implementaciones (prioridad)

1) MCP completo + herramientas
- Implementar lógica real de `CompararTrazasFO` y `RegistrarEnNotion`.
- Completar integración de `ConvertirDocAPdf` con `office_service` (manejo de errores y colas si es necesario).
- Definir taxonomía de mensajes/errores estandarizados para herramientas.

2) Gestión de adjuntos y almacenamiento
- Políticas de retención/borrado para archivos de `/api/chat/uploads`.
- Auditoría de descargas y permisos (evaluar endpoint autenticado o URLs firmadas).

3) Flujos SLA y comparador desde UI
- Botones del panel deben disparar endpoints backend que invocan `modules/informes_*` (con feedback de progreso y uso potencial de workers).

4) Conectividad Ollama y respuestas generativas
- Unificar consumo de Ollama entre `web` y `nlp_intent` (service mesh o contenedor dedicado).
- Afinar prompts e indicadores de intención para decidir cuándo invocar herramientas vs. respuestas generativas.

5) Observabilidad y seguridad
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
  - [ ] Botones que invocan flujos (SLA/Repetitividad) vía endpoints backend (con feedback UI).
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

### Pendiente (prioridad)
- [ ] Conectividad limpia con Ollama desde `nlp_intent`/`web`.
- [ ] Disparadores de flujos desde la UI.
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
- [ ] Definir estrategia de limpieza programada para archivos subidos en `/api/chat/uploads`.
- [ ] Añadir métricas/observabilidad específicas del chat MCP (contador de tool-calls, errores, latencias).

### Notas operativas
- Script `./Start` disponible en la raíz para levantar el stack mínimo (Postgres, NLP, API en 8001 y Web en 8080). Para reconstruir sólo los estáticos del panel: `./Start --rebuild-frontend`.
- Carpeta `Legacy/` reservada para referencias del proyecto Sandy; está excluida de git mediante `.gitignore`.

## Cómo actualizar este documento

- Actualizar en cada hito relevante y al menos una vez por jornada, referenciando el PR del día en `docs/PR/YYYY-MM-DD.md`.
- Mantener las secciones: Estado actual, Próximas implementaciones, Roadmap por iteraciones, Checklist (Realizado/Pendiente).
- Registrar decisiones no triviales en `docs/decisiones.md` y enlazarlas aquí cuando corresponda.
- Respetar el encabezado obligatorio de 3 líneas al inicio del archivo.

## Referencias

- `README.md` — visión general y despliegue.
- `deploy/compose.yml` — servicios, redes, puertos y healthchecks.
- `docs/decisiones.md` — registro de decisiones técnicas.
- `docs/PR/` — PR diario con cambios y validaciones.
- `docs/office_service.md` — detalles del microservicio LibreOffice/UNO.
- `Templates/` — repositorio centralizado de plantillas (SLA, Repetitividad y futuras).
- `docs/api.md` — endpoints disponibles (incluye `/reports/repetitividad`).
