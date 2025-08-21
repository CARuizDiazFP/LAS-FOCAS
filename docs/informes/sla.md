# Nombre de archivo: sla.md
# Ubicación de archivo: docs/informes/sla.md
# Descripción: Documentación del informe de SLA

## Columnas esperadas y mapeos
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
- `SLA_TEMPLATE_PATH=/app/templates/sla.docx` ruta de la plantilla.
- `REPORTS_DIR=/app/data/reports` destino de los informes.
- `UPLOADS_DIR=/app/data/uploads` ubicación temporal de archivos subidos.
- `SOFFICE_BIN=/usr/bin/soffice` para habilitar PDF (opcional).
