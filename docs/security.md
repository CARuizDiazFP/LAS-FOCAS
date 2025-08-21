# Nombre de archivo: security.md
# Ubicación de archivo: docs/security.md
# Descripción: Políticas de manejo de secrets, rate limiting y mínimo privilegio

## Secrets

- Las credenciales se gestionan mediante variables de entorno definidas en `.env` y no se versionan.
- Para producción se recomienda migrar a **Docker Secrets** o gestores como Vault.
- No se deben exponer tokens ni contraseñas en logs ni commits.

## Rate limiting

- Cada servicio debe definir límites de solicitudes por origen. Ejemplo: `API_RATE_LIMIT=60/minute`.
- Superar el límite genera respuestas `429 Too Many Requests` para proteger recursos.

## Principio de mínimo privilegio

- Los contenedores deben ejecutarse con usuarios no root cuando sea posible.
- La base de datos utiliza usuarios específicos por servicio y roles de solo lectura cuando aplique.
- Los puertos publicados al host se restringen únicamente a los necesarios.
