# Nombre de archivo: repetitividad.md
# Ubicación de archivo: docs/informes/repetitividad.md
# Descripción: Documentación del informe de Repetitividad

## Insumos requeridos
- Excel "Casos" en formato `.xlsx` con encabezados en español.
- Columnas mínimas (se renombran automáticamente): `Número Reclamo`, `Numero Línea`, `Nombre Cliente`, `Fecha Inicio Problema Reclamo`, `Fecha Cierre Problema Reclamo`, `Horas Netas Problema Reclamo` (opcional GEO: `Latitud Reclamo`, `Longitud Reclamo`).
- El parser tolera acentos/mayúsculas y coma decimal; la columna Horas Netas se convierte a minutos (`HORAS_NETAS_MIN`) aceptando formatos `HH:MM[:SS]`, enteros o decimales.
- Los datos del cliente **BANCO MACRO SA** nunca se filtran automáticamente.

## Cálculo
- Se normalizan las columnas (incluidas fechas y GEO) y se asigna `PERIODO = YYYY-MM`.
- Las Horas Netas se guardan como minutos enteros (`HORAS_NETAS_MIN`) y al exportar se formatean como `HH:MM` mediante `core.utils.timefmt.minutes_to_hhmm`.
- En el flujo Web, el período `mes/año` se usa como título/etiqueta (no se filtra por mes), el análisis es global sobre el dataset cargado.
- Se agrupan casos por `SERVICIO` y se consideran repetitivos aquellos con **2 o más** casos.
- El conteo de servicios repetitivos se realiza con operaciones vectorizadas (`groupby().size()`), lo que mejora el rendimiento.
- Se genera una tabla con servicio, cantidad y detalles/IDs; cada fila incluye Horas Netas en formato `HH:MM`.

## Uso por Telegram
1. Enviar comando `/repetitividad` o usar el botón correspondiente.
2. Subir el Excel.
3. Indicar el período `mm/aaaa`.
4. El bot devuelve el `.docx`, adjunta el `.pdf` si está disponible y reenvía cada mapa `.png` generado.

## Integración con otros canales
- Tanto la UI web como (a futuro) el bot de Telegram llaman a la misma función de servicio: `modules.informes_repetitividad.service.generar_informe_desde_excel`.
- La API web (`/api/flows/repetitividad`) devuelve rutas absolutas de descarga bajo `/reports/*` incluyendo los mapas `.png` generados por servicio y la lista completa en `assets`.
- El histórico se lista con `/reports-history`.

## Cobertura de pruebas automatizadas
- `tests/test_docx_utils.py`, `tests/test_static_map.py`, `tests/test_repetitividad_docx_render.py`: casos actualizados para nuevas funcionalidades.
- `tests/test_timefmt.py`: valida conversión minutos ↔ `HH:MM` y entradas mixtas (decimales, `timedelta`, objetos con `total_seconds`).
- `tests/test_ingest_parser.py`: asegura que el parser normalice Horas Netas a minutos y limpie GEO fuera de rango.

### Pendientes (# TODO)
- Crear pruebas funcionales del flujo de Telegram con `aiogram` (al menos simulando estados felices y errores).
- Añadir cobertura adicional para escenarios donde `/reports/repetitividad` deba limitar tamaño de archivos y autenticar requests (incluyendo verificación de headers `X-PDF-*`).
- Evaluar pruebas integrales que verifiquen la generación y descarga de archivos desde la UI (end-to-end en Docker compose).

## Paths de salida
- Archivos generados en `/app/web_app/data/reports/` en el contenedor `web` (o en `REPORTS_DIR` configurado). La descarga se sirve en `/reports/*`.

## Variables de entorno
- `REP_TEMPLATE_PATH=/app/Templates/Plantilla_Informe_Repetitividad.docx` ruta de la plantilla oficial (copiada desde `Templates/`).
- `REPORTS_DIR=/app/data/reports` destino de los informes.
- `UPLOADS_DIR=/app/data/uploads` ubicación temporal de archivos subidos.
- `SOFFICE_BIN=/usr/bin/soffice` para habilitar la conversión a PDF (opcional).
- `MAPS_ENABLED=true` activa la generación de mapas PNG.
- Dependencias geoespaciales instaladas en los contenedores: `matplotlib==3.9.2`, `contextily==1.5.2`, `pyproj==3.6.1` + paquetes nativos (`gdal-bin`, `libgdal-dev`, `libproj-dev`, `libgeos-dev`, `build-essential`).

## Referencias legacy y plan de migración

### Componentes en Sandy
- `sandybot/handlers/repetitividad.py`: orquestación completa (validaciones, pandas, armado de DOCX, render de mapas y post-procesado COM en Windows).
- `sandybot/geo_utils.py`: extracción de coordenadas y generación de mapas (`geopandas`, `contextily`, `matplotlib`).
- `sandybot/config.py`: define `PLANTILLA_PATH` y dependencias de rutas/historial.
- `sandybot/handlers/document.py`: enruta el archivo recibido según el modo (`repetitividad`).
- Plantillas en `Sandy bot/templates/` (`plantilla_informe.docx`).

### Riesgos detectados
- Dependencia en librerías sólo disponibles en Windows (COM con `pythoncom`/`win32com`).
- Generación de mapas requiere stack geoespacial pesado; en Sandy se ejecutaba localmente, en LAS-FOCAS debe encapsularse o simplificarse.
- Flujo monolítico (Telegram) acoplado a bot; necesitamos reutilizarlo desde web/API.

### Plan de migración
1. **Estandarizar plantillas**
   - Usar `Templates/Plantilla_Informe_Repetitividad.docx` como fuente única.
   - Añadir pruebas de integridad (por hash o fecha) para detectar cambios no deseados.
2. **Refactor de procesamiento de datos**
   - Crear módulo `modules/informes_repetitividad/processor.py` en LAS-FOCAS reutilizando la lógica de pandas (normalización, filtrado, agrupaciones) desacoplada del canal Telegram.
   - Añadir tests unitarios basados en fixtures (similar a los existentes en `tests/test_repetitividad_processor.py`).
3. **Generación de documento**
   - Implementar componente que consuma la plantilla via `python-docx` o delegue en `office_service` para conversiones y formateos.
   - Reemplazar la porción COM por macros/estilos predefinidos o post-proceso con LibreOffice headless.
4. **Mapas**
   - Consolidado: `core.maps.static_map` genera PNG con `matplotlib` (Agg) y tiles de `contextily` cuando hay conectividad, ajustándolos para no superar media hoja A4 al incrustarse en el DOCX.
   - El worker `repetitividad_worker` mantiene `geopandas` para tareas enfocadas; API/web/bot consumen directamente los PNG almacenados en `REPORTS_DIR`.
5. **Integraciones**
   - Exponer servicio REST (`POST /reports/repetitividad`) reutilizable por bot y web.
   - Orquestar envío de archivos desde web/Telegram usando `REPORTS_DIR`.
6. **Documentación y CI**
   - Actualizar esta guía al finalizar y registrar las decisiones.
   - Añadir pruebas end-to-end (web o CLI) que generen el reporte y validen el DOCX.

### Pendientes
- Definir dataset de prueba realista (anonimizado) para validar la tabla generada.
- Diseñar interfaz del microservicio/módulo que devuelva enlaces a reportes bajo `Templates/`.

### Fixtures de integración
- `tests/fixtures/repetitividad/casos_repetitividad_base.xlsx`: dataset controlado para validar el cálculo principal (dos servicios repetitivos y uno único).
- `tests/fixtures/repetitividad/casos_repetitividad_geo.xlsx`: incluye descripciones con coordenadas (prefijo `GEO:`) para futuras pruebas del worker geoespacial.

### Jobs para `repetitividad_worker`
- El worker dedicado (`modules/informes_repetitividad/worker.py`) se desplegará con la imagen `deploy/docker/repetitividad_worker.Dockerfile` (perfil `reports-worker`).
- Payload inicial previsto (cola a definir):
  ```json
  {
    "type": "repetitividad.maps",
    "docx": "/app/data/reports/repetitividad_202407.docx",
    "detalles": [
      {"servicio": "Fibra 100", "coordenadas": [[-34.60, -58.38], [-34.61, -58.37]]}
    ]
  }
  ```
- Objetivos de la primera iteración del worker:
  1. Consumir este payload desde una cola Redis/Celery.
  2. Generar PNGs y adjuntarlos al reporte (o guardarlos junto al DOCX).
  3. Registrar métricas de uso y tiempos de render.
