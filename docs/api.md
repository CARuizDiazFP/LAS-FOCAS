# Nombre de archivo: api.md
# Ubicación de archivo: docs/api.md
# Descripción: Documentación básica de la API y del endpoint de salud

## Endpoint de salud

- **Ruta:** `GET /health`
- **Descripción:** Verifica el estado del servicio y la conexión a la base de datos.
- **Respuesta:**

  ```json
  {
    "status": "ok",
    "service": "api",
    "time": "2024-01-01T00:00:00+00:00",
    "db": "ok",
    "server_version": "16.0"
  }
  ```

## Verificación de base de datos

- **Ruta:** `GET /db-check`
- **Descripción:** Ejecuta un `SELECT 1` y devuelve la versión del servidor PostgreSQL.
- **Respuesta exitosa:**

  ```json
  {
    "db": "ok",
    "server_version": "16.0"
  }
  ```

- **Respuesta con error:**

  ```json
  {
    "db": "error",
    "detail": "detalle del error"
  }
  ```

  El campo `detail` incluye el mensaje original de la excepción capturada.


## Rate limiting

- **Variable:** `API_RATE_LIMIT` (por defecto `60/minute`).
- **Descripción:** Limita la cantidad de solicitudes que puede realizar un mismo origen. Si se supera el límite, el servicio responde con `429 Too Many Requests`.
