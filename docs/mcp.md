# Nombre de archivo: mcp.md
# Ubicación de archivo: docs/mcp.md
# Descripción: Catálogo de herramientas MCP disponibles para el chatbot

# Capa MCP en LAS-FOCAS

La capa MCP (Model Context Protocol) abstrae la ejecución de herramientas del backend para que el chatbot del panel pueda invocarlas de forma segura y trazable.

## 📚 Registro de herramientas

Las herramientas se definen en `core/mcp/registry.py` mediante `ToolDefinition` y se registran en el `MCPRegistry` retornado por `get_default_registry()`.

| Nombre | Rol requerido | Descripción breve |
|--------|---------------|-------------------|
| `GenerarInformeRepetitividad` | `user` | Genera informe DOCX (y opcionalmente PDF/mapa) a partir de un XLSX cargado. |
| `GenerarMapaGeo` | `user` | Construye un mapa HTML con marcadores `lat/lon`. |
| `CompararTrazasFO` | `user` | Placeholder; registra solicitud mientras se completa la integración. |
| `ConvertirDocAPdf` | `ownergroup` / `admin` | Envía un documento al servicio `office_service` para conversión a PDF. |
| `RegistrarEnNotion` | `admin` | Placeholder para futura integración con Notion. |

## 🧾 Especificaciones de entrada/salida

### GenerarInformeRepetitividad

- **Input**

  ```json
  {
    "file_path": "chat_..._casos.xlsx",
    "mes": 9,
    "anio": 2025,
    "export_pdf": true
  }
  ```

- **Output (`result`)**

  ```json
  {
    "status": "ok",
    "docx": "/reports/Informe_Repetitividad_2025-09.docx",
    "pdf": "/reports/Informe_Repetitividad_2025-09.pdf",
    "map": "/reports/mapa_1696680000.html"
  }
  ```

- **Errores relevantes**: `FILE_NOT_FOUND`, `INVALID_TOOL_ARGS`, `TOOL_INTERNAL_ERROR`.

### GenerarMapaGeo

- **Input**: `{ "points": [{"lat": -34.6, "lon": -58.4, "label": "Nodo"}, ...], "out_path": "opcional.html" }`
- **Output**: `{ "status": "ok", "map": "/reports/mapa_1696681111.html" }`
- **Errores**: `INVALID_POINTS`, `MISSING_DEPENDENCY` (folium no instalado).

### CompararTrazasFO *(placeholder)*

- Registra la intención y devuelve `{ "status": "pending" }`. Se documentarán los parámetros cuando se integre el módulo definitivo.

### ConvertirDocAPdf

- **Input**: `{ "input_path": "chat_..._reporte.docx", "out_dir": "/app/data/reports" }`
- **Salida**: respuesta directa del microservicio `office_service` (`status`, `message`, `output_path`).
- **Errores**: `CONVERT_HTTP_ERROR`, `CONVERT_NETWORK_ERROR`.

### RegistrarEnNotion *(placeholder)*

- **Input**: `{ "page": "soporte/pendientes", "payload": {"titulo": "Ticket", ...} }`
- **Salida**: `{ "status": "pending" }` con log de auditoría.

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
- Para pruebas unitarias del orquestador puede utilizarse `InMemoryChatStorage` y registrar herramientas de prueba.

## 🚧 Próximos pasos

1. Integrar lógica real para `CompararTrazasFO` y `RegistrarEnNotion`.
2. Añadir métricas Prometheus (contador por herramienta, latencias).
3. Implementar autorizaciones más granuladas (rol vs. herramienta) desde DB.
4. Publicar colección Postman para `POST /mcp/invoke` y `/api/chat/uploads`.
