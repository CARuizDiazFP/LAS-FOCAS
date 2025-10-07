# Nombre de archivo: repetitividad.md
# Ubicación de archivo: docs/informes/repetitividad.md
# Descripción: Documentación del informe de Repetitividad

## Insumos requeridos
- Excel "Casos" en formato `.xlsx`.
- Columnas mínimas: `CLIENTE`, `SERVICIO`, `FECHA` y opcional `ID_SERVICIO`.
- Los datos del cliente **BANCO MACRO SA** nunca se filtran automáticamente.

## Cálculo
- Se normalizan las columnas y se genera `PERIODO = YYYY-MM`.
- Se filtra por período indicado (mes/año).
- Se agrupan casos por `SERVICIO` y se consideran repetitivos aquellos con **2 o más** casos.
- El conteo de servicios repetitivos se realiza con operaciones vectorizadas (`groupby().size()`), lo que mejora el rendimiento.
- Se genera una tabla con servicio, cantidad y detalles/IDs.

## Uso por Telegram
1. Enviar comando `/repetitividad` o usar el botón correspondiente.
2. Subir el Excel.
3. Indicar el período `mm/aaaa`.
4. El bot devuelve un archivo `.docx` y opcionalmente `.pdf`.

## Integración con otros canales
- Tanto el bot de Telegram como la UI web delegan la invocación HTTP y el almacenamiento de resultados en `modules.informes_repetitividad.service.generate_report`.
- El servicio centraliza la publicación hacia `POST /reports/repetitividad`, maneja respuestas ZIP/DOCX y normaliza rutas de salida en disco.
- Para reutilizarlo desde nuevos flujos basta con pasar la ruta del archivo cargado, el período y el directorio de salida deseado.

## Cobertura de pruebas automatizadas
- `tests/test_repetitividad_processor.py`: cubre normalización básica y cálculo de repetitividad para casos repetidos vs. preservación del cliente banquero. Falta validar errores por columnas ausentes (`normalize`) y escenarios con filas nulas.
- `tests/test_report_builder.py`: verifica que `export_docx` genere un documento válido con título dinámico. No comprueba estilos, totales ni resaltado de casos ≥4.
- `tests/test_reports_repetitividad_api.py`: asegura respuestas DOCX y ZIP (mockeando LibreOffice), valida headers `X-PDF-Requested` / `X-PDF-Generated` e incluye casos negativos (extensión inválida, error en `processor.load_excel`).
- `tests/test_informes_repetitividad_service.py`: prueba el helper asíncrono (`generate_report`) para respuestas DOCX/ZIP, errores HTTP, ausencia de `Content-Disposition` y ZIP sin PDF.
- `tests/test_web_repetitividad_flow.py`: valida el flujo completo desde la UI web (CSRF correcto, respuesta exitosa y propagación de errores HTTP del servicio externo).
- `Legacy/Sandy/tests/test_clasificar_flujo.py` (proyecto Sandy) servía de referencia para garantizar que las entradas de chat disparen el handler de repetitividad. También existen pruebas de base de datos en `Legacy/Sandy/tests/test_database.py` que evitan duplicados de servicios y reclamos. Sirven como guía para planificar tests de orquestación en el bot/UI y reglas de deduplicación en la nueva versión.

### Pendientes (# TODO)
- Crear pruebas funcionales del flujo de Telegram con `aiogram` (al menos simulando estados felices y errores).
- Añadir cobertura adicional para escenarios donde `/reports/repetitividad` deba limitar tamaño de archivos y autenticar requests (incluyendo verificación de headers `X-PDF-*`).
- Evaluar pruebas integrales que verifiquen la generación y descarga de archivos desde la UI (end-to-end en Docker compose).

## Paths de salida
- Archivos generados en `/app/data/reports/` dentro del contenedor del bot.

## Variables de entorno
- `REP_TEMPLATE_PATH=/app/Templates/Plantilla_Informe_Repetitividad.docx` ruta de la plantilla oficial (copiada desde `Templates/`).
- `REPORTS_DIR=/app/data/reports` destino de los informes.
- `UPLOADS_DIR=/app/data/uploads` ubicación temporal de archivos subidos.
- `SOFFICE_BIN=/usr/bin/soffice` para habilitar la conversión a PDF (opcional).
- `MAPS_ENABLED=false` habilita mapas cuando es `true`.
- `MAPS_LIGHTWEIGHT=true` usa Matplotlib sin stack geoespacial.

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
   - Evaluar si se mantiene `geopandas/contextily`; de ser necesario, encapsularlo en un worker Docker separado.
   - Alternativa lightweight: `folium` o servicios estáticos si el overhead geoespacial es muy alto.
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
