# Nombre de archivo: sla.md
# Ubicación de archivo: docs/informes/sla.md
# Descripción: Documentación del informe de SLA - Generación desde Excel (modo legacy) o desde DB

## Resumen

El informe de SLA analiza el cumplimiento de tiempos de resolución de tickets/reclamos comparando el **TTR** (Time To Resolve) real contra el **SLA objetivo**. Replica el comportamiento del sistema legacy Sandy, soportando:

1. **Modo Excel (legacy)**: Dos archivos separados ("Servicios Fuera de SLA" + "Reclamos SLA").
2. **Modo DB**: Consulta directa a la tabla `app.reclamos` con normalización automática.

**Estado actual (2026-01-13)**: ✅ Flujo web completamente funcional. Corrección crítica aplicada para usar la columna correcta de horas (columna U "Horas Netas Reclamo").

## Columnas esperadas y mapeos

### Archivo "Reclamos SLA"

Las columnas se mapean internamente con sinónimos para tolerar variaciones:

| Campo interno | Columna Excel esperada | Columna | Descripción |
|---------------|------------------------|---------|-------------|
| `id_reclamo` | "Número reclamo" | A | ID único del ticket |
| `id_servicio` | "Número Línea" o "Número Primer Servicio" | D / C | ID del servicio afectado |
| `cliente` | "Razón Social" o "Cliente" | - | Nombre del cliente |
| `horas` | **"Horas Netas Reclamo"** | **U** | ⚠️ **Columna crítica**: tiempo neto de resolución |

> **IMPORTANTE**: La columna "Horas Netas Reclamo" (U) es la única fuente válida para el cálculo de horas. NO se usa "Horas Netas Cierre Problema Reclamo" (columna P).

### Archivo "Servicios Fuera de SLA"

- `ID`
- `CLIENTE`
- `SERVICIO`
- `FECHA_APERTURA`
- `FECHA_CIERRE`
- `SLA_OBJETIVO_HORAS` (opcional)

Mapeos admitidos: `TicketID`→`ID`, `Apertura`→`FECHA_APERTURA`, `Cierre`→`FECHA_CIERRE`, `SLA`→`SLA_OBJETIVO_HORAS`.

## Cálculo
- Se normalizan las columnas y se calcula `TTR_h = (FECHA_CIERRE - FECHA_APERTURA) / 3600`.
- Se filtra por `FECHA_CIERRE` dentro del período indicado (mes/año).
- Si falta `SLA_OBJETIVO_HORAS`, se usa `SLA_POR_SERVICIO` con fallback **24 h**.
- Se excluyen casos sin fecha de cierre y se informa la cantidad excluida.
- Cumplido cuando `TTR_h <= SLA_OBJETIVO_HORAS`.

## Parámetros del período
- Formato `mm/aaaa`.
- Mes 1–12, año ≥ 2000.

## Uso por Web Panel

**Endpoint**: `POST /api/reports/sla`

**URL**: `http://localhost:8080/sla`

### Pasos:
1. Acceder a la vista `/sla` (requiere login).
2. Arrastrar y soltar **dos archivos Excel obligatorios**:
   - "Servicios Fuera de SLA.xlsx" (o similar)
   - "Reclamos SLA.xlsx" (o similar)
3. Indicar el período: mes (1-12) y año (≥2000).
4. Opcional: activar "Generar PDF" si LibreOffice está disponible.
5. Opcional: activar "Usar base de datos" para ignorar archivos y consultar desde `app.reclamos`.
6. Click en "Generar informe".
7. El sistema devuelve JSON con rutas de descarga del `.docx` y opcionalmente `.pdf`.

### Validaciones:
- Se requieren **exactamente 2 archivos** si no se usa DB.
- Ambos archivos deben tener extensión `.xlsx`.
- El sistema identifica automáticamente cuál es "Servicios" y cuál es "Reclamos" por las columnas.
- Errores claros se muestran en la UI (ej: "Plantilla SLA no encontrada", "Debés adjuntar dos archivos").

### Respuesta exitosa:
```json
{
  "ok": true,
  "docx": "/api/reports/download/sla/202510/InformeSLA_202510_abc123.docx",
  "pdf": "/api/reports/download/sla/202510/InformeSLA_202510_abc123.pdf"
}
```

## Uso por Telegram
1. Enviar comando `/sla` o usar el botón correspondiente.
2. Subir el Excel `.xlsx`.
3. Indicar el período `mm/aaaa`.
4. El bot devuelve un `.docx` y opcionalmente `.pdf`.

## Límites y notas
- Se muestran hasta 2000 filas en el detalle.
- Horas calendario (horario laboral pendiente).

## Paths de salida
- Archivos en `/app/data/reports/` dentro del contenedor.

## Variables de entorno

**Configuradas en `deploy/compose.yml` para el servicio `web`:**

- `TEMPLATES_DIR=/app/Templates` — ruta base de plantillas dentro del contenedor.
- `SLA_TEMPLATE_PATH=${TEMPLATES_DIR}/Template_Informe_SLA.docx` — ruta de la plantilla oficial (se resuelve automáticamente desde `TEMPLATES_DIR`).
- `REPORTS_DIR=/app/web_app/data/reports` — destino de los informes generados.
- `UPLOADS_DIR=/app/web_app/data/uploads` — ubicación temporal de archivos subidos.
- `SOFFICE_BIN=/usr/bin/soffice` — para habilitar conversión a PDF (opcional, requiere LibreOffice en el contenedor).

**Volúmenes montados:**
```yaml
volumes:
  - ../Templates:/app/Templates:ro  # Plantillas en modo read-only
  - reports_data:/app/web_app/data/reports
  - uploads_data:/app/web_app/data/uploads
```

## Correcciones aplicadas (2025-11-11)

### Problema 1: Logs vacíos
**Causa**: La configuración de logging no forzaba escritura a archivo dentro del contenedor.

**Solución**: Se centralizó el sistema de logging en `core/logging.py` para usar el directorio `Logs/` del proyecto, con `enable_file=True` forzado y variable de entorno `LOGS_DIR` para control externo.

### Problema 2: Solo 1 de 2 archivos llegaba al endpoint
**Causa**: El parámetro FastAPI estaba definido como:
```python
files: Union[List[UploadFile], UploadFile, None] = File(None)
```

Esto causaba ambigüedad en el parser multipart, resultando en que solo se recibiera el primer archivo.

**Solución**: Se cambió a:
```python
files: List[UploadFile] = File(default=[])
```

Y se simplificó la normalización:
```python
archivos = [archivo for archivo in files if archivo and archivo.filename]
```

### Problema 3: Template no encontrado
**Causa**: La variable de entorno `TEMPLATES_DIR` no estaba definida en el servicio `web` del `compose.yml`, aunque el volumen estaba montado.

**Solución**: Se agregó `TEMPLATES_DIR: /app/Templates` en la sección `environment` del servicio `web`.

## Tests

### Tests unitarios del generador legacy:
```bash
pytest tests/test_sla_module.py -v
# PASSED: test_sla_config
# PASSED: test_load_servicios_excel
# PASSED: test_generate_from_excel_pair
```

### Validación dentro del contenedor:
```bash
# Verificar variable de entorno
docker exec lasfocas-web env | grep TEMPLATES_DIR
# Output: TEMPLATES_DIR=/app/Templates

# Verificar template
docker exec lasfocas-web ls -lh /app/Templates/Template_Informe_SLA.docx
# Output: -rw-r--r-- 1 1001 1001 1.8M Sep 30 14:21 /app/Templates/Template_Informe_SLA.docx

# Validar desde Python
docker exec lasfocas-web python -c "from core.sla.config import SLA_TEMPLATE_PATH; print(f'SLA_TEMPLATE_PATH={SLA_TEMPLATE_PATH}'); print(f'Existe: {SLA_TEMPLATE_PATH.exists()}')"
# Output: SLA_TEMPLATE_PATH=/app/Templates/Template_Informe_SLA.docx
#         Existe: True
```

## Próximos pasos

1. ~~**Ajustes de formato**: Revisar y ajustar detalles menores del formato del informe para coincidencia 100% con el legacy de Sandy.~~ ✅ Corregido 2026-01-13.
2. **Tests de integración**: Agregar test end-to-end para el endpoint `/api/reports/sla`.
3. **Documentación de API**: Actualizar `docs/api.md` con ejemplos de uso del endpoint SLA.
4. **Modo DB**: Validar y documentar el flujo completo usando `use_db=true` con datos reales de `app.reclamos`.

---

## Corrección crítica de columnas (2026-01-13)

### Problema detectado

El informe SLA mostraba valores de horas incorrectos. Al comparar con el Excel fuente:

| Servicio | Excel Col U (correcto) | Informe mostraba |
|----------|------------------------|------------------|
| 85015    | 28:05:57               | 43:58:59         |
| 85015    | 06:01:53               | 62:13:16         |

### Causa

La función `_columna_horas_reclamos()` en `core/sla/legacy_report.py` retornaba la columna incorrecta:

```python
# ANTES (incorrecto):
return optional.get("horas_netas_cierre")  # Columna P

# DESPUÉS (correcto):
return columns.get("horas")  # Columna U
```

### Archivos modificados

- `core/sla/legacy_report.py` - Función `_columna_horas_reclamos()` corregida
- `core/sla/parser.py` - Eliminada columna fallback incorrecta de `RECLAMOS_REQUIRED`
- `modules/informes_sla/processor.py` - Docstring actualizado
- `tests/test_sla_legacy_report.py` - Test actualizado

### Validación

```bash
# Verificar con datos reales
docker exec lasfocas-web python -c "
from core.sla.parser import RECLAMOS_REQUIRED
print('Columna horas:', RECLAMOS_REQUIRED.get('horas'))
"
# Output: ['Horas Netas Reclamo']
```

