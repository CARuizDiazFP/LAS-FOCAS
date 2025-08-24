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




## Métricas

- **Ruta:** `GET /metrics`
- **Descripción:** expone contadores básicos del servicio.
- **Respuesta:**

```json
{
  "total_requests": 0,
  "average_latency_ms": 0.0
}
```


## Rate limiting

- **Variable:** `API_RATE_LIMIT` (por defecto `60/minute`).
- **Clave:** encabezado `X-API-Key`.
- **Descripción:** Cada clave cuenta con su propio límite. Si no se envía, se utiliza la IP remota. Al superar el límite se responde con `429 Too Many Requests`.

## Logging y `request_id`

- Cada solicitud genera un encabezado `X-Request-ID` y se propaga en los logs.
- Los registros se emiten en formato JSON con los campos `service`, `action`, `tg_user_id` y `request_id` para facilitar la trazabilidad.

## Informes asíncronos

- **Ruta:** `POST /informes/repetitividad`
- **Descripción:** encola la generación del informe de repetitividad y devuelve el identificador del job.
- **Respuesta:** `{ "job_id": "<id>" }`

- **Ruta:** `GET /informes/jobs/{job_id}`
- **Descripción:** consulta el estado de un job previamente encolado.
- **Respuesta:** `{ "status": "queued" | "finished" | "failed" }`
