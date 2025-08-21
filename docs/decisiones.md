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
