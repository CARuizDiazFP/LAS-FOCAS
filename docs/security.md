# Nombre de archivo: security.md
# Ubicación de archivo: docs/security.md
# Descripción: Políticas de manejo de secrets, rate limiting y mínimo privilegio

## Secrets

- Las credenciales se gestionan mediante **Docker Secrets** montados en `/run/secrets/*`.
- Secretos usados: `postgres_password`, `telegram_bot_token`, `openai_api_key`, `smtp_host`, `smtp_user`, `smtp_password`, `smtp_from`, `web_admin_username`, `web_admin_password`, `web_lector_username`, `web_lector_password` y `notion_token`.
- Para crear un secreto, generar el archivo en `deploy/secrets/<nombre>`:
  ```bash
  echo "valor" > deploy/secrets/postgres_password
  ```
  Luego reiniciar los servicios con `docker compose -f deploy/compose.yml up -d`.
- Para rotar un secreto, actualizar el archivo correspondiente y volver a desplegar el servicio que lo consume.
- No se deben exponer tokens ni contraseñas en logs ni commits.

### Política de rotación

- Todos los secretos y credenciales deben rotarse al menos cada 90 días.
- La rotación incluye los servicios activados mediante perfiles opcionales como `worker` o `pgadmin`.
- Registrar en `docs/decisiones.md` cualquier rotación que implique cambios operativos.

## Rate limiting

- Cada servicio debe definir límites de solicitudes por origen. Ejemplo: `API_RATE_LIMIT=60/minute`.
- Superar el límite genera respuestas `429 Too Many Requests` para proteger recursos.

## Principio de mínimo privilegio

- Los contenedores deben ejecutarse con usuarios no root cuando sea posible.
- La base de datos utiliza usuarios específicos por servicio y roles de solo lectura cuando aplique.
- Los puertos publicados al host se restringen únicamente a los necesarios.
