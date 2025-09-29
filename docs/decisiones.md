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
