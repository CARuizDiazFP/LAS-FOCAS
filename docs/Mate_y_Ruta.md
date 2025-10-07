# Nombre de archivo: Mate_y_Ruta.md
# Ubicación de archivo: docs/Mate_y_Ruta.md
# Descripción: Plan de trabajo e implementaciones (estado actual, roadmap y checklist)

# Mate y Ruta — Plan de trabajo e implementaciones

Fecha de última actualización: 2025-10-03

Este documento centraliza el estado actual del proyecto LAS-FOCAS, el plan de implementación de nuevas funciones, y los checklists de tareas pendientes y realizadas. Es un documento vivo: debe mantenerse al día en cada hito o cambio de alcance.

## Estado actual (al 2025-09-17)

- Infraestructura y orquestación
  - Docker instalado y operativo en la VM.
  - Contenedor de Ollama activo (`ollama-llama3`) con modelo disponible: `llama3:latest` (4.7 GB).
  - Nota: el puerto 11434 no está publicado al host en el contenedor observado; evaluar exposición o incorporación de Ollama al `compose` del proyecto.
- Servicios del repo
  - `api` (FastAPI): endpoints `/health` y `/db-check` (SQLAlchemy a PostgreSQL). Dockerfile propio.
  - `nlp_intent` (FastAPI): `POST /v1/intent:classify` con proveedores `heuristic | ollama | openai`. Usa `OLLAMA_URL` (default `http://ollama:11434`).
  - `bot` (Telegram): definido en `deploy/compose.yml`.
  - `office` (FastAPI + LibreOffice UNO): servicio dockerizado para conversiones de documentos (en preparación).
  - DB: `db/init.sql` incluye `app.conversations` y `app.messages` para trazabilidad de diálogos.
- Compose
  - Define `postgres`, `api`, `nlp_intent`, `bot` (y `pgadmin` opcional). Red `lasfocas_net`.
  - El puerto 8000 de la VM está actualmente ocupado por otro contenedor externo al stack del repo.
- Tests y calidad
  - Pruebas en `nlp_intent/tests/test_intent.py` (heurística) y en `tests/` para módulos de informes y utilidades.
- Documentación
  - `README.md`, `docs/` con módulos bot/API/NLP/Informes.
- Seguridad y lineamientos
  - Reglas en `AGENTS.md`: encabezado obligatorio de 3 líneas, PEP8 + type hints, logging, no secrets.

## Próximas implementaciones (prioridad)

1) Web Panel (UI) con chat y barra de acciones
- Nuevo microservicio `web` (FastAPI + plantillas/HTMX o similar):
  - Página principal dark-style con barra superior (botones: SLA, Repetitividad, Comparador FO, etc.).
  - Área de chat (MVP REST; iteración 2 con WebSocket/streaming).
  - Integración con `nlp_intent` para clasificación y con Ollama para generación (cuando aplique).
  - Persistencia de conversaciones/mensajes en Postgres.
- Seguridad básica: cookie de sesión firmada, rate limiting por IP/ID de sesión, sanitización de entradas.

2) Integración con flujos (SLA, Repetitividad, Comparador FO)
- Botones disparan endpoints backend que invocan los runners de `modules/informes_*`.
- Feedback de progreso (long running): planificar cola/worker (Celery/RQ) a mediano plazo.

3) Conectividad con Ollama
- Opción A (rápida): publicar 11434 del contenedor actual y setear `OLLAMA_URL=http://host.docker.internal:11434` en servicios dockerizados (agregar `extra_hosts` host-gateway).
- Opción B (recomendada): añadir servicio `ollama` al `deploy/compose.yml` dentro de la misma red.

4) Observabilidad y calidad
- Healthchecks para `web`, métricas simples (latencias, mensajes procesados).
- Tests de UI/backend (mínimo 60% cobertura en módulo nuevo).

5) Autenticación Web
- Login básico para el panel (roles mínimos), guardias por endpoint.

## Roadmap por iteraciones

- I1 (MVP UI)
  - [ ] Servicio `web` con página dark, barra de botones y chat (REST).
  - [ ] Endpoint `POST /api/chat/message` con clasificación por `nlp_intent` y respuesta dummy si no hay LLM.
  - [ ] Persistencia de mensajes/sesiones en DB.
  - [ ] Healthcheck y logging estructurado.
  - [ ] Documentación `docs/web.md` y actualización de `README.md`.

- I2 (Chat avanzado + flujos)
  - [ ] WebSocket/streaming desde Ollama.
  - [ ] Botones que invocan flujos (SLA/Repetitividad) vía endpoints backend.
  - [ ] Tests de integración básicos (WS, flujos).

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

### Notas operativas
- Script `./Start` disponible en la raíz para levantar el stack mínimo (Postgres, Ollama, NLP, API en 8001 y Web en 8080).
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
