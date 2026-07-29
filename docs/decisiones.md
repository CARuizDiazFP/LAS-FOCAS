# Nombre de archivo: decisiones.md
# Ubicación de archivo: docs/decisiones.md
# Descripción: Registro de decisiones técnicas del proyecto

## 2025-08-21 — Fijación de versiones de dependencias

- **Contexto:** Las dependencias `sqlalchemy`, `psycopg[binary]` y `orjson` no tenían versiones fijas, lo que provocaba diferencias entre entornos.
- **Decisión:** Establecer versiones explícitas en `requirements.txt` para asegurar un entorno replicable.
- **Alternativas:** Mantener versiones flotantes y resolver conflictos cuando aparezcan.
- **Impacto:** Facilita la reproducción de entornos y reduce fallos por cambios inesperados en las dependencias.

## 2025-08-21 — Unificación de flujos del bot

- **Contexto:** Los comandos y botones del bot ejecutaban lógica separada, lo que dificultaba diagnosticar problemas con `callback_query` y generaba duplicidad de código.
- **Decisión:** Aplicar el middleware de allowlist también a `callback_query`, resolver `allowed_updates` automáticamente y unificar comandos y botones en funciones comunes (`start_sla_flow`, `start_repetitividad_flow`).
- **Alternativas:** Mantener handlers separados o posponer la unificación.
- **Impacto:** Logs más consistentes, menor duplicación de código y posibilidad de diagnosticar rápidamente con `/diag` los eventos recibidos.

## 2025-09-18 — Política de URL base (Web UI) usando IP privada

- Contexto: Usuarios acceden al Web UI desde la red local de la VM Debian. Usar localhost en documentación y defaults generaba confusión y errores de acceso desde otros equipos.
- Decisión: Unificar la URL base expuesta en código, variables de entorno y documentación a la IP privada de la VM: http://172.18.208.162:8080. En containers, healthchecks siguen usando localhost interno.
- Alternativas: Mantener localhost y exigir configurar API_BASE manualmente; usar nombre DNS interno. Se opta por IP para simplicidad en esta fase.
- Impacto: Documentación y defaults coherentes. Requiere rebuild del servicio web para hornear el fallback del frontend. Posibles ajustes de firewall/routing si la IP no es accesible desde el host o clientes externos.

## 2025-09-26 — Fijado bcrypt y fallback hashing en script de mantenimiento

- Contexto: El login (usuario admin) fallaba con `result=fail reason=bad_password` pese a hash válido en DB. Al intentar `passlib.hash.bcrypt` aparecía `AttributeError: module 'bcrypt' has no attribute '__about__'` y excepciones internas durante la detección de backend (`detect_wrap_bug`). Esto impedía resetear/verificar contraseñas de forma confiable y generaba falsos negativos.
- Decisión: Fijar versión explícita `bcrypt==4.1.2` en `web/requirements.txt` y añadir un script robustecido (`web/tools/reset_admin_password.py`) con fallback: si passlib falla, usar directamente la librería `bcrypt` para `hashpw` y `checkpw`. Se añade truncado manual (72 bytes) y logging de advertencia.
- Alternativas: Migrar a `argon2` (más seguro) o esperar actualización de passlib. Se opta por parche mínimo para restaurar operatividad del MVP.
- Impacto: Login funcional (`result=success`) y herramienta de mantenimiento confiable. Futura tarea: Evaluar migración a `argon2` y rotación de hashes existentes.

## 2025-09-29 — Espacio Legacy para referencias del proyecto Sandy

- Contexto: Se requiere consultar flujos y plantillas del proyecto Sandy (origen de los informes) para migrar lógica al ecosistema LAS-FOCAS sin mezclar código heredado con desarrollo actual.
- Decisión: Crear la carpeta `Legacy/` ignorada por git para alojar la clonación local del repositorio Sandy con fines de referencia y análisis offline.
- Alternativas: Mantener el repositorio en otra ubicación fuera del proyecto o traer fragmentos específicos manualmente.
- Impacto: Facilita la consulta rápida de código e informes previos manteniendo el repositorio limpio; se debe validar licencias antes de incorporar código y documentar cualquier reutilización.

## 2025-09-29 — Microservicio LibreOffice/UNO dedicado

- Contexto: Los informes heredados de Sandy dependen de Microsoft Word vía pywin32. Para portarlos a Debian/docker se requiere encapsular LibreOffice en modo headless y exponer capacidades UNO de manera reutilizable por múltiples módulos.
- Decisión: Construir el microservicio `office_service/` (FastAPI + LibreOffice headless) con imagen propia, `docker-compose` integrado y endpoint de salud. Se pospone la implementación de conversiones reales, dejando placeholder con logging estructurado.
- Alternativas: Integrar `libreoffice` directamente en cada módulo o usar librerías específicas (`docxtpl`, `python-docx`). Se elige servicio dedicado para centralizar dependencias pesadas y compartir recursos entre módulos.
- Impacto: Aumenta el tamaño del stack pero permite estandarizar conversiones y aislar LibreOffice en un contenedor controlado. Requiere seguir iterando para exponer conversiones seguras y definir volúmenes compartidos.

## 2025-09-29 — Hashing de contraseñas con bcrypt nativo

- Contexto: Passlib continuaba emitiendo advertencias por depender del módulo `crypt` (deprecado en Python 3.13) y la lógica de hashing estaba duplicada entre web y scripts.
- Decisión: Eliminar Passlib y utilizar la librería nativa `bcrypt` desde `core/password.py`, centralizando rounds y verificación para web, tests y utilidades CLI. Esta decisión queda supersedida parcialmente el 2026-06-25: ya no se truncan contraseñas largas.
- Alternativas: Migrar directamente a `argon2-cffi` (más costoso en CPU) o mantener Passlib. Se optó por `bcrypt` nativo para compatibilidad con hashes existentes y simplicidad, dejando abierta la migración futura a Argon2.
- Impacto: Se retira una dependencia obsoleta, se reducen advertencias y se simplifica el mantenimiento al tener un único módulo responsable del hashing.

## 2026-06-25 — Hashing versionado sin truncado silencioso

- Contexto: bcrypt limita la entrada efectiva a 72 bytes. El truncado manual previo podía hacer que contraseñas largas distintas verificaran igual si compartían el mismo prefijo.
- Decisión: Generar hashes nuevos como SHA-256 de la contraseña UTF-8 completa y luego bcrypt sobre ese digest, con prefijo `$lasfocas-sha256-bcrypt$v1$`. La verificación conserva compatibilidad con bcrypt legacy para contraseñas de hasta 72 bytes y `needs_rehash` marca legacy como migrable.
- Alternativas: Rechazar contraseñas mayores a 72 bytes o migrar directamente a Argon2. Se elige prehash versionado para no invalidar usuarios existentes y eliminar pérdida silenciosa de información.
- Impacto: Las contraseñas nuevas no se truncan; los hashes legacy siguen funcionando durante la transición y pueden migrarse en cambios de contraseña o login exitoso futuro.

## 2025-09-29 — Repositorio central de plantillas y worker geoespacial

- Contexto: Las plantillas de informes estaban dispersas (Legacy/Sandy) y la generación de mapas dependía de librerías pesadas dentro del bot original.
- Decisión: Crear `Templates/` como repositorio único versionado y preparar un worker Docker (`repetitividad_worker`) para encapsular `geopandas/contextily`, evitando inflar los servicios principales.
- Alternativas: Mantener plantillas dentro de cada módulo o seguir ejecutando mapas en el mismo contenedor. Se optó por centralizar para facilitar mantenimiento y futuras auditorías.
- Impacto: Simplifica la gestión de plantillas, permite pruebas de integridad y sienta las bases para un pipeline de mapas desacoplado (aún en fase placeholder).

## 2025-10-03 — Default LLM = OpenAI y validación temprana de API Key
## 2025-10-03 — Taxonomía unificada de intención y endpoint analyze
## 2025-10-03 — Fase 2: Sub-clasificación de acciones y respuestas de consulta
- Persistencia de memoria Web Chat (pseudo-id de usuario web) se implementa sin alterar esquema (se reutiliza `tg_user_id`). Justificación: evita migraciones durante MVP; se evaluará agregar campo específico en fase posterior.

- Contexto: Se necesitaba distinguir acciones soportadas (por ahora solo informe de repetitividad) de solicitudes aún no implementadas y ofrecer respuestas útiles a consultas dentro del dominio telecom/red.
- Decisión: Extender `IntentionResult` (schema_version=2) con campos `action_code`, `action_supported`, `answer`, `answer_source`, `domain_confidence`. Heurística de acción prioritaria (repetitividad) y base de FAQs para consultas frecuentes evitando costo LLM.
- Alternativas: Implementar inmediatamente un motor de flujos completo o separar endpoints (classify vs answer). Se opta por un único endpoint enriquecido para reducir round trips y facilitar evolución incremental.
- Impacto: Aumenta ligeramente complejidad del servicio NLP. El costo LLM controlado por flags (`INTENT_ENABLE_ANSWERS`, `INTENT_CLARIFY_PROVIDER`). Base FAQ reduce tokens y latencia.
- Próximo: incorporar subclasificación SLA/comparador FO cuando estén listos los flujos.

- Contexto: El sistema necesitaba separar claramente entre solicitudes accionables y consultas genéricas, reduciendo confusión entre saludos/neutros y preparando un pipeline multi-stage (clasificar → clarificar → despachar flujo / responder). Las etiquetas previas (Acción, Consulta, Otros) eran insuficientes para el Web Chat porque Otros mezclaba ruido y casos que ameritan follow-up.
- Decisión: Introducir nueva taxonomía normalizada: `Solicitud de acción`, `Consulta/Generico`, `Otros`. Se crea endpoint `/v1/intent:analyze` que mapea la etiqueta original y agrega campos `need_clarification` y `clarification_question`. El endpoint anterior `/v1/intent:classify` queda deprecado.
- Alternativas: Expandir a más clases (ej. "Saludo", "Agradecimiento") o mantener 3 clases originales y lógica ad-hoc para follow-up. Se opta por mantener mapeo mínimo y enriquecer con clarificación para conservar simplicidad.
- Impacto: El Web Chat ahora puede decidir si preguntar detalles cuando la intención es ambigua. Incrementa una llamada adicional (clarify) solo para casos "Otros" (configurable por `INTENT_CLARIFY_PROVIDER`). Sienta base para subclasificación de flujos.

## 2025-10-03 — conversation_id, endpoints /api/chat/history y /api/chat/metrics, sanitización

- Contexto: El Web Chat necesitaba correlacionar turnos, ofrecer recuperación de historial y exponer métricas mínimas sin introducir complejidad de observabilidad completa.
- Decisión: Añadir `conversation_id` en la respuesta de `/api/chat/message`, endpoint `GET /api/chat/history` (límite configurable hasta 100), y `GET /api/chat/metrics` con contador en memoria por intención (MVP). Se implementa sanitización de caracteres de control Unicode (categoría C) excluyendo `\n` y `\t` antes de enviar al servicio NLP.
- Alternativas: a) Implementar inmediatamente almacenamiento de métricas en DB o Prometheus; b) Usar WebSocket para streaming. Se pospone para MVP para reducir superficie inicial.
- Impacto: Mejora trazabilidad de sesiones y debugging. Métricas se reinician en cada despliegue (documentado). Posible inconsistencia en análisis longitudinal hasta persistir estadísticas (futuro backlog).


- Contexto: El flujo de clasificación de intención usaba modo "auto" (heurístico → Ollama → OpenAI) lo cual generaba respuestas no homogéneas y dificultaba testear mejoras futuras de generación en el Web Chat. Se requiere forzar consistencia y preparar la capa para respuestas generativas.
- Decisión: Cambiar el valor por defecto de `LLM_PROVIDER` a `openai` en `nlp_intent/app/config.py` y agregar validación fail-fast: si `OPENAI_API_KEY` no está presente y el proveedor es OpenAI el servicio aborta al iniciar. No se expone la clave en el repositorio; sigue suministrándose vía `.env` / secret.
- Alternativas: Mantener "auto" y priorizar heurística; forzar uso de Ollama local (requiere modelo cargado y latencia variable); posponer hasta introducir generación completa. Se elige OpenAI para maximizar calidad inicial y reducir lógica condicional en esta fase.
- Impacto: Despliegues sin `OPENAI_API_KEY` fallarán rápido (visibilidad operativa). Tests que dependan de `LLM_PROVIDER=heuristic` deberán fijar explícitamente la variable de entorno en el entorno de CI. Próximo paso: introducir endpoint de generación y memoria conversacional con almacenamiento en DB.

## 2025-10-07 — Estado DEPRECATED del árbol `Legacy/`

- **Contexto:** Se incorporó un árbol `Legacy/` (ej. código histórico de Sandy) únicamente para consulta offline y referencia durante la migración de informes. Este contenido no debe mezclarse ni evolucionar dentro del repositorio principal para evitar deuda técnica y riesgos de licenciamiento o incoherencias arquitectónicas.
- **Decisión:** Marcar formalmente `Legacy/` como DEPRECATED y congelado. No se aceptarán PRs que modifiquen archivos bajo `Legacy/`. La carpeta permanece ignorada en `.gitignore` para nuevos archivos; los existentes no se alteran. No se harán copias directas de lógica sin: (1) revisión de licencias, (2) refactor a estándares actuales (PEP8, logging estructurado, tests), (3) documentación en `/docs`.
- **Alternativas:** Eliminar completamente el árbol (perdería valor de referencia) o moverlo a un repositorio separado de solo lectura. Se pospone esa separación hasta finalizar la migración de todos los informes críticos.
- **Impacto:** Reduce riesgo de reintroducir patrones obsoletos, clarifica el alcance para colaboradores y auditores. Facilita auditoría de cambios: cualquier modificación en `Legacy/` se considera señal de posible error de procedimiento.
- **Acciones complementarias:** Añadir hook pre-commit (pendiente) que bloquee modificaciones futuras; actualizar `README.md` para informar el estado DEPRECATED. (Se añadirá en una iteración futura si se aprueba.)

## 2026-05-12 — Topología Debian 13, IP fija 172.18.208.162 y proveedor LLM sólo por API externa

- Contexto: el proyecto fue migrado a una nueva VM operativa con Debian 13 y cambió su IP privada a `172.18.208.162`. La infraestructura anterior y parte de la documentación todavía referenciaban `192.168.241.28` y una integración con Ollama vía `host.docker.internal:11434`.
- Decisión: consolidar la topología productiva en la nueva IP privada, eliminar del despliegue estándar las referencias operativas a Ollama/local LLM y documentar que el proveedor LLM por defecto se consume vía API externa (`openai`).
- Alternativas: mantener la compatibilidad operativa con Ollama en compose o publicar ambos caminos en paralelo. Se descarta porque la VM actual no dispone de GPU y el camino local ya no representa el entorno real.
- Impacto: `deploy/compose.yml`, `deploy/docker-compose.dev.yml`, `Start`, `README.md`, samples de entorno y documentación operativa deben reflejar la nueva IP y la política de proveedor externo. El soporte heredado para `ollama` puede permanecer en código, pero fuera del despliegue recomendado.

## 2026-04-17 — Tríada para generación de skills y customizations agénticos

- **Contexto:** El proyecto evolucionó hacia un ecosistema agéntico con recursos en `.github/agents/`, `.github/prompts/` y `.github/skills/`. Crear nuevas skills sin un patrón claro aumentaba el riesgo de mezclar instrucciones pasivas, prompts y workflows activos, saturando la ventana de contexto y degradando el descubrimiento automático.
- **Decisión:** Estandarizar la creación de nuevas skills mediante una tríada explícita compuesta por: un agente generador de skills, un prompt estructurado para capturar requerimientos y una meta-skill invocable que orquesta el workflow. Cada capa mantiene una responsabilidad única: el agente implementa, el prompt estructura y la skill empaqueta el proceso.
- **Alternativas:** Crear solo una skill genérica, mover estas reglas a `AGENTS.md` o seguir creando customizations ad hoc en cada tarea. Se descartaron porque mezclan responsabilidades o cargan contexto global innecesario.
- **Impacto:** Reduce duplicación, mejora consistencia de naming y frontmatter, y mantiene el conocimiento especializado fuera de las instrucciones siempre activas. También hace más predecible la evolución del ecosistema de customizations del repositorio.

## 2026-04-17 — Worker Slack con APScheduler y configuración dinámica en DB

- **Contexto:** Se necesita un servicio automatizado que notifique periódicamente el estado de baneos de cámaras a canales de Slack, con un intervalo y canales editables desde el panel admin sin reiniciar el contenedor.
- **Decisión:** Implementar un worker Docker independiente (`slack_baneo_worker`) usando APScheduler (`BlockingScheduler` + `IntervalTrigger`) en lugar de Celery/Redis. La configuración (intervalo, canales, estado activo) se persiste en la nueva tabla `app.config_servicios` y se relee en cada ejecución del job. Si el intervalo cambió, se invoca `reschedule_job()` dinámicamente. Los tokens de Slack permanecen en `.env` (secretos). El health check se expone mediante `http.server` embebido en un thread daemon (puerto 8095), evitando dependencia de FastAPI.
- **Alternativas:** (1) Celery + Redis: excesivo para una tarea periódica simple sin cola de mensajes. (2) Config solo en `.env`: no permite cambios dinámicos desde la UI. (3) FastAPI para health check: agrega dependencia innecesaria al worker.
- **Impacto:** Stack liviano sin infraestructura adicional (Redis/broker), reconfiguración sin reinicio, y health check verificable desde el panel admin y desde Docker Compose healthcheck.

## 2026-04-20 — Override manual auditado para estados de cámaras

- **Contexto:** El panel Infra mostraba cámaras cubiertas por incidentes activos aunque el estado persistido real ya no debía considerarse baneado. Operaciones necesitaba corregir esos desvíos manualmente desde la UI sin alterar el historial de incidentes de protección.
- **Decisión:** Implementar un flujo admin-only de override sobre `Camara.estado`, separado de `IncidenteBaneo`, con cálculo de contexto operativo (`estado_sugerido`, incidentes activos e ingresos abiertos) y auditoría persistida en `app.camaras_estado_auditoria`. Los conteos del badge de baneos pasan a usar el estado efectivo persistido, mientras el modal conserva la referencia de cobertura topológica por incidente.
- **Alternativas:** (1) modificar automáticamente incidentes activos para “desbanear” cámaras desde la UI, descartado porque mezcla corrección operativa con historial de incidentes; (2) recalcular siempre el estado de forma derivada sin persistencia, descartado porque impide normalizaciones manuales; (3) permitir edición sin auditoría, descartado por falta de trazabilidad.
- **Impacto:** Operaciones puede normalizar desvíos de estado desde el panel sin perder rastro de quién, cuándo y por qué cambió una cámara. La UI evita falsos positivos en cámaras baneadas, pero conserva visibilidad de inconsistencias cuando el override no coincide con el estado sugerido por el sistema.

## 2026-04-23 — Política de zona horaria: UTC en DB, GMT-3 en presentación

- **Contexto:** Los mensajes de Slack, reportes Excel y emails mostraban timestamps en UTC (`16:16 UTC`), mientras los usuarios y el personal operativo trabajan en la zona `America/Argentina/Buenos_Aires` (GMT-3, sin DST). Esto generaba confusión al correlacionar eventos con horas locales.
- **Decisión:** Centralizar la conversión de TZ en `core/utils/tz.py` con una sola fuente de verdad (`TZ_ARG = ZoneInfo("America/Argentina/Buenos_Aires")`). Regla estricta: **almacenamiento siempre en UTC, presentación siempre en GMT-3**. Para mostrar cualquier fecha al usuario se usa `fmt_local(dt)` o `ahora_fmt()`. Los logs internos, health checks y nombres de archivo de sistema pueden mantener UTC.
- **Alternativas:** (1) Cambiar el `TZ` del sistema operativo del contenedor a `America/Argentina/Buenos_Aires` — descartado porque afecta librerías que asumen servidor UTC y complica la portabilidad; (2) convertir en el frontend (JavaScript) — descartado para Slack y emails donde no hay frontend que intervenga; (3) forzar TZ en PostgreSQL — descartado porque todos los clientes deben acordar TZ de visualización y solo algunos muestran a usuarios.
- **Impacto:** Un único cambio en `TZ_ARG` actualiza todo el proyecto. Los archivos afectados en esta iteración: `modules/slack_baneo_notifier/{eventos.py,notifier.py}`, `api/api_app/routes/infra.py`, `web/web_app/main.py`. Los modelos DB y el worker interno mantienen `datetime.now(timezone.utc)`.

## 2026-07-13 — Servicios Fase 1 sobre tabla existente y proxy web autenticado

- **Contexto:** Se necesitaba incorporar ingesta masiva de Excel y visor con búsqueda + scroll infinito para servicios SLA, sin romper la infraestructura FO ya montada sobre `app.servicios` y manteniendo el SPA autenticado por sesión.
- **Decisión:** Extender `app.servicios` (no crear tabla paralela) agregando campos de SLA (`numero_primer_servicio`, cliente, línea, tipo, domicilio, estado, etc.). La lógica principal se implementa en `api/app` con FastAPI async + SQLAlchemy async + Pydantic, y `web/app` expone endpoints same-origin como proxy autenticado (sesión/rol/CSRF) hacia la API interna con API key.
- **Alternativas:** (1) tabla nueva `servicios_sla`; (2) lógica directa en `web/app` con consultas sync. Se descartaron por duplicación de dominio y por no cumplir el objetivo de consolidar backend async desacoplado.
- **Impacto:** El visor `/servicios` queda disponible para usuarios autenticados y la ingesta `/admin/ingesta` solo para admin. Se reduce acoplamiento frontend-backend y se preserva compatibilidad con rutas/trackings existentes.

## 2026-07-28 — Docker Secrets basados en archivo para dev y prod, con prefijo `Dev_`

- **Contexto:** Ni el stack dev (`deploy/docker-compose.dev.yml`) ni el productivo (`deploy/compose.yml`) usaban Docker Secrets pese a que `core/config.py:get_secret()` ya soportaba leer `/run/secrets/<nombre>`; todas las credenciales viajaban en texto plano vía `env_file` (`.env.dev` / `.env`). `docs/Seguridad.md` documentaba además una estrategia productiva basada en Docker Swarm (`docker secret create ... --external`) que nunca se implementó y que resultó inaplicable: el host corre Docker en modo no-Swarm (`docker info` → `Swarm.LocalNodeState: inactive`).
- **Decisión:** Adoptar Docker Compose Secrets basados en archivo (sin Swarm) en ambos stacks. Los 8 secretos (`db_password_v1`, `api_key_v1`, `web_secret_key_v1`, `telegram_bot_token_v1`, `openai_api_key_v1`, `smtp_password_v1`, `slack_bot_token_v1`, `slack_app_token_v1`) usan archivos en `.secrets/`: prefijo `Dev_` reservado exclusivamente para dev (`.secrets/Dev_db_password_v1.txt`, etc.), sin prefijo para prod (`.secrets/db_password_v1.txt`, etc.). `scripts/setup_local_secrets.sh` genera el set `Dev_*.txt`; los archivos de prod se poblaron a mano desde los valores vigentes en `.env`. Se generó un `api_key_v1` nuevo para prod (no existía `LAS_FOCAS_API_KEY` en `.env`, dejando 503 en rutas protegidas). `SMTP_PASS` de prod quedó vacío (igual que `.env`, no se asumió el valor leftover de dev). `env_file: ../.env` se mantiene como fallback de transición en todos los servicios excepto `postgres` (ver hallazgo siguiente).
- **Hallazgos técnicos que condicionaron la implementación:**
  1. El servicio `postgres` no puede tener simultáneamente `env_file` (que inyecta `POSTGRES_PASSWORD` en texto plano) y `POSTGRES_PASSWORD_FILE` en `environment:` — la imagen oficial aborta con `both POSTGRES_PASSWORD and POSTGRES_PASSWORD_FILE are set (but are exclusive)`. Se quitó `env_file` del servicio `postgres` en ambos composes.
  2. `DATABASE_URL`/`ALEMBIC_URL`, si están seteadas, tienen prioridad sobre el secreto `db_password_v1` en `_engine_url()` (`db/session.py`, `core/services/repetitividad.py`), anulándolo por completo. `.env` de prod tenía `DATABASE_URL` seteada (no documentada en `deploy/env.sample`) y hubo que comentarla — **no alcanza con vaciarla**: `DATABASE_URL=` (vacía pero presente) sigue haciendo que `os.getenv("DATABASE_URL", default)` devuelva `""` en vez de caer al default, porque `os.getenv` solo usa el default cuando la clave está ausente, no cuando está vacía. Rompió el arranque de `api` (`ArgumentError: Could not parse SQLAlchemy URL from string ''`) hasta comentar la línea completa.
  3. El contenido de cada `.txt` de secret debe ser una copia exacta del valor que el rol de Postgres/servicio ya tiene vigente, nunca uno regenerado — se rompió la autenticación en dev al asumir (por instrucción del usuario, luego corregida) que el placeholder de `.env.dev` era la password real vigente.
  4. Al rotar `POSTGRES_PASSWORD` (mismo día, ver `docs/PR/2026-07-28.md`), `ALTER ROLE <nombre> ...` sin comillas pliega el identificador a minúsculas — falló con `role "focalbot" does not exist` hasta usar `ALTER ROLE "FOCALBOT" ...`. Aplica a cualquier rol creado con mayúsculas (vía `POSTGRES_USER` con mayúsculas en el entorno).
- **Alternativas:** (1) Mantener Swarm como estrategia productiva documentada — descartada por no reflejar la realidad del host (no-Swarm). (2) Seguir con `.env`/`.env.dev` en texto plano indefinidamente — descartada por exposición de credenciales en filesystem plano sin rotación controlada. (3) Un solo set de archivos sin distinguir dev/prod — descartada explícitamente por el usuario para evitar pisar secretos productivos durante trabajo en dev.
- **Impacto:** `deploy/compose.yml` y `deploy/docker-compose.dev.yml` quedan con secretos file-based; `scripts/check_no_plaintext_secrets.sh` ahora escanea ambos composes; `docs/Seguridad.md`, `docs/infra.md`, `docs/db.md`, `docs/api.md` actualizados. Recrear cualquiera de estos 8 secretos sobre un volumen Postgres ya inicializado exige copiar el valor exacto vigente (no regenerar) o coordinar `ALTER ROLE`/recreación de volumen. Mismo día, ya se ejecutó la primera rotación real: `POSTGRES_PASSWORD` de prod (antes el placeholder de la plantilla) se rotó a un valor generado con `secrets.token_urlsafe(32)`, con ensayo previo en dev. Futuras rotaciones deben seguir el mismo patrón: backup → nueva password en el secret + `.env` → `ALTER ROLE "<user>" WITH PASSWORD ...` vía socket local → recreate por servicio con verificación de health/DB entre cada paso.

## 2026-07-29 — Rediseño Nocturne del portal y hallazgo operativo: `--env-file` explícito obligatorio en `docker compose build/up` con `-f deploy/*.yml`

- **Contexto:** Se implementó el rediseño visual Nocturne del SPA (tokens, shell, tarjeta de servicio mínima, iconos Phosphor) en `web/frontend`, sin cambios de lógica de negocio ni de backend. Detalle completo en `docs/PR/2026-07-29.md` y en `docs/web.md`. Al desplegarlo se detectó un problema operativo separado, no relacionado al frontend en sí, que vale la pena registrar porque puede repetirse con cualquier cambio futuro que toque `deploy/compose.yml` o `deploy/docker-compose.dev.yml`.
- **Hallazgo:** Ejecutar `docker compose -f deploy/compose.yml up -d --force-recreate <servicio>` (o el equivalente para `docker-compose.dev.yml`) **sin** pasar `--env-file .env` (o `.env.dev`) explícito hace que Compose no resuelva las variables `${POSTGRES_DB}` / `${POSTGRES_USER}` usadas directamente en el bloque `environment:` del servicio `postgres` — Compose por default solo busca un `.env` en el directorio del archivo compose (`deploy/`), no en la raíz del repo donde viven realmente `.env`/`.env.dev`. El resultado: Compose detecta una diferencia de configuración y **recrea también `postgres`**, con `POSTGRES_DB=` y `POSTGRES_USER=` vacíos en el contenedor recreado. El volumen de datos no se pierde (Postgres no reinicializa un `PGDATA` ya poblado) y el healthcheck puede seguir en `healthy`, pero el contenedor queda con env vars incorrectas hasta la próxima recreación con el flag correcto.
- **Decisión:** Todo comando `docker compose build` o `docker compose up` sobre `deploy/compose.yml` o `deploy/docker-compose.dev.yml` debe incluir siempre `--env-file .env` / `--env-file .env.dev` explícito, incluso cuando el objetivo es un único servicio (`web`, por ejemplo) que en apariencia no depende de esas variables. Los scripts `./Start` y `./scripts/start_dev.sh` ya lo hacen correctamente (arman `COMPOSE_BASE`/`COMPOSE_DEV` con `--env-file` incluido); el riesgo aparece únicamente al ejecutar comandos `docker compose` sueltos a mano.
- **Alternativas:** (1) Mover `.env`/`.env.dev` a `deploy/` para que coincida con el default de Compose — descartada porque rompe la convención vigente de raíz del repo y otros scripts que ya asumen esa ubicación. (2) Confiar en que nunca se ejecuten comandos manuales fuera de `./Start`/`start_dev.sh` — descartada por ser el escenario que efectivamente causó el problema.
- **Impacto:** Ninguna pérdida de datos; se corrigió recreando `postgres` una vez más con `--env-file` correcto. Se documenta acá para que cualquier intervención manual futura sobre estos composes (rebuild puntual de un servicio, debugging) pase primero por este hallazgo.
