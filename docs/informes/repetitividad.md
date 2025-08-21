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

## Paths de salida
- Archivos generados en `/app/data/reports/` dentro del contenedor del bot.

## Variables de entorno
- `REP_TEMPLATE_PATH=/app/templates/repetitividad.docx` ruta de la plantilla.
- `REPORTS_DIR=/app/data/reports` destino de los informes.
- `UPLOADS_DIR=/app/data/uploads` ubicación temporal de archivos subidos.
- `SOFFICE_BIN=/usr/bin/soffice` para habilitar la conversión a PDF (opcional).
- `MAPS_ENABLED=false` habilita mapas cuando es `true`.
- `MAPS_LIGHTWEIGHT=true` usa Matplotlib sin stack geoespacial.
