# Nombre de archivo: AGENTS.md
# Ubicación de archivo: AGENTS.md
# Descripción: Instrucciones para CODEX sobre el proyecto LAS-FOCAS

# AGENTS.md

Este documento está diseñado para orientar a **CODEX** en la comprensión del proyecto **LAS-FOCAS** y establecer las directrices para el desarrollo, asegurando consistencia en la estructura y propósito del código.

## 🎯 Objetivo del Proyecto

**LAS-FOCAS** es un sistema modular, dockerizado y diseñado para Debian 12.4, cuyo propósito principal es:

1. Automatizar informes operativos (Repetitividad, SLA, Comparador de trazas FO, etc.).
2. Actuar como asistente conversacional para tareas repetitivas.
3. Integrarse con sistemas internos de Metrotel a futuro.

## 📜 Alcance y Expectativas

* Migrar y adaptar módulos de **Sandy** a un entorno Linux.
* Implementar microservicios dockerizados con **PostgreSQL** como base de datos local.
* Proveer interfaces vía **Telegram Bot** (con IDs permitidos) y **Web Panel** (con login básico).
* Incorporar logs desde el inicio y documentar todo en `/docs`.
* Mantener la estructura modular para permitir la incorporación de un **agente autónomo** en el futuro.

## 📝 Primera Instrucción para CODEX

**Regla obligatoria:** Todo archivo modificable debe iniciar con un encabezado de 3 líneas con el siguiente formato:

```
# Nombre de archivo: <nombre_del_archivo.ext>
# Ubicación de archivo: <ruta_relativa_en_el_proyecto>
# Descripción: <breve_descripción_del_uso_o_función_del_archivo>
```

* Si el archivo ya existe y no tiene encabezado, agregarlo.
* Si es un archivo nuevo, crearlo con este encabezado incluido desde el inicio.

**Ejemplo:**

```
# Nombre de archivo: main.py
# Ubicación de archivo: sandy_bot/main.py
# Descripción: Archivo Main, en este se centralizan las funciones y operaciones del bot
```

## 📌 Instrucciones Generales

1. **Estructura de carpetas:** Respetar la organización definida en el README. No crear carpetas fuera de la estructura sin aprobación.
2. **Estilo de código:** Seguir PEP8 para Python. Nombres descriptivos, comentarios claros y docstrings en funciones y clases.
3. **Commits:** Usar mensajes de commit descriptivos en español, siguiendo formato "[módulo] Acción realizada".
4. **Logs:** Incluir logging en puntos clave del código. No usar `print()` en producción.
5. **Variables sensibles:** Nunca commitear `.env` ni credenciales. Usar `.env` y Docker Secrets cuando corresponda.
6. **Documentación:** Cualquier módulo nuevo debe tener su documentación en `/docs`.
7. **Pruebas:** Crear o actualizar tests para cualquier cambio funcional. Los tests deben pasar antes de mergear.
8. **Docker:** Mantener imágenes ligeras y basadas en versiones específicas, no usar `latest`.
9. **Dependencias:** Actualizar `requirements.txt` al añadir librerías y verificar compatibilidad.
10. **Integraciones externas:** Probar en entornos de staging antes de aplicar a producción.

## 📌 Instrucciones Generales Permanentes (para todas las interacciones de CODEX)

> Estas pautas aplican a **todo cambio en el repositorio**, a toda **implementación** y a cada **prompt** que se envíe a CODEX dentro del proyecto LAS-FOCAS.

### 1) Estilo de trabajo y alcance

* **Idioma:** siempre en español (código, commits, PRs y documentación).
* **Docker-first:** todo lo que pueda correr dockerizado debe correr en Docker/Compose. Evitar dependencias del host.
* **No usar `latest`:** fijar versiones (imágenes, librerías). Mantener reproducibilidad.
* **Idempotencia:** scripts y servicios deben poder ejecutarse múltiples veces sin efectos inesperados.
* **Fail-safe por defecto:** ante ambigüedad, usar valores por defecto seguros y documentarlos en el PR.
* **Cuando falte información:** proponer supuestos explícitos, implementar con placeholders y dejar `# TODO:` claros.

### 2) Formato estándar de prompts a CODEX

Todos los prompts deben seguir este esquema **en este orden**:

1. **Contexto** (qué es LAS-FOCAS, qué módulo/parte afecta, entorno y restricciones).
2. **Observaciones y Errores** (estado actual, huecos, bugs, riesgos, supuestos).
3. **Objetivo** (resultado esperado de negocio/técnico y límites del alcance).
4. **Tareas o configuraciones** (lista detallada, con archivos a crear/editar y contenido esperado).
5. **Criterios de aceptación** (tests, comportamiento, logs, endpoints, performance, seguridad).
6. **Entregables** (archivos, fragmentos de código, comandos, migraciones, docs a actualizar).
7. **Checklist de validación** (pasos manuales para verificar que funciona).

> Nota: La regla del **encabezado de 3 líneas** ya está definida en este AGENTS.md y se considera **obligatoria** para cada archivo nuevo o modificado.

### 3) Código y calidad

* **PEP8 + type hints**: usar anotaciones de tipo y `pydantic` para contratos.
* **Docstrings** en módulos, clases y funciones públicas.
* **Sin `print()` en producción**: usar `logging` con formato estructurado.
* **Tratamiento de errores:** timeouts definidos (HTTP default 15s), reintentos con backoff exponencial, manejo explícito de excepciones y mensajes de error útiles.
* **Dependencias:** mantener `requirements.txt`/`pyproject` actualizados y versionados; evitar paquetes no utilizados.
* **Estructura**: respetar la jerarquía del README (api/, bot_telegram/, nlp_intent/, core/, modules/, db/, deploy/, docs/, tests/).

### 4) Seguridad y confidencialidad

* **Principio de mínimos privilegios** (DB, contenedores, archivos). Usuario no root cuando sea viable.
* **Secrets:** nunca exponer claves/tokens en el código ni en logs. Usar `.env` y planificar migración a Docker Secrets.
* **Red interna:** servicios internos con `expose`, evitar `ports` hacia el host salvo interfaces públicas controladas.
* **Rate limiting** por ID en superficies expuestas (ej: bot), y validación/escape de entradas.
* **Dependabot/actualizaciones**: fijar versiones y programar revisiones periódicas.

### 5) Logs, métricas y trazabilidad

* **Logs estructurados** (JSON o clave=valor). Incluir `service`, `action`, `tg_user_id` (si aplica), `request_id` y timestamps.
* **Contenido sensible:** por defecto **no** loguear texto íntegro del usuario; habilitarlo solo si `LOG_RAW_TEXT=true`.
* **Persistencia de conversaciones:** según política actual, se **guardará el texto completo** en DB asociado al ID de Telegram y metadatos; documentar esta decisión en `docs/`.
* **Métricas**: exponer healthchecks y, cuando corresponda, contadores simples (req/s, latencias).

### 6) Pruebas y CI

* **pytest** obligatorio para módulos nuevos y cambios funcionales.
* **Cobertura mínima sugerida:** 60% para módulos nuevos en MVP (elevar gradualmente).
* **Mocks** para proveedores externos (OpenAI/Ollama/SMTP/etc.).
* **Tests de integración** básicos cuando se agreguen endpoints o servicios nuevos.
* Preparar workflows de **GitHub Actions** (CI) cuando el módulo esté estable.

### 7) Documentación viva

* Actualizar **README**, **AGENTS.md** y **requirements** cuando corresponda.
* En `/docs/` crear/actualizar la documentación específica del módulo tocado (ej.: `docs/bot.md`, `docs/nlp/intent.md`, `docs/db.md`).
* Mantener un registro de decisiones técnicas en `docs/decisiones.md` (formato breve: contexto → decisión → alternativas → impactos).

### 8) Docker/Infra

* **Compose**: redes internas por defecto, volúmenes nombrados, healthchecks cuando sea posible.
* **Imágenes ligeras** (slim, alpine si es viable) y multi-stage builds para reducir tamaño.
* **Recursos**: límites razonables de CPU/RAM en servicios no críticos.
* **Migraciones DB**: con Alembic (planificar e integrar); no romper esquemas en caliente.

### 9) Interacción del Bot

* **Baja confianza (<0.7)**: solicitar aclaración corta para elevar confianza (botones “Acción”/“Consulta” cuando aplique).
* **Acción detectada**: si el flujo no existe, responder “implementación pendiente” y registrar intención para backlog.
* **Mensajes de sistema**: ser claros, breves y accionables.

### 10) Rendimiento y resiliencia

* **Latencia objetivo (MVP):** flexible; priorizar estabilidad sobre velocidad en desarrollo.
* **Cache**/colas opcionales para tareas pesadas (Redis/Celery) conforme se necesite.
* **Circuit breaker** simplificado para proveedores externos (cortar tras N fallos y degradar a heurística/local).

---
