# Nombre de archivo: mcp.md
# Ubicación de archivo: docs/mcp.md
# Descripción: Catálogo de herramientas MCP disponibles para el chatbot

# Capa MCP en LAS-FOCAS

La capa MCP (Model Context Protocol) abstrae la ejecución de herramientas del backend para que el chatbot del panel pueda invocarlas de forma segura y trazable.

## 📚 Registro de herramientas

Las herramientas se definen en `core/mcp/registry.py` mediante `ToolDefinition` y se registran en el `MCPRegistry` retornado por `get_default_registry()` (`list_tools()` devuelve los nombres). Sólo se registran herramientas que funcionan en el contenedor `web`: una herramienta sin implementación no se expone para fallar después.

| Nombre | Rol requerido | Estado | Depende de |
|--------|---------------|--------|------------|
| `GenerarInformeRepetitividad` | `user` / `admin` | Operativa | `modules/informes_repetitividad` (PDF vía `office:8090`; si falla, `pdf_error` en el resultado) |
| `ConvertirDocAPdf` | `admin` / `ownergroup` | Operativa (2026-10-26) | Servicio `office` (`OFFICE_SERVICE_BASE`, default `http://office:8090`), `POST /convert` |

**Cómo se llega a ellas.** No hay un LLM que elija herramientas: el orquestador (`core/chatbot/orchestrator.py`) las invoca por comando de texto en el WebSocket `/ws/chat` (`/repetitividad mes=9 anio=2025` con un `.xlsx` adjunto) o por pedido explícito `tool_call` (WebSocket o `POST /mcp/invoke`). El chat del SPA (`ChatTab.vue`) usa `/api/chat/message` (clasificación NLP) y hoy no invoca herramientas MCP.

**Retiradas el 2026-10-26** (auditoría integral, P13; ver `docs/PR/2026-10-26.md`):

| Nombre | Motivo |
|--------|--------|
| `GenerarMapaGeo` | Importaba `folium`, que no está en la imagen `web` (sólo en `api`): devolvía siempre `MISSING_DEPENDENCY`. Se quitó también el comando `/mapa`. |
| `CompararTrazasFO` | Stub que devolvía `pending`. No existe un comparador de trazas FO al que conectarla (`POST /api/flows/comparador-fo` responde 501; `web/tools/vlan_comparator.py` compara VLANs Cisco). Se quitó el comando `/comparador`. |
| `RegistrarEnNotion` | Stub sin configuración de Notion en el código ni en `env.sample`, sin dueño. |

Un nombre retirado responde `TOOL_NOT_FOUND`.

## 🧾 Especificaciones de entrada/salida

### GenerarInformeRepetitividad

- **Input**

  ```json
  {
    "file_path": "chat_..._casos.xlsx",
    "mes": 9,
    "anio": 2025,
    "export_pdf": true,
    "with_geo": false
  }
  ```

  `file_path` relativo se resuelve contra `UPLOADS_DIR`.

- **Output (`result`)**

  ```json
  {
    "status": "ok",
    "docx": "/reports/Informe_Repetitividad_2025-09.docx",
    "pdf": "/reports/Informe_Repetitividad_2025-09.pdf",
    "maps": [],
    "map_images": ["/reports/maps_202509/repetitividad_202509_X.png"],
    "with_geo": false
  }
  ```

- **Errores relevantes**: `FILE_NOT_FOUND`, `INVALID_TOOL_ARGS`, `TOOL_INTERNAL_ERROR`.

### ConvertirDocAPdf

- **Input**: `{ "input_path": "chat_..._reporte.docx" }`. Ruta relativa a `UPLOADS_DIR`, o absoluta **dentro** de `UPLOADS_DIR` o `REPORTS_DIR`; cualquier otra (`../`, `/etc/...`) se rechaza antes de leer el disco. El campo `out_dir` de la versión anterior ya no existe (se ignora si llega).
- **Flujo**: lee el archivo, lo sube multipart a `{OFFICE_SERVICE_BASE}/convert?output_format=pdf` (timeout 150 s) y guarda el PDF en `REPORTS_DIR/<nombre>.pdf`.
- **Output**: `{ "status": "ok", "input": "chat_..._reporte.docx", "pdf": "/reports/chat_..._reporte.pdf" }`.
- **Formatos**: `.docx`, `.doc`, `.odt`, `.rtf` (la imagen de `office` sólo trae Writer); máximo 50 MB. Ver `docs/office_service.md`.
- **Errores**: `INVALID_PATH`, `FILE_NOT_FOUND`, `CONVERT_HTTP_ERROR` (rechazo, timeout, archivo de más de 50 MB o respuesta que no es PDF; el detalle trae la respuesta de office, p. ej. extensión no soportada), `CONVERT_NETWORK_ERROR`. Convierte con el cliente compartido `core/services/office_client.py` (desde P16).

## 🛡️ Auditoría

Cada invocación registra un log `action=mcp_tool_call` con:

- `tool`: nombre de la herramienta.
- `user_id` y `session_id`.
- `duration_ms` de la ejecución.

Las excepciones se capturan como `action=mcp_tool_exception` con detalle y stacktrace.

## 🔁 Invocación HTTP (`POST /mcp/invoke`)

Ejemplo usando `curl` (requiere sesión activa y cookie):

```bash
curl -X POST https://panel.local/mcp/invoke \
  -H 'Content-Type: application/json' \
  -d '{
    "tool": "GenerarInformeRepetitividad",
    "args": {"file_path": "chat_...xlsx", "mes": 9, "anio": 2025}
  }'
```

La respuesta incluye cada evento emitido por el orquestador (útil para depurar flujos de streaming sin abrir el panel).

## 🧪 Pruebas y dobles

- `tests/test_mcp_registry.py` verifica registros duplicados, validación y respuesta base.
- `tests/test_mcp_herramientas.py` prueba cada herramienta del registro por defecto (éxito y error), con el HTTP de office simulado con `httpx.MockTransport` (se reemplaza `core.services.office_client._cliente`).
- `tests/test_office_service_convert.py` prueba `POST /convert` de office con `soffice` simulado.
- `tests/test_office_client.py` prueba el cliente compartido (éxito, timeout, 4xx/5xx, no-PDF, archivo grande); `-m office_real` con `OFFICE_REAL_URL` lo corre contra un office real.
- Para pruebas unitarias del orquestador puede utilizarse `InMemoryChatStorage` y registrar herramientas de prueba.

## 🚧 Próximos pasos

1. Añadir métricas Prometheus (contador por herramienta, latencias).
2. Implementar autorizaciones más granuladas (rol vs. herramienta) desde DB.
3. Publicar colección Postman para `POST /mcp/invoke` y `/api/chat/uploads`.
