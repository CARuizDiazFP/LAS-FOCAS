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
- Decisión: Unificar la URL base expuesta en código, variables de entorno y documentación a la IP privada de la VM: http://192.168.241.28:8080. En containers, healthchecks siguen usando localhost interno.
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
- Decisión: Eliminar Passlib y utilizar la librería nativa `bcrypt` desde `core/password.py`, centralizando truncado seguro, rounds y verificación para web, tests y utilidades CLI.
- Alternativas: Migrar directamente a `argon2-cffi` (más costoso en CPU) o mantener Passlib. Se optó por `bcrypt` nativo para compatibilidad con hashes existentes y simplicidad, dejando abierta la migración futura a Argon2.
- Impacto: Se retira una dependencia obsoleta, se reducen advertencias y se simplifica el mantenimiento al tener un único módulo responsable del hashing.

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
