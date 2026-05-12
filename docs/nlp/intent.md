# Nombre de archivo: intent.md
# Ubicación de archivo: docs/nlp/intent.md
# Descripción: Documentación del microservicio nlp_intent

# Microservicio `nlp_intent`

Servicio FastAPI para clasificar mensajes de usuario en una de tres intenciones: **Consulta**, **Acción** u **Otros**. En operación estándar, el proveedor LLM por defecto es externo vía API (`openai`); el modo heurístico se conserva para desarrollo y pruebas.

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

## Selección de proveedores

1. `heuristic` si `LLM_PROVIDER=heuristic`.
2. `openai` si `LLM_PROVIDER=openai`.
3. `auto` sólo para retrocompatibilidad; intenta heurística, luego Ollama y finalmente OpenAI.

La topología operativa del proyecto ya no depende de Ollama local. Si se habilita `auto` u `ollama`, se trata de compatibilidad heredada y no del despliegue recomendado.

## Baja confianza

Si `confidence < INTENT_THRESHOLD`, el bot pedirá una aclaración al usuario para mejorar la interpretación del mensaje.

## Ejemplos de uso

- "hola, ¿cómo va?" → Otros
- "¿cómo genero el reporte de repetitividad?" → Consulta
- "generá el reporte de repetitividad de agosto 2025" → Acción

