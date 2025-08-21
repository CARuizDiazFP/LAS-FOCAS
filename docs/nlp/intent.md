# Nombre de archivo: intent.md
# Ubicación de archivo: docs/nlp/intent.md
# Descripción: Documentación del microservicio nlp_intent

# Microservicio `nlp_intent`

Servicio FastAPI para clasificar mensajes de usuario en una de tres intenciones: **Consulta**, **Acción** u **Otros**.

## Endpoint

- `POST /v1/intent:classify`
- `GET /metrics`

### Request
```json
{ "text": "generá el informe SLA de julio" }
```

### Response
```json
{
  "intent": "Acción",
  "confidence": 0.90,
  "provider": "heuristic",
  "normalized_text": "generá el informe sla de julio"
}
```

## Orden de proveedores

1. Heurística local (rápida).
2. Ollama (`llama3`).
3. OpenAI API.

El servicio intenta cada proveedor en ese orden mientras la confianza sea menor al umbral configurado (`INTENT_THRESHOLD`, por defecto **0.7**).

## Caché

Las respuestas de clasificación se almacenan en memoria durante `CACHE_TTL` segundos (300 por defecto). Esta duración se configura con la variable de entorno `CACHE_TTL`. Si un texto se repite dentro de ese período, la respuesta se devuelve desde caché evitando recalcularla.

## Métricas

El endpoint `GET /metrics` devuelve estadísticas básicas:

```json
{
  "total_requests": 42,
  "average_latency_ms": 12.5
}
```

`total_requests` cuenta las llamadas a `/v1/intent:classify` y `average_latency_ms` es la latencia promedio.

## Healthcheck

El contenedor ejecuta `app/healthcheck.sh` que consulta `http://localhost:8100/health` para asegurar que el servicio responda.


## Resiliencia ante fallos

Cada proveedor externo mantiene un contador de errores. Tras **3** fallos consecutivos, ese proveedor se desactiva y el servicio se degrada a la heurística local para evitar más errores.

## Baja confianza

Si `confidence < INTENT_THRESHOLD`, el bot pedirá una aclaración al usuario para mejorar la interpretación del mensaje.

## Ejemplos de uso

- "hola, ¿cómo va?" → Otros
- "¿cómo genero el reporte de repetitividad?" → Consulta
- "generá el reporte de repetitividad de agosto 2025" → Acción


## Rate limiting

- **Variable:** `NLP_RATE_LIMIT` (por defecto `60/minute`).
- **Descripción:** Controla cuántas clasificaciones puede hacer una misma IP en un período dado. Al excederlo, se responde con `429 Too Many Requests`.

## Logging y `request_id`

- Cada solicitud genera un encabezado `X-Request-ID` y se registra en los logs.
- Los logs se emiten en formato JSON con los campos `service`, `action`, `tg_user_id` y `request_id`.
