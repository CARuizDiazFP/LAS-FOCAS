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

## Infraestructura
### POST `/sync/camaras`

Dispara manualmente la sincronización de cámaras desde Google Sheets hacia la tabla `app.camaras`.

- **Autenticación:** pendiente (usar sólo en entornos controlados hasta integrar API key / JWT).
- **Body (JSON opcional):**

  | Campo            | Tipo   | Descripción |
  |------------------|--------|-------------|
  | `sheet_id`       | string | ID del Google Sheet (override de `INFRA_SHEET_ID`). |
  | `worksheet_name` | string | Nombre de la hoja; default `Camaras`. |

  Si no se envía body se usan los valores configurados por entorno (`INFRA_SHEET_ID`, `INFRA_SHEET_NAME`).

- **Respuesta 200:**

  ```json
  {
    "status": "ok",
    "processed": 120,
    "updated": 17,
    "created": 5
  }
  ```

- **Códigos de error:**
  - `400`: configuración incompleta o columnas requeridas ausentes.
  - `500`: falló la lectura del Sheet o el upsert (consultar logs `action=infra_sync`).

- **Dependencias:** requiere un archivo `credentials.json` en la carpeta `Keys/` (o la variable `GOOGLE_CREDENTIALS_JSON` con el Service Account), además de un Sheet "Camaras" con columnas `Fontine_ID`, `Nombre`, `Lat`, `Lon`, `Estado`.
- **Notas:** los estados se normalizan a `LIBRE|OCUPADA|BANEADA`; las coordenadas aceptan `.` o `,` como separador decimal. Las filas sin `Fontine_ID` se omiten del conteo `processed` y se registran como `skipped` en logs.
- **Referencias:** ver pasos operativos en `docs/Guia_de_Uso.md` (sección "Sincronización de cámaras").

### GET `/api/infra/camaras`

Busca cámaras en la base de datos con filtrado por texto y/o estado.

- **Autenticación:** requiere sesión activa (panel web) o API key (pendiente).
- **Parámetros (query string):**

  | Campo   | Tipo   | Requerido | Default | Descripción |
  |---------|--------|-----------|---------|-------------|
  | `q`     | string | No        | -       | Texto de búsqueda (busca en nombre, dirección, fontine_id, servicio_id). |
  | `estado`| string | No        | -       | Filtrar por estado: `LIBRE`, `OCUPADA`, `BANEADA`, `DETECTADA`. |
  | `limit` | int    | No        | 100     | Máximo de resultados (tope: 500). |

- **Lógica de búsqueda:**
  1. Filtra cámaras por estado si se especifica.
  2. Busca coincidencias en `nombre`, `direccion`, `fontine_id` usando `ILIKE`.
  3. Si no encuentra resultados y `q` parece un ID de servicio, busca servicios y retorna las cámaras asociadas.
  4. Incluye lista de servicios que pasan por cada cámara (IDs extraídos de la relación servicio-empalme-cámara).

- **Respuesta 200:**

  ```json
  {
    "status": "ok",
    "total": 5,
    "camaras": [
      {
        "id": 1,
        "nombre": "Av. Corrientes 1234",
        "fontine_id": "CAM-001",
        "direccion": null,
        "estado": "OCUPADA",
        "origen_datos": "SHEET",
        "latitud": -34.6037,
        "longitud": -58.3816,
        "servicios": ["111995", "112001"]
      }
    ]
  }
  ```

- **Códigos de error:**
  - `500`: error de base de datos (consultar logs `action=search_camaras`).

- **Ejemplo (cURL):**
  ```bash
  curl "http://localhost:8001/api/infra/camaras?q=corrientes&estado=OCUPADA&limit=50"
  ```

### POST `/api/infra/search`

Búsqueda avanzada de cámaras con filtros combinables (lógica AND). Permite buscar cámaras que cumplan **todos** los criterios especificados simultáneamente.

- **Autenticación:** requiere sesión activa (panel web) o API key (pendiente).
- **Content-Type:** `application/json`
- **Body (JSON):**

  ```json
  {
    "filters": [
      {"field": "service_id", "operator": "eq", "value": "111995"},
      {"field": "address", "operator": "contains", "value": "rivadavia"}
    ],
    "limit": 100,
    "offset": 0
  }
  ```

- **Campos de filtro disponibles:**

  | Campo       | Descripción |
  |-------------|-------------|
  | `service_id` | Busca cámaras por donde pasa un servicio específico. |
  | `address`    | Busca por nombre o dirección de la cámara. |
  | `status`     | Estado de la cámara: `LIBRE`, `OCUPADA`, `BANEADA`, `DETECTADA`. |
  | `cable`      | Busca cámaras asociadas a un cable por nombre. |
  | `origen`     | Origen de datos: `MANUAL`, `TRACKING`, `SHEET`. |

- **Operadores disponibles:**

  | Operador      | Descripción | Ejemplo |
  |---------------|-------------|---------|
  | `eq`          | Coincidencia exacta (case-insensitive) | `{"field": "status", "operator": "eq", "value": "LIBRE"}` |
  | `contains`    | El texto contiene el valor (default) | `{"field": "address", "operator": "contains", "value": "corrientes"}` |
  | `starts_with` | Empieza con el valor | `{"field": "address", "operator": "starts_with", "value": "av."}` |
  | `ends_with`   | Termina con el valor | `{"field": "address", "operator": "ends_with", "value": "1234"}` |
  | `in`          | Valor está en lista (usar array en `value`) | `{"field": "status", "operator": "in", "value": ["LIBRE", "DETECTADA"]}` |

- **Lógica de búsqueda:**
  - Los filtros se combinan con **AND** (intersección): solo se devuelven cámaras que cumplan **todos** los filtros.
  - Para filtrar por servicio, se busca en las relaciones servicio → empalme → cámara.
  - Para filtrar por cable, se busca en la relación cámara → cables.
  - Soporta paginación con `limit` (max 500) y `offset`.

- **Respuesta 200:**

  ```json
  {
    "status": "ok",
    "total": 3,
    "limit": 100,
    "offset": 0,
    "filters_applied": 2,
    "camaras": [
      {
        "id": 1,
        "nombre": "Av. Rivadavia 1500",
        "fontine_id": "CAM-001",
        "direccion": null,
        "estado": "OCUPADA",
        "origen_datos": "TRACKING",
        "latitud": -34.6037,
        "longitud": -58.3816,
        "servicios": ["111995"]
      }
    ]
  }
  ```

- **Códigos de error:**
  - `422`: filtros inválidos o más de 10 filtros.
  - `500`: error de base de datos (consultar logs `action=advanced_search`).

- **Ejemplos de uso:**

  ```bash
  # Buscar cámaras de un servicio específico
  curl -X POST http://localhost:8001/api/infra/search \
    -H "Content-Type: application/json" \
    -d '{"filters": [{"field": "service_id", "operator": "eq", "value": "111995"}]}'

  # Buscar cámaras libres en una calle
  curl -X POST http://localhost:8001/api/infra/search \
    -H "Content-Type: application/json" \
    -d '{"filters": [
      {"field": "address", "operator": "contains", "value": "corrientes"},
      {"field": "status", "operator": "eq", "value": "LIBRE"}
    ]}'

  # Buscar cámaras con múltiples estados (detectadas o libres)
  curl -X POST http://localhost:8001/api/infra/search \
    -H "Content-Type: application/json" \
    -d '{"filters": [{"field": "status", "operator": "in", "value": ["LIBRE", "DETECTADA"]}]}'

  # Buscar con paginación
  curl -X POST http://localhost:8001/api/infra/search \
    -H "Content-Type: application/json" \
    -d '{"filters": [], "limit": 50, "offset": 100}'
  ```

### POST `/api/infra/upload_tracking`

Procesa un archivo de tracking de fibra óptica (TXT) y puebla la base de datos con servicios, cámaras y empalmes.

- **Autenticación:** pendiente (usar sólo en entornos controlados hasta integrar API key / JWT).
- **Content-Type:** `multipart/form-data`
- **Parámetros:**

  | Campo  | Tipo       | Requerido | Descripción |
  |--------|------------|-----------|-------------|
  | `file` | UploadFile | Sí        | Archivo `.txt` con el tracking de fibra óptica. |

- **Lógica de procesamiento:**
  1. Extrae el ID del servicio desde el nombre del archivo usando regex (ej: `FO 111995 C2.txt` → `111995`).
  2. Parsea el contenido buscando líneas `Empalme <ID>: <Dirección/Ubicación>`.
  3. Crea o actualiza el servicio en `app.servicios`.
  4. Para cada empalme/ubicación:
     - Busca la cámara por nombre (coincidencia exacta o normalizada case-insensitive).
     - **Si no existe:** crea una nueva cámara con `estado=DETECTADA` y `origen_datos=TRACKING`.
     - Registra el empalme y la asociación servicio-empalme.
  5. Guarda el tracking crudo en `raw_tracking_data` del servicio.

- **Enriquecimiento progresivo:** las cámaras detectadas automáticamente pueden enriquecerse posteriormente con coordenadas y estado real mediante el endpoint `/sync/camaras` o edición manual.

- **Idempotencia:** subir el mismo archivo dos veces no duplica datos; actualiza las asociaciones existentes.

- **Respuesta 200:**

  ```json
  {
    "status": "ok",
    "servicios_procesados": 1,
    "servicio_id": "111995",
    "camaras_nuevas": 3,
    "camaras_existentes": 5,
    "empalmes_registrados": 8,
    "mensaje": "Tracking del servicio 111995 procesado correctamente"
  }
  ```

- **Códigos de error:**
  - `400`: archivo sin extensión `.txt`, ID de servicio no extraíble, o sin empalmes válidos.
  - `500`: error durante el procesamiento o persistencia (consultar logs `action=upload_tracking`).

- **Ejemplo (cURL):**
  ```bash
  curl -X POST \
    -F "file=@FO 111995 C2.txt" \
    http://localhost:8001/api/infra/upload_tracking
  ```

- **Formato de archivo esperado:**
  ```
  Empalme 1: Av. Corrientes 1234
  F-001: ... 0.35 dB
  F-002: ... 0.28 dB
  Empalme 2: Calle Florida 567
  F-003: ... 0.42 dB
  ...
  ```

### Sistema de Versionado de Rutas FO (v2)

El sistema de carga de trackings evolucionó a un flujo en 2 pasos con soporte de versionado/ramificación, similar a un sistema de control de versiones (Git) para rutas de fibra óptica.

#### Conceptos clave

- **Servicio**: Identificador único de una conexión de fibra (ej: `52547`, `111995`).
- **Ruta (RutaServicio)**: Un camino específico dentro de un servicio. Un servicio puede tener múltiples rutas:
  - `PRINCIPAL`: La ruta primaria/activa.
  - `ALTERNATIVA`: Camino alternativo (disjunto, backup, etc.).
  - `BACKUP`: Ruta de respaldo histórica.
- **Empalme**: Punto de fusión en una cámara, asociado a una o más rutas.
- **Hash SHA256**: Identifica de forma única el contenido de un tracking (normalizado).

#### Flujo de carga inteligente

```
┌─────────────────┐
│  Archivo .txt   │
│  (Tracking FO)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     POST /api/infra/trackings/analyze
│    ANÁLISIS     │ ──────────────────────────────────────►
│  (Fase 1)       │
└────────┬────────┘
         │
         ▼
    ┌────┴────┐
    │ Status? │
    └────┬────┘
         │
   ┌─────┼─────┬─────────┐
   │     │     │         │
   ▼     ▼     ▼         ▼
  NEW  IDENT. CONFLICT  ERROR
   │     │     │         │
   │     │     │         └──► Mostrar error
   │     │     │
   │     │     └──► Modal con opciones:
   │     │         ├─ REPLACE (Reemplazar)
   │     │         ├─ MERGE_APPEND (Complementar)
   │     │         ├─ BRANCH (Camino disjunto)
   │     │         └─ SKIP (Ignorar)
   │     │
   │     └──► No hacer nada (ya idéntico)
   │
   └──► Crear servicio + ruta principal
         │
         ▼
┌─────────────────┐     POST /api/infra/trackings/resolve
│   RESOLUCIÓN    │ ──────────────────────────────────────►
│   (Fase 2)      │
└─────────────────┘
```

### POST `/api/infra/trackings/analyze`

Analiza un archivo de tracking sin modificar la base de datos. Detecta si es nuevo, idéntico o hay conflicto.

- **Autenticación:** requiere sesión activa.
- **Content-Type:** `multipart/form-data`
- **Parámetros:**

  | Campo    | Tipo       | Requerido | Descripción |
  |----------|------------|-----------|-------------|
  | `file`   | UploadFile | Sí        | Archivo `.txt` con el tracking. |

- **Respuestas posibles:**

  **1. NEW** - Servicio no existe:
  ```json
  {
    "status": "NEW",
    "servicio_id": "52547",
    "servicio_db_id": null,
    "nuevo_hash": "a3b8c1d2e4f5...",
    "rutas_existentes": [],
    "parsed_empalmes_count": 15,
    "message": "Servicio 52547 es nuevo. Se creará con una ruta principal."
  }
  ```

  **2. IDENTICAL** - Hash coincide con ruta existente:
  ```json
  {
    "status": "IDENTICAL",
    "servicio_id": "52547",
    "servicio_db_id": 123,
    "ruta_identica_id": 456,
    "nuevo_hash": "a3b8c1d2e4f5...",
    "rutas_existentes": [
      {
        "id": 456,
        "nombre": "Principal",
        "tipo": "PRINCIPAL",
        "hash_contenido": "a3b8c1d2e4f5...",
        "empalmes_count": 15,
        "activa": true,
        "created_at": "2026-01-09T10:30:00",
        "nombre_archivo_origen": "52547.txt"
      }
    ],
    "message": "El archivo es idéntico a la ruta existente (ID: 456). No se requiere acción."
  }
  ```

  **3. CONFLICT** - Hash difiere, requiere decisión:
  ```json
  {
    "status": "CONFLICT",
    "servicio_id": "52547",
    "servicio_db_id": 123,
    "nuevo_hash": "x9y8z7w6v5u4...",
    "rutas_existentes": [
      {
        "id": 456,
        "nombre": "Principal",
        "tipo": "PRINCIPAL",
        "hash_contenido": "a3b8c1d2e4f5...",
        "empalmes_count": 12,
        "activa": true
      }
    ],
    "parsed_empalmes_count": 15,
    "message": "El servicio 52547 ya existe con 1 ruta(s). Seleccioná una acción."
  }
  ```

  **4. ERROR** - Problema durante el análisis:
  ```json
  {
    "status": "ERROR",
    "servicio_id": null,
    "error": "No se pudo extraer ID de servicio desde: archivo.txt",
    "message": "El nombre del archivo debe contener un ID de servicio (ej: 'FO 111995 C2.txt')"
  }
  ```

### POST `/api/infra/trackings/resolve`

Ejecuta la acción seleccionada tras el análisis.

- **Autenticación:** requiere sesión activa.
- **Content-Type:** `application/json`
- **Body:**

  ```json
  {
    "action": "REPLACE",
    "content": "<contenido del archivo>",
    "filename": "52547.txt",
    "target_ruta_id": 456,
    "new_ruta_name": null,
    "new_ruta_tipo": null
  }
  ```

- **Parámetros:**

  | Campo           | Tipo   | Requerido | Descripción |
  |-----------------|--------|-----------|-------------|
  | `action`        | string | Sí        | `CREATE_NEW`, `MERGE_APPEND`, `REPLACE`, `BRANCH` |
  | `content`       | string | Sí        | Contenido del archivo de tracking |
  | `filename`      | string | Sí        | Nombre del archivo |
  | `target_ruta_id`| int    | Condicional | Requerido para `MERGE_APPEND` y `REPLACE` |
  | `new_ruta_name` | string | Condicional | Nombre de la nueva ruta (para `BRANCH`, default: "Camino 2") |
  | `new_ruta_tipo` | string | No        | `PRINCIPAL`, `ALTERNATIVA`, `BACKUP` (default: `ALTERNATIVA`) |

- **Acciones disponibles:**

  | Acción        | Descripción | Parámetros adicionales |
  |---------------|-------------|------------------------|
  | `CREATE_NEW`  | Crea servicio nuevo con ruta "Principal" | Ninguno |
  | `REPLACE`     | Reemplaza empalmes de una ruta existente | `target_ruta_id` |
  | `MERGE_APPEND`| Agrega empalmes sin eliminar existentes | `target_ruta_id` |
  | `BRANCH`      | Crea nueva ruta bajo el mismo servicio | `new_ruta_name`, `new_ruta_tipo` |

- **Respuesta 200 (éxito):**

  ```json
  {
    "success": true,
    "action": "REPLACE",
    "servicio_id": "52547",
    "servicio_db_id": 123,
    "ruta_id": 456,
    "ruta_nombre": "Principal",
    "camaras_nuevas": 3,
    "camaras_existentes": 12,
    "empalmes_creados": 3,
    "empalmes_asociados": 15,
    "message": "Ruta 'Principal' actualizada con 15 empalmes"
  }
  ```

- **Respuesta (error de negocio, no HTTP error):**

  ```json
  {
    "success": false,
    "action": "MERGE_APPEND",
    "servicio_id": "52547",
    "error": "target_ruta_id es requerido para MERGE_APPEND",
    "message": null
  }
  ```

### DELETE `/api/infra/servicios/{servicio_id}/empalmes`

Elimina todas las asociaciones de empalmes de un servicio (limpia el servicio sin borrarlo).

- **Autenticación:** requiere sesión activa.
- **Parámetros de ruta:**

  | Campo        | Tipo   | Descripción |
  |--------------|--------|-------------|
  | `servicio_id`| string | ID del servicio (ej: `52547`) |

- **Respuesta 200:**

  ```json
  {
    "status": "ok",
    "servicio_id": "52547",
    "empalmes_removed": 15,
    "message": "Eliminados 15 empalmes del servicio 52547"
  }
  ```

- **Códigos de error:**
  - `404`: Servicio no encontrado.
  - `500`: Error durante la eliminación.

- **Ejemplo (cURL):**
  ```bash
  curl -X DELETE \
    -H "X-CSRF-Token: $TOKEN" \
    "http://localhost:8080/api/infra/servicios/52547/empalmes"
  ```

### POST `/api/infra/smart-search`

Búsqueda de cámaras por texto libre con múltiples términos (lógica AND).

- **Autenticación:** requiere sesión activa.
- **Content-Type:** `application/json`
- **Body:**

  ```json
  {
    "terms": ["52547", "corrientes"],
    "limit": 100,
    "offset": 0
  }
  ```

- **Lógica:**
  - Cada término se busca en: `nombre`, `direccion`, `fontine_id`, `servicios`, `cables`, `estado`, `origen`
  - Términos se combinan con **AND** (intersección)
  - Máximo 20 términos

- **Respuesta 200:**

  ```json
  {
    "status": "ok",
    "total": 3,
    "limit": 100,
    "offset": 0,
    "terms_applied": 2,
    "camaras": [...]
  }
  ```

- **Ejemplo (cURL):**
  ```bash
  curl -X POST http://localhost:8080/api/infra/smart-search \
    -H "Content-Type: application/json" \
    -H "X-CSRF-Token: $TOKEN" \
    -d '{"terms": ["111995", "OCUPADA"]}'
  ```

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

## Herramientas del panel web

### POST `/api/tools/compare-vlans`

Compara las VLANs permitidas de dos configuraciones Cisco IOS.

- **Autenticación:** requiere sesión válida en el panel web y token CSRF (omitible en modo `TESTING=true`).
- **Body (JSON):**
  | Campo | Tipo | Requerido | Descripción |
  |-------|------|-----------|-------------|
  | `text_a` | string | Sí | Configuración completa de la primera interfaz. Se buscan las líneas `switchport trunk allowed vlan` (con o sin `add`). |
  | `text_b` | string | Sí | Configuración de la segunda interfaz. |
  | `csrf_token` | string | Condicional | Token de sesión utilizado por el panel (campo oculto en `panel.html`). |

- **Procesamiento:**
  - Se parsean las líneas relevantes usando `web.tools.vlan_comparator.parse_cisco_vlans`.
  - Se admiten rangos (`1-6,200-210`) y listas separadas por comas; los valores fuera de `1-4094` se descartan.
  - Las VLANs se consolidan en conjuntos únicos antes de comparar.

- **Respuesta 200:**

  ```json
  {
    "vlans_a": [1, 2, 3, 10],
    "vlans_b": [2, 3, 4, 30],
    "only_a": [1, 10],
    "only_b": [4, 30],
    "common": [2, 3],
    "total_a": 4,
    "total_b": 4
  }
  ```

- **Errores frecuentes:**
  - `401` → sesión expirada o inexistente.
  - `403` → token CSRF inválido.
  - `400` → no se detectaron VLANs en una de las configuraciones.

- **UI relacionada:** sección "Comparador de VLANs" en `web/templates/panel.html`, estilos en `web/static/styles.css` y lógica en `web/static/panel.js`.


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
---

## Protocolo de Protección (Baneo de Cámaras)

Endpoints para gestionar el bloqueo de acceso físico a cámaras de fibra óptica de respaldo.

### POST `/api/infra/ban/create`

Crea un incidente de baneo y marca las cámaras afectadas como `BANEADA`.

- **Body (JSON):**

  | Campo                | Tipo   | Requerido | Descripción |
  |----------------------|--------|-----------|-------------|
  | `ticket_asociado`    | string | No        | ID del ticket de soporte (ej: "INC0012345"). |
  | `servicio_afectado_id` | string | Sí      | ID del servicio que sufrió el corte. |
  | `servicio_protegido_id`| string | Sí      | ID del servicio a proteger (banear sus cámaras). |
  | `ruta_protegida_id`  | int    | No        | ID de ruta específica a banear (opcional). |
  | `usuario_ejecutor`   | string | No        | Usuario que ejecuta el baneo. |
  | `motivo`             | string | No        | Motivo del baneo. |

- **Respuesta 200:**

  ```json
  {
    "success": true,
    "incidente_id": 1,
    "camaras_baneadas": 45,
    "camaras_ya_baneadas": 5,
    "message": "Baneo creado. 45 cámaras baneadas, 5 ya estaban baneadas.",
    "camaras_afectadas": [
      {"id": 123, "nombre": "CAM-001", "estado_anterior": "LIBRE", "estado_nuevo": "BANEADA", "accion": "baneada"}
    ]
  }
  ```

- **Notas:**
  - Soporta **redundancia cruzada**: el servicio afectado puede ser diferente al protegido.
  - El baneo afecta a la entidad Cámara completa, no solo la asociación.

### POST `/api/infra/ban/lift`

Levanta un baneo y restaura el estado de las cámaras.

- **Body (JSON):**

  | Campo            | Tipo   | Requerido | Descripción |
  |------------------|--------|-----------|-------------|
  | `incidente_id`   | int    | Sí        | ID del incidente a cerrar. |
  | `usuario_ejecutor` | string | No      | Usuario que levanta el baneo. |
  | `motivo_cierre`  | string | No        | Motivo del cierre. |

- **Lógica de restauración:**
  - Si la cámara tiene un ingreso activo → `OCUPADA`
  - Si la cámara tiene otro baneo activo → `BANEADA` (sin cambio)
  - En otro caso → `LIBRE`

- **Respuesta 200:**

  ```json
  {
    "success": true,
    "incidente_id": 1,
    "camaras_restauradas": 40,
    "camaras_mantenidas_baneadas": 5,
    "message": "Baneo levantado. 40 cámaras restauradas, 5 mantenidas baneadas por otros incidentes."
  }
  ```

### GET `/api/infra/ban/active`

Obtiene todos los incidentes de baneo activos.

- **Respuesta 200:**

  ```json
  {
    "status": "ok",
    "total": 2,
    "incidentes": [
      {
        "id": 1,
        "ticket_asociado": "INC0012345",
        "servicio_afectado_id": "52547",
        "servicio_protegido_id": "52548",
        "motivo": "Corte de fibra principal",
        "fecha_inicio": "2026-01-12T10:00:00+00:00",
        "activo": true,
        "duracion_horas": 2.5
      }
    ]
  }
  ```

### GET `/api/infra/ban/{incidente_id}`

Obtiene el detalle de un incidente específico con las cámaras afectadas.

- **Respuesta 200:** Incluye datos del incidente y lista de cámaras afectadas.

---

## Exportación de Cámaras

### GET `/api/infra/export/cameras`

Exporta un listado de cámaras a CSV o XLSX.

- **Parámetros (query string):**

  | Campo          | Tipo   | Requerido | Default | Descripción |
  |----------------|--------|-----------|---------|-------------|
  | `filter_status`| string | No        | ALL     | Filtrar por estado: `ALL`, `LIBRE`, `OCUPADA`, `BANEADA`, `DETECTADA`. |
  | `servicio_id`  | string | No        | -       | Filtrar cámaras de un servicio específico. |
  | `format`       | string | No        | csv     | Formato de salida: `csv` o `xlsx`. |

- **Columnas exportadas:**
  - `ID`: ID de la cámara.
  - `Nombre`: Nombre de la cámara.
  - `Fontine_ID`: ID de referencia externa.
  - `Dirección`: Dirección de la cámara.
  - `Estado`: Estado actual (`LIBRE`, `OCUPADA`, `BANEADA`, `DETECTADA`).
  - `Servicios_Cat6`: IDs de servicios asociados (separados por coma).
  - `Ticket_Baneo`: ID del ticket de baneo (si aplica).
  - `Latitud`, `Longitud`: Coordenadas.
  - `Origen_Datos`: Origen de los datos (`MANUAL`, `TRACKING`, `SHEET`).

- **Respuesta:**
  - `200 OK` con archivo CSV o XLSX para descarga.
  - Content-Disposition: `attachment; filename="camaras_20260112_143000.csv"`

- **Notas:**
  - Si `pandas` u `openpyxl` no están disponibles, se degrada a CSV con header `X-Export-Warning`.
  - El CSV usa BOM UTF-8 para compatibilidad con Excel.