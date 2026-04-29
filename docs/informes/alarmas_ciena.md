# Nombre de archivo: alarmas_ciena.md
# Ubicación de archivo: docs/informes/alarmas_ciena.md
# Descripción: Documentación del módulo de procesamiento de alarmas Ciena

# Alarmas Ciena

## Descripción

El módulo **Alarmas Ciena** permite procesar archivos CSV de alarmas exportados desde gestores de red Ciena, convirtiéndolos automáticamente a archivos Excel (.xlsx) con formato limpio y columnas correctamente separadas.

Soporta dos tipos de exportación de alarmas Ciena:
- **SiteManager**: formato con campos entrecomillados y características específicas
- **MCP (Management Control Point)**: formato CSV estándar con soporte para campos multilínea

## Características principales

✅ **Detección automática de formato**: El sistema identifica automáticamente si el CSV es de SiteManager o MCP según su estructura de encabezado.

✅ **Procesamiento robusto**:
- Limpieza de espacios padding
- Conversión de placeholders (guiones "-") a valores vacíos
- Soporte para campos multilínea (descripciones largas)
- Preservación de caracteres especiales y formatos complejos

✅ **Generación de Excel**: Exporta los datos a un archivo .xlsx limpio y fácil de manipular en Excel.

✅ **Validaciones**: Control de extensión de archivo, tamaño máximo (10MB), formato soportado y contenido vacío.

## Formatos soportados

### SiteManager CSV

**Características:**
- Todos los campos vienen entrecomillados con comillas dobles (`"`)
- Separador de campos: coma (`,`)
- Los valores pueden contener espacios padding adicionales
- Valores vacíos representados con guiones (`-`)

**Columnas típicas:**
```
"Unit","Class","Severity","Service","Description","Time Raised","Time Cleared","Duration","Acknowledge","Owner"
```

**Ejemplo de datos:**
```csv
"Unit","Class","Severity","Service","Description","Time Raised","Time Cleared","Duration"
"NE-001","Equipment","Critical","Service-A","Fiber optic link down","2024-11-15 10:23:45","2024-11-15 11:45:30","01:21:45"
"NE-002","Environment","Major","Service-B","High temperature"," 2024-11-15 12:30:00 "," - "," - "
```

**Procesamiento aplicado:**
- Elimina espacios padding al inicio y final de cada valor
- Convierte guiones aislados (`-`) en cadenas vacías
- Preserva nombres de columna con caracteres especiales (ej: `"Date, Time"`)

### MCP CSV

**Características:**
- Formato CSV estándar (campos sin comillas, excepto cuando contienen caracteres especiales)
- Separador de campos: coma (`,`)
- Soporte para descripciones multilínea (texto con saltos de línea)
- Valores vacíos aparecen como celdas sin contenido

**Columnas típicas:**
```
Severity,Description,Class,Card type,Device type,Device name,Note,Device tags,NMS alarm ID,NMS alarm instance ID
```

**Ejemplo de datos:**
```csv
Severity,Description,Class,Card type,Device type,Device name,Device tags
Critical,Port down on interface GigE 1/1,Equipment,Line Card,Switch,SW-CORE-01,priority:high;location:datacenter
Major,"Temperature threshold exceeded
Detailed description: Temperature sensor reading 85°C",Environment,Environmental,Router,RTR-EDGE-02,critical:yes
```

**Procesamiento aplicado:**
- Motor de parsing Python para soportar campos multilínea
- Preserva saltos de línea dentro de campos
- Limpieza de espacios en extremos

## Uso desde la interfaz web

### Acceso

1. Acceder al panel web de LAS-FOCAS
2. Hacer clic en el botón **"Alarmas Ciena"** en la barra de navegación superior

### Proceso

1. **Subir archivo CSV**:
   - Arrastrar y soltar el archivo .CSV en la zona indicada, o
   - Hacer clic en la zona para seleccionar el archivo desde tu equipo

2. **Procesar**:
   - Hacer clic en el botón **"Procesar"**
   - El sistema detectará automáticamente el formato
   - Se mostrará un mensaje de estado durante el procesamiento

3. **Descarga automática**:
   - El archivo Excel procesado se descargará automáticamente
   - Nombre de salida: `<nombre_original>_procesado.xlsx`
   - Se mostrará un mensaje de confirmación con estadísticas (formato detectado, filas procesadas, columnas)

### Validaciones

El sistema validará:
- ✅ Extensión del archivo debe ser `.csv`
- ✅ Tamaño máximo: 10 MB
- ✅ Archivo no vacío
- ✅ Formato reconocible (SiteManager o MCP)
- ✅ Usuario autenticado
- ✅ Token CSRF válido

En caso de error, se mostrará un mensaje descriptivo:
- "Por favor subí un archivo .CSV válido" → extensión incorrecta
- "El archivo está vacío" → archivo sin contenido
- "Formato de archivo no soportado..." → CSV no reconocido como SiteManager ni MCP
- "El archivo supera el límite de 10MB" → archivo demasiado grande

## API Endpoint

### `POST /api/tools/alarmas-ciena`

**Descripción**: Procesa un archivo CSV de alarmas Ciena y retorna un Excel.

**Autenticación**: Requerida (sesión activa)

**Parámetros**:
- `file` (UploadFile): Archivo CSV a procesar
- `csrf_token` (string): Token CSRF para validación

**Respuesta exitosa**:
- **Status**: 200 OK
- **Content-Type**: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **Headers**:
  - `Content-Disposition`: `attachment; filename="<nombre>_procesado.xlsx"`
  - `X-Formato-Detectado`: `SiteManager` o `MCP`
  - `X-Filas-Procesadas`: Número de filas procesadas
  - `X-Columnas`: Número de columnas
- **Body**: Contenido binario del archivo Excel

**Respuestas de error**:

| Status | Descripción |
|--------|-------------|
| 400 | Extensión incorrecta, archivo vacío o parámetros faltantes |
| 401 | No autenticado |
| 403 | CSRF token inválido |
| 413 | Archivo supera el límite de 10MB |
| 415 | Formato de archivo no soportado |
| 500 | Error interno durante el procesamiento |

**Ejemplo con curl**:
```bash
curl -X POST "http://localhost:8080/api/tools/alarmas-ciena" \
  -H "Cookie: session=<tu_session>" \
  -F "file=@alarmas.csv" \
  -F "csrf_token=<tu_csrf_token>" \
  --output alarmas_procesado.xlsx
```

**Logs generados**:
```
action=alarmas_ciena_start user=<username> filename=<file> size=<bytes>
action=alarmas_ciena_parsed user=<username> formato=<SiteManager|MCP> rows=<n> cols=<n>
action=alarmas_ciena_complete user=<username> formato=<format> rows=<n> size_out=<bytes> elapsed=<seconds>
```

## Módulo Python

### Ubicación

`core/parsers/alarmas_ciena.py`

### Funciones principales

#### `detectar_formato(content: bytes) -> FormatoAlarma`

Detecta el formato del CSV según su línea de encabezado.

**Parámetros**:
- `content`: Contenido binario del archivo CSV

**Retorna**: Enum `FormatoAlarma` (SITEMANAGER, MCP o DESCONOCIDO)

**Ejemplo**:
```python
from core.parsers.alarmas_ciena import detectar_formato

with open("alarmas.csv", "rb") as f:
    content = f.read()

formato = detectar_formato(content)
print(formato)  # FormatoAlarma.SITEMANAGER o FormatoAlarma.MCP
```

#### `parsear_alarmas_ciena(content: bytes) -> tuple[pd.DataFrame, FormatoAlarma]`

Función principal que detecta y parsea el CSV automáticamente.

**Parámetros**:
- `content`: Contenido binario del archivo CSV

**Retorna**: Tupla con (DataFrame procesado, formato detectado)

**Excepciones**:
- `ValueError`: Si el archivo está vacío o el formato no es soportado

**Ejemplo**:
```python
from core.parsers.alarmas_ciena import parsear_alarmas_ciena

with open("alarmas.csv", "rb") as f:
    content = f.read()

df, formato = parsear_alarmas_ciena(content)
print(f"Formato: {formato}")
print(f"Filas: {len(df)}, Columnas: {len(df.columns)}")
print(df.head())
```

#### `dataframe_to_excel(df: pd.DataFrame) -> bytes`

Convierte un DataFrame a un archivo Excel en memoria.

**Parámetros**:
- `df`: DataFrame a exportar

**Retorna**: Contenido binario del archivo Excel (.xlsx)

**Excepciones**:
- `ValueError`: Si hay error en la generación del Excel

**Ejemplo**:
```python
from core.parsers.alarmas_ciena import parsear_alarmas_ciena, dataframe_to_excel

# Parsear CSV
df, formato = parsear_alarmas_ciena(csv_content)

# Generar Excel
excel_bytes = dataframe_to_excel(df)

# Guardar a archivo
with open("output.xlsx", "wb") as f:
    f.write(excel_bytes)
```

### Funciones auxiliares

- `parsear_sitemanager(content: bytes) -> pd.DataFrame`: Parsea específicamente formato SiteManager
- `parsear_mcp(content: bytes) -> pd.DataFrame`: Parsea específicamente formato MCP

## Tests

Ubicación: `tests/test_alarmas_ciena.py`

**Cobertura de tests**:
- ✅ Detección de formato (SiteManager, MCP, inválido, vacío)
- ✅ Parsing de SiteManager (columnas, limpieza de espacios, guiones)
- ✅ Parsing de MCP (columnas, campos multilínea, valores complejos)
- ✅ Función principal `parsear_alarmas_ciena`
- ✅ Generación de Excel (estructura, preservación de datos, sin índice)
- ✅ Integración con API (formatos válidos, validaciones, errores, autenticación, CSRF)

**Ejecutar tests**:
```bash
# Todos los tests de alarmas Ciena
pytest tests/test_alarmas_ciena.py -v

# Solo tests de parsing
pytest tests/test_alarmas_ciena.py -k "parsear" -v

# Solo tests de API
pytest tests/test_alarmas_ciena.py -k "api_endpoint" -v

# Con cobertura
pytest tests/test_alarmas_ciena.py --cov=core.parsers.alarmas_ciena --cov-report=html
```

## Consideraciones técnicas

### Dependencias

El módulo requiere:
- `pandas>=2.2.2`: Procesamiento de DataFrames y lectura/escritura CSV/Excel
- `openpyxl>=3.1.2`: Motor para generación de archivos Excel (.xlsx)

Estas dependencias ya están incluidas en `requirements.txt` del proyecto.

### Límites y rendimiento

- **Tamaño máximo**: 10 MB por archivo CSV
- **Memoria**: Procesamiento en memoria (RAM), considerar esto para archivos grandes
- **Rendimiento**: Típicamente < 2 segundos para archivos de ~5000 filas

### Logs

Todos los eventos son registrados en `Logs/web.log` con el siguiente formato:

```
action=alarmas_ciena_<stage> user=<username> <parámetros...>
```

Etapas logueadas:
- `alarmas_ciena_start`: Inicio del procesamiento
- `alarmas_ciena_parsed`: Parseo exitoso
- `alarmas_ciena_complete`: Finalización con estadísticas
- `alarmas_ciena_validation_error`: Error de validación (formato no soportado)
- `alarmas_ciena_error`: Error inesperado

### Seguridad

- ✅ Requiere autenticación de usuario
- ✅ Validación de token CSRF
- ✅ Control de tamaño de archivo (previene DoS)
- ✅ Validación de extensión (solo .csv)
- ✅ Parsing seguro con pandas (previene inyección)
- ✅ Sin ejecución de código del usuario
- ✅ Logs con identificación de usuario para auditoría

## Extensibilidad

Para añadir soporte a nuevos formatos de alarmas:

1. **Actualizar detección**: Modificar `detectar_formato()` añadiendo una nueva condición
2. **Crear función de parsing**: Implementar `parsear_<nuevo_formato>(content: bytes)`
3. **Integrar en función principal**: Añadir caso en `parsear_alarmas_ciena()`
4. **Crear tests**: Añadir fixtures y tests en `test_alarmas_ciena.py`
5. **Documentar**: Actualizar este documento con el nuevo formato

**Ejemplo de extensión** (pseudo-código):
```python
class FormatoAlarma(str, Enum):
    SITEMANAGER = "SiteManager"
    MCP = "MCP"
    NUEVO_FORMATO = "NuevoFormato"  # <-- Añadir

def detectar_formato(content: bytes) -> FormatoAlarma:
    first_line = content.split(b'\n', 1)[0].decode('utf-8')
    
    # Lógica existente...
    
    # Nueva detección
    if "Columna-Especifica-Del-Nuevo" in first_line:
        return FormatoAlarma.NUEVO_FORMATO
    
    return FormatoAlarma.DESCONOCIDO

def parsear_nuevo_formato(content: bytes) -> pd.DataFrame:
    # Implementación específica
    pass

def parsear_alarmas_ciena(content: bytes) -> tuple[pd.DataFrame, FormatoAlarma]:
    formato = detectar_formato(content)
    
    if formato == FormatoAlarma.NUEVO_FORMATO:
        df = parsear_nuevo_formato(content)
    # ... casos existentes
    
    return df, formato
```

## Troubleshooting

### Problema: "Formato de archivo no soportado"

**Causas posibles**:
- El CSV no es de SiteManager ni MCP
- El archivo está corrupto o tiene un encoding diferente
- La primera línea no contiene el encabezado esperado

**Solución**:
1. Verificar que el archivo fue exportado correctamente desde SiteManager o MCP
2. Abrir el archivo en un editor de texto y verificar la primera línea
3. Asegurarse que el encoding es UTF-8

### Problema: Datos mal parseados

**Causas posibles**:
- Delimitador incorrecto (el sistema espera coma)
- Comillas mal cerradas en el CSV

**Solución**:
1. Revisar el archivo CSV manualmente
2. Re-exportar desde el gestor de red asegurándose de usar formato CSV estándar
3. Verificar los logs para detalles del error

### Problema: Descarga no inicia

**Causas posibles**:
- Bloqueador de pop-ups del navegador
- Error de red durante la transferencia

**Solución**:
1. Verificar configuración del navegador (permitir descargas)
2. Revisar consola del navegador (F12) para errores JavaScript
3. Verificar logs del servidor (`Logs/web.log`)

## Changelog

### 2025-11-17 - v1.0.0
- 🎉 Lanzamiento inicial de la funcionalidad Alarmas Ciena
- ✅ Soporte para formatos SiteManager y MCP
- ✅ Detección automática de formato
- ✅ Interfaz web integrada en el panel
- ✅ Endpoint API `/api/tools/alarmas-ciena`
- ✅ Suite completa de tests
- ✅ Documentación completa

## Referencias

- **Módulo**: `core/parsers/alarmas_ciena.py`
- **Endpoint**: `web/app/main.py` → `tool_alarmas_ciena()`
- **Frontend**: `web/templates/panel.html` → sección `view-ciena`
- **JavaScript**: `web/static/panel.js` → handler `ciena-run`
- **Tests**: `tests/test_alarmas_ciena.py`
- **PR**: `docs/PR/2025-11-17.md`

## Soporte

Para reportar problemas o sugerencias:
1. Revisar los logs en `Logs/web.log`
2. Verificar que el archivo CSV cumple con los formatos documentados
3. Consultar la sección de Troubleshooting
4. Contactar al equipo de desarrollo con los detalles del error
