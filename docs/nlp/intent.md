# Nombre de archivo: intent.md
# Ubicación de archivo: docs/nlp/intent.md
# Descripción: Documentación del microservicio nlp_intent

# Microservicio `nlp_intent`

Servicio FastAPI para clasificar mensajes de usuario en una de tres intenciones: **Consulta**, **Acción** u **Otros**.

## Endpoint

- `POST /v1/intent:classify`

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

## Baja confianza

Si `confidence < INTENT_THRESHOLD`, el bot pedirá una aclaración al usuario para mejorar la interpretación del mensaje.

## Ejemplos de uso

- "hola, ¿cómo va?" → Otros
- "¿cómo genero el reporte de repetitividad?" → Consulta
- "generá el reporte de repetitividad de agosto 2025" → Acción

