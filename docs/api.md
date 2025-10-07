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

## Informes
## NLP Intención

### POST `/v1/intent:classify` (DEPRECADO)
Devuelve intención básica (Consulta|Acción|Otros).

### POST `/v1/intent:analyze`
Analiza el texto y retorna estructura enriquecida:

```json
{
  "intention_raw": "Consulta",
  "intention": "Consulta/Generico",
  "confidence": 0.91,
  "provider": "openai",
  "normalized_text": "como genero el informe sla",
  "need_clarification": false,
  "clarification_question": null,
  "next_action": null,
  "action_code": null,
  "action_supported": null,
  "action_reason": null,
  "answer": "Explicación breve ...",
  "answer_source": "openai",
  "domain_confidence": 0.85,
  "schema_version": 2
}
```

Campos adicionales cuando es invocado desde Web Chat autenticado:

```json
{
  "conversation_id": 17,
  "history": [ {"role":"user", "text":"hola"}, {"role":"assistant", "text":"¿Podrías ampliar?"} ]
}
```

## Web Chat (servicio web)

### POST `/api/chat/message`
Proxy hacia `/v1/intent:analyze` que además:
- Sanitiza caracteres de control (excepto `\n`, `\t`).
- Persiste mensaje y respuesta en DB (`app.conversations`, `app.messages`).
- Devuelve `conversation_id` y `history` (≤6 últimos mensajes) del usuario autenticado.

### GET `/api/chat/history?limit=N`
Devuelve últimos N (máx 100) mensajes persistidos de la conversación del usuario y su `conversation_id`.

### GET `/api/chat/metrics`
Retorna contador en memoria de intenciones clasificadas (`intent_counts`). Reinicia al reiniciar el contenedor (no persistente, sólo observabilidad rápida).
Si se configura `METRICS_PERSIST_PATH` (o se usa default del servicio web) el archivo JSON de métricas se reescribe en disco tras cada incremento para conservar el conteo entre reinicios.

Notas:
- `intention` mapea las etiquetas raw a la taxonomía unificada.
- Si `need_clarification=true`, `clarification_question` contendrá una pregunta breve.
- `next_action` se reserva para futura orquestación de flujos.


### POST `/reports/repetitividad`

- **Descripción:** Genera el informe de repetitividad a partir de un Excel `.xlsx` y devuelve el archivo `.docx`. Si se envía `incluir_pdf=true` también se adjunta un `.zip` con el PDF generado mediante LibreOffice headless.
- **Parámetros (form-data):**
  - `file` (UploadFile, requerido): Excel con columnas `CLIENTE`, `SERVICIO`, `FECHA`, `ID_SERVICIO` (opcional).
  - `periodo_mes` (int, 1-12, requerido).
  - `periodo_anio` (int, 2000-2100, requerido).
  - `incluir_pdf` (bool, opcional, por defecto `false`).
- **Respuestas:**
  - `200 OK` → `Content-Type` `application/vnd.openxmlformats-officedocument.wordprocessingml.document` o `application/zip`.
  - `400 Bad Request` si el archivo no es `.xlsx` o faltan columnas requeridas.
- **Encabezados de respuesta:**
  - `X-PDF-Requested`: `true` si el cliente envió `incluir_pdf=true`, `false` en caso contrario.
  - `X-PDF-Generated`: `true` cuando se generó y adjuntó un PDF (ZIP); `false` si LibreOffice no estaba disponible o no se pidió.
- **Notas:**
  - La conversión a PDF sólo se intenta cuando `incluir_pdf=true` *y* el binario configurado en `SOFFICE_BIN` existe en el contenedor.
  - Si el PDF no puede generarse, la respuesta se degrada a DOCX sin error y `X-PDF-Generated=false`.
- **Dependencias:** utiliza `modules.informes_repetitividad` + plantillas de `Templates/` y, si está configurado, `SOFFICE_BIN` o el servicio `office_service` para la conversión a PDF.
