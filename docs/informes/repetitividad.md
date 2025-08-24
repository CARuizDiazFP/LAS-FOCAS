# Nombre de archivo: repetitividad.md
# Ubicación de archivo: docs/informes/repetitividad.md
# Descripción: Documentación del informe de Repetitividad

## Insumos requeridos
- Excel "Casos" en formato `.xlsx`.
- Tamaño máximo permitido: 10MB.
- El nombre del archivo no debe contener rutas ni caracteres especiales.
- Columnas mínimas: `CLIENTE`, `SERVICIO`, `FECHA` y opcional `ID_SERVICIO`.
- Los datos del cliente **BANCO MACRO SA** nunca se filtran automáticamente.

## Validaciones
- `CLIENTE` y `SERVICIO` deben ser texto de hasta 100 caracteres.
- `FECHA` debe contener valores de fecha válidos.
- El período debe ingresarse en formato `mm/aaaa` y estar dentro del rango desde 2000.
- Se rechazan archivos que no puedan abrirse como Excel.

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
4. La generación se encola y el worker procesa el informe en segundo plano.
5. El bot devuelve un archivo `.docx` y opcionalmente `.pdf` al finalizar.
6. Finalmente, envía un mensaje con enlaces a los archivos generados.

## Paths de salida
- Archivos generados en `/app/data/reports/` dentro del contenedor del bot.

## Limpieza de archivos
- Los archivos subidos y los informes generados se eliminan automáticamente luego de ser enviados al usuario.

## Variables de entorno
- `REP_TEMPLATE_PATH=/app/templates/repetitividad.docx` ruta de la plantilla.
- `REPORTS_DIR=/app/data/reports` destino de los informes.
- `UPLOADS_DIR=/app/data/uploads` ubicación temporal de archivos subidos.
- `SOFFICE_BIN=/usr/bin/soffice` habilita la conversión a PDF. LibreOffice ya está instalado en la imagen del bot.
- `MAPS_ENABLED=false` habilita mapas cuando es `true`.
- `MAPS_LIGHTWEIGHT=true` usa Matplotlib sin stack geoespacial.

## Habilitar exportación a PDF
1. Instalar LibreOffice: `apt-get install -y libreoffice`.
2. Verificar la ruta del binario con `which soffice`.
3. Definir la variable de entorno `SOFFICE_BIN` con la ruta obtenida.
