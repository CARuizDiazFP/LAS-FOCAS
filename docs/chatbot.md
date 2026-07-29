# Nombre de archivo: chatbot.md
# Ubicación de archivo: docs/chatbot.md
# Descripción: Documentación del chatbot de la SPA web y su canal WebSocket

# Chatbot de la SPA Web

El chatbot de la SPA Web expone un WebSocket autenticado que conecta la interfaz Vue 3 con el orquestador MCP del backend.

## 🔌 Conexión WebSocket

- **URL:** `/ws/chat`
- **Protocolo:** WebSocket seguro (`wss`) o `ws` según esquema de la página.
- **Autenticación:** reutiliza la cookie de sesión del panel. Si no existe sesión válida, el servidor emite un `error` con `metadata.code = WS_UNAUTHORIZED` y cierra la conexión con código `4401`.
- **Orígenes admitidos:** configurables vía `WEB_CHAT_ALLOWED_ORIGINS` (lista separada por comas). Si no se define, se acepta el mismo host del panel.

### Mensaje de inicialización

Tras aceptar la conexión, el servidor envía:

```json
{
  "type": "history_snapshot",
  "messages": [
    {
      "id": 42,
      "role": "assistant",
      "content": "Hola, ¿en qué puedo ayudarte?",
      "created_at": "2025-10-07T18:30:11.712345"
    }
  ]
}
```

Los mensajes se ordenan de más antiguos a más recientes y excluyen eventos internos de herramientas. Si la sesión caducó, se registra un mensaje informando que es necesario volver a iniciar sesión en el panel.

## 📨 Contrato de mensajes

### Mensajes salientes del cliente

- **Mensaje libre del usuario**

  ```json
  {
    "type": "user_message",
    "content": "Necesito el informe de repetitividad de septiembre",
    "attachments": [
      { "name": "casos.xlsx", "path": "chat_..._casos.xlsx" }
    ]
  }
  ```

- **Tool-call explícito**

  ```json
  {
    "type": "tool_call",
    "tool": "GenerarInformeRepetitividad",
    "args": { "file_path": "chat_..._casos.xlsx", "mes": 9, "anio": 2025 },
    "attachments": []
  }
  ```

Los adjuntos deben subirse previamente mediante `POST /api/chat/uploads` (ver más abajo). El backend rellenará automáticamente `file_path` para comandos `/repetitividad` cuando exista al menos un adjunto.

### Eventos emitidos por el servidor

- `history_snapshot`: historial inicial.
- `assistant_delta`: fragmentos de texto que permiten streaming.
- `assistant_done`: marca el final de la respuesta; incluye `metadata.result` con enlaces relativos (DOCX/PDF/mapa) y `metadata.tool` con la herramienta ejecutada.
- `error`: errores amigables con `metadata.code` (`WS_BAD_REQUEST`, `WS_UNAUTHORIZED`, `WS_TOOL_ERROR`, `WS_INTERNAL_ERROR`, `WS_SESSION_ERROR`).

## 💾 Persistencia

El historial se almacena en PostgreSQL en las tablas `app.chat_sessions` y `app.chat_messages` (ver migración `20251007_01`). Cada mensaje guarda:

- `role`: `user`, `assistant` o `tool`.
- `content`: texto mostrado al usuario.
- `tool_name` y `tool_args`: trazabilidad de la herramienta MCP utilizada.
- `attachments`: JSON con archivos referenciados.
- `error_code`: código de error de negocio (cuando aplica).

Índices relevantes creados por las migraciones recientes:

- `app.ix_chat_messages_session_created` y `app.ix_chat_messages_role_created` para ordenar el historial y filtrar por rol.
- `app.uq_chat_sessions_user_active` evita sesiones duplicadas por usuario.
- `app.ix_chat_sessions_last_activity` acelera los listados por última actividad.

El endpoint `GET /api/chat/ws-history?limit=40` devuelve una vista JSON del historial persistido.

## 📎 Adjuntos

- Endpoint: `POST /api/chat/uploads`
- Autenticación: requiere sesión y token CSRF (omitido únicamente cuando `TESTING=true`).
- Límite por archivo: configurable con `CHAT_UPLOAD_MAX_BYTES` (por defecto 15 MB).
- Tipos admitidos: `.xlsx`, `.xlsm`, `.csv`, `.txt`, `.json`, `.pdf`, `.docx`. Otros formatos reciben HTTP 415.
- Auditoría: cada carga emite `action=chat_upload` con nombre, tamaño y nombre almacenado.
- Respuesta:

  ```json
  {
    "status": "ok",
    "name": "casos.xlsx",
    "path": "chat_1696680000_ABCDcasos.xlsx",
    "size": 123456
  }
  ```

El campo `path` se usa como `file_path` para las herramientas MCP.

## 🔧 API auxiliar MCP

- `POST /mcp/invoke` permite invocar herramientas manualmente (útil para pruebas desde Postman o curl).
- Payload: `{ "tool": "GenerarInformeRepetitividad", "args": {...} }`
- Respuesta: lista de eventos emitidos por el orquestador; los errores inesperados devuelven HTTP 500 con mensaje descriptivo.

## 🧪 Testing

- El orquestador puede ejecutarse en memoria usando `core.chatbot.storage.InMemoryChatStorage`.
- Durante los tests, cuando `TESTING=true`, el WebSocket acepta el encabezado `X-Test-User: usuario:rol` para simular sesiones.
- Tests clave: `tests/test_chat_orchestrator.py`, `tests/test_mcp_registry.py`.

## 🛠️ Operación y monitoreo

- Logs estructurados (`action=chat_ws_connected`, `action=mcp_tool_call`, etc.) registran usuario, herramienta y latencia.
- Metricas globales del chat legacy permanecen disponibles en `/api/chat/metrics` (se añadirán contadores específicos MCP en próximas iteraciones).
- Revisar `web/logs/web.log` para diagnósticos de conexión.

## ✅ Checklist de despliegue

1. Ejecutar migraciones: `alembic -c db/alembic.ini upgrade head`.
2. Montar `REPORTS_DIR` y `UPLOADS_DIR` como volúmenes compartidos entre servicios (panel, API, workers).
3. Configurar `WEB_CHAT_ALLOWED_ORIGINS` con la URL del panel (por ejemplo `https://panel.metrotel.local`).
4. Verificar health manual conectándose al panel e inspeccionando que el estado del chat cambie a “Conectado”.
