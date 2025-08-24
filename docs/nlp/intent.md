# Nombre de archivo: intent.md
# Ubicación de archivo: docs/nlp/intent.md
# Descripción: Documentación del microservicio nlp_intent

# Microservicio `nlp_intent`

Servicio FastAPI para clasificar mensajes de usuario en una de tres intenciones: **Consulta**, **Acción** u **Otros**.

## Endpoint

- `POST /v1/intent:classify`
- `GET /config` y `POST /config`
- `GET /metrics`
- `GET /health`

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
`confidence` se valida para permanecer entre `0` y `1`.
Campos devueltos:

- `intent`: intención detectada (`Consulta`, `Acción` u `Otros`).
- `confidence`: confianza del modelo en el rango `[0, 1]`.
- `provider`: proveedor que clasificó el texto.
- `normalized_text`: texto transformado previo a la inferencia.

## Integración con el bot de Telegram

El bot de Telegram consume `POST /v1/intent:classify` mediante `httpx` para
analizar los mensajes de los usuarios. Si la confianza devuelta es menor que
`INTENT_THRESHOLD` (0.7 por defecto), responde pidiendo una aclaración para
comprender mejor la intención.

## Orden de proveedores

1. Heurística local (rápida).
2. Ollama (`llama3`).
3. OpenAI API.

El servicio intenta cada proveedor en ese orden mientras la confianza sea menor al umbral configurado (`INTENT_THRESHOLD`, por defecto **0.7**).

## Configuración del proveedor LLM

El proveedor por defecto se define mediante la variable `LLM_PROVIDER`.
Valores admitidos: `auto`, `heuristic`, `ollama` y `openai`.

El endpoint `/config` permite consultar o modificar este valor en tiempo de ejecución.

### `GET /config`

Devuelve el proveedor configurado:

```json
{ "llm_provider": "heuristic" }
```

### `POST /config`

Actualiza el proveedor activo:

```json
{ "llm_provider": "openai" }
```

## Caché

Las respuestas de clasificación se almacenan en memoria durante `CACHE_TTL` segundos (300 por defecto). Esta duración se configura con la variable de entorno `CACHE_TTL`. Si un texto se repite dentro de ese período, la respuesta se devuelve desde caché evitando recalcularla.

## Métricas

El endpoint `GET /metrics` expone estadísticas en formato **Prometheus**. Ejemplo truncado:

```
# HELP nlp_intent_requests_total Total de solicitudes de clasificación procesadas
# TYPE nlp_intent_requests_total counter
nlp_intent_requests_total 2.0
```

Actualmente se registran el total de solicitudes y un histograma de latencias.

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
