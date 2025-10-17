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

### Versión

- **Ruta:** `GET /health/version`
- **Descripción:** Devuelve la versión de build del servicio (cuando está habilitado).
  ```json
  { "status": "ok", "service": "api", "version": "2025-10-14T12:00:00Z" }
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
### POST `/reports/repetitividad`

Genera el informe de Repetitividad para un mes/año determinado ya sea a partir de un archivo Excel cargado por el usuario (modo Excel) o directamente desde la base de datos (modo DB, si no se adjunta archivo).

#### Descripción general
Procesa los casos del período indicado, calcula métricas de repetitividad y construye un documento DOCX basado en la plantilla oficial `Plantilla_Informe_Repetitividad.docx`. Las Horas Netas se normalizan a minutos enteros y al renderizar el informe se muestran como `HH:MM`. Cuando hay datos georreferenciados genera un PNG por servicio repetitivo usando `matplotlib` (con tiles de `contextily` si están disponibles) y adjunta las rutas en la respuesta. Si se solicita, intenta producir un PDF (LibreOffice headless vía `SOFFICE_BIN`). Cuando existen PDFs y/o mapas, el endpoint empaqueta todos los artefactos en un ZIP.

#### Parámetros (multipart/form-data)
| Campo | Tipo | Requerido | Validación | Descripción |
|-------|------|-----------|------------|-------------|
| `file` | UploadFile (.xlsx) | No | Si se envía, debe ser `.xlsx` | Si está presente se usa modo Excel; si falta, se usa modo DB consultando `app.reclamos` por período. |
| `periodo_mes` | int | Sí | 1 ≤ mes ≤ 12 | Mes del período a procesar |
| `periodo_anio` | int | Sí | 2000 ≤ año ≤ 2100 | Año del período |
| `incluir_pdf` | bool | No | Default `false` | Si es `true`, intenta adjuntar PDF (requiere LibreOffice disponible) |

#### Respuestas
1. **200 OK (DOCX)**
  - `Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document`
  - Se devuelve solo el DOCX cuando no se solicitó PDF y no existen mapas generados.
2. **200 OK (ZIP)**
  - `Content-Type: application/zip`
  - El ZIP incluye siempre el DOCX y, si corresponde, el PDF (`incluir_pdf=true` + conversión exitosa) y todos los mapas PNG generados (`repetitividad_<YYYY><MM>_*.png`).
3. **400 Bad Request**
  - Archivo sin extensión `.xlsx`, payload vacío o parámetros fuera de rango.
4. **404 Not Found (modo DB)**
  - Sin datos en la base para el período solicitado.
5. **500 Internal Server Error**
  - Errores inesperados durante la normalización o la escritura se registran y devuelven mensaje genérico.

#### Encabezados personalizados
| Header | Valores | Significado |
|--------|---------|-------------|
| `X-Source` | `excel` / `db` | Fuente de datos utilizada.
| `X-With-Geo` | `true` / `false` | Indica si el cálculo incluyó georreferenciación.
| `X-PDF-Requested` | `true` / `false` | Se solicitó PDF (`incluir_pdf=true`).
| `X-PDF-Generated` | `true` / `false` | El PDF se generó correctamente y se agregó al ZIP.
| `X-Map-Generated` | `true` / `false` | Existen mapas PNG en la respuesta.
| `X-Maps-Count` | entero | Cantidad de archivos PNG generados.
| `X-Map-Filenames` | lista separada por comas | Nombres de los mapas incluidos en el ZIP.
| `X-Total-Filas` / `X-Total-Repetitivos` | entero | Métricas básicas usadas en la UI.

#### Ejemplos
Solicitud (cURL ilustrativo):
```
curl -X POST \
  -F "file=@casos_julio.xlsx" \
  -F "periodo_mes=7" \
  -F "periodo_anio=2024" \
  -F "incluir_pdf=true" \
  http://localhost:8000/reports/repetitividad -OJ
```

Respuesta (ZIP) con encabezados:
```
HTTP/1.1 200 OK
Content-Type: application/zip
Content-Disposition: attachment; filename=repetitividad_202407.zip
X-PDF-Requested: true
X-PDF-Generated: true
X-Map-Generated: true
X-Maps-Count: 3
X-Map-Filenames: repetitividad_202407_servicio_a.png,repetitividad_202407_servicio_b.png,repetitividad_202407_servicio_c.png
```

#### Notas de implementación
- Mapas: `core.maps.static_map` utiliza `matplotlib` con backend Agg y agrega basemap de `contextily`+`pyproj` cuando están instalados; en ausencia de tiles, queda un scatter sobre lat/lon.
- Las imágenes generadas se escalan automáticamente para no superar media hoja A4 dentro del DOCX.
- Dependencias del sistema: las imágenes Docker instalan `gdal-bin`, `libgdal-dev`, `libproj-dev`, `libgeos-dev` y `build-essential` para soportar `pyproj/rasterio`.
- La conversión a PDF se realiza sólo si `incluir_pdf=true` y `SOFFICE_BIN` apunta a un binario válido (modo directo) o se integra a futuro con `office_service`.
- Si la conversión falla, se devuelve el DOCX sin elevar excepción (fail-safe) y `X-PDF-Generated=false`.
- Los archivos se escriben en el directorio configurado (`REPORTS_DIR`). Limpiar o rotar periódicamente para evitar acumulación.
- Validar tamaño máximo del Excel (pendiente: establecer límite y documentación — TODO).
- `core.utils.timefmt` centraliza la conversión de valores de Horas Netas (decimales, `HH:MM`, `timedelta`, enteros) a minutos enteros y los formatea luego como `HH:MM`.

### GET `/reports/repetitividad`

Devuelve métricas básicas del período consultando la DB.

- Parámetros: `periodo_mes` (1-12), `periodo_anio` (2000-2100)
- Respuesta 200:
  ```json
  { "periodo": "2024-07", "total_servicios": 123, "servicios_repetitivos": 17 }
  ```

Notas:
- Requiere que la tabla `app.reclamos` exista (migraciones Alembic aplicadas) y que las variables de conexión estén configuradas.

### Ingesta de reclamos (nuevo)

- **Ruta:** `POST /ingest/reclamos`
- **Descripción:** Normaliza y resume un archivo XLSX/CSV con reclamos (fechas, duraciones, GEO opcional). Útil para prevalidar datasets antes de generar reportes.
- **Respuesta (ejemplo):**
  ```json
  {
    "rows_ok": 1200,
    "rows_bad": 14,
    "date_min": "2025-07-01",
    "date_max": "2025-07-31",
    "geo_available": true,
    "geo_pct": 77.4
  }
  ```

  Las Horas Netas aceptan formatos `HH:MM[:SS]`, decimales (`1,5`) o enteros y se convierten a minutos (`Int64`).

#### Seguridad y consideraciones
- El endpoint no exige aún autenticación ni rate limiting: agregar API key / token interno (TODO) antes de exponer en ambientes sensibles.
- Los datos cargados se procesan con `pandas` (openpyxl). No se evalúa código embebido en el XLSX.
- Se recomienda escanear/limitar tamaño de archivo para mitigar ataques de compresión o payloads muy grandes.

## Migraciones Alembic y Start

- El script `./Start` ejecuta las migraciones Alembic dentro del contenedor `api` luego de que PostgreSQL esté healthy.
- Para alinear credenciales, `Start` construye `ALEMBIC_URL` a partir de `.env` (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`).
- Asegurate de revisar `deploy/env.sample` y crear `.env` acorde; por defecto, las credenciales de ejemplo son `FOCALBOT` / `LASFOCAS2026!` y DB `FOCALDB`.

#### Códigos de error resumidos
| Código | Causa principal | Mitigación |
|--------|-----------------|------------|
| 400 | Extensión distinta a `.xlsx` / parámetros fuera de rango | Corregir entrada |
| 500 | Error de parsing / columnas faltantes / fallo en pipeline interno | Revisar formato de columnas requeridas |

---
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
  - `file` (UploadFile, requerido): Excel con columnas mínimas `Número Reclamo`, `Numero Línea`, `Nombre Cliente`, `Fecha Inicio Problema Reclamo`, `Fecha Cierre Problema Reclamo`, `Horas Netas Problema Reclamo` (se normalizan; GEO opcional).
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
  - Los mapas PNG embebidos se escalan automáticamente para no superar media hoja A4 dentro del documento.
- **Dependencias:** utiliza `modules.informes_repetitividad`, el helper `core.utils.timefmt` para normalizar Horas Netas, plantillas de `Templates/` y, si está configurado, `SOFFICE_BIN` o el servicio `office_service` para la conversión a PDF.
