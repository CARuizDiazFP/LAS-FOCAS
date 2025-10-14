# Nombre de archivo: Mate_y_Ruta.md
# Ubicación de archivo: docs/Mate_y_Ruta.md
# Descripción: Plan de trabajo e implementaciones (estado actual, roadmap y checklist)

# Mate y Ruta — Plan de trabajo e implementaciones

Fecha de última actualización: 2025-10-14

Este documento centraliza el estado actual del proyecto LAS-FOCAS, el plan de implementación de nuevas funciones, y los checklists de tareas pendientes y realizadas. Es un documento vivo: debe mantenerse al día en cada hito o cambio de alcance.

## Estado actual (al 2025-10-14)

- Infraestructura y orquestación
  - Docker instalado y operativo en la VM.
  - Contenedor de Ollama activo (`ollama-llama3`) con modelo disponible: `llama3:latest` (4.7 GB).
  - Nota: el puerto 11434 no está publicado al host en el contenedor observado; evaluar exposición o incorporación de Ollama al `compose` del proyecto.
- Servicios del repo
  - `api` (FastAPI): endpoints `/health`, `/db-check` y `/reports/repetitividad` (generación DOCX/PDF).
  - `web` (FastAPI): login básico, Panel con Chat por defecto (HTTP y WS), tabs para flujos (Repetitividad/SLA/FO), listado histórico en `/reports-history`, validación de adjuntos y persistencia en DB.
  - `nlp_intent` (FastAPI): `POST /v1/intent:classify` con proveedores `heuristic | ollama | openai`. Usa `OLLAMA_URL` (default `http://ollama:11434`).
  - `bot` (Telegram): definido en `deploy/compose.yml`.
  - `office` (FastAPI + LibreOffice UNO): servicio dockerizado para conversiones de documentos (en preparación).
  - DB: esquema `app` con conversaciones legacy y nuevas tablas de chat web + migraciones Alembic (`db/alembic`).
- Compose
  - Define `postgres`, `api`, `nlp_intent`, `bot` (y `pgadmin` opcional). Red `lasfocas_net`.
  - El puerto 8000 de la VM está actualmente ocupado por otro contenedor externo al stack del repo.
  - Volúmenes `reports_data` y `uploads_data` montados en `web` (`/app/web_app/data/...`); parámetros `REPORTS_DIR`, `UPLOADS_DIR`, `WEB_CHAT_ALLOWED_ORIGINS` declarados en `deploy/compose.yml`.
- Tests y calidad
  - Pruebas en `nlp_intent/tests/test_intent.py` (heurística) y en `tests/` para módulos de informes y utilidades.
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

### Pendiente (prioridad)
- [ ] Conectividad limpia con Ollama desde `nlp_intent`/`web`.
- [ ] Disparadores de flujos desde la UI.
- [ ] Documentar en `docs/api.md` y `docs/web.md` los headers `X-PDF-*` y el nuevo comportamiento opcional del PDF.
- [ ] Unificar versiones FastAPI/pydantic (root vs `office_service`).
- [ ] Validaciones de tamaño y tipo en `/reports/repetitividad`.
- [x] Pruebas automatizadas para `POST /api/flows/repetitividad` (web) cubriendo paths feliz y errores.
- [ ] Pruebas FSM del flujo Telegram de repetitividad (aiogram) con escenarios de error/éxito.
- [ ] Documentar endpoint `/reports/repetitividad` en `docs/api.md`.
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
