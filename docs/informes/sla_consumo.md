# Nombre de archivo: sla_consumo.md
# Ubicación de archivo: docs/informes/sla_consumo.md
# Descripción: Informe de SLA consumido — histórico persistido, fórmulas, grupos de cierre, idempotencia y salidas

## Propósito

El informe de **SLA consumido** responde cuánto del presupuesto de indisponibilidad de cada servicio
se gastó en los últimos 365 días y qué reclamos, eventos y tipos de cierre lo consumieron. A
diferencia del informe SLA mensual (`docs/informes/sla.md`), este informe **persiste** lo que
ingiere: cada corrida guarda los reclamos y una foto del SLA de cada servicio, de modo que el
detalle de un servicio muestra sus reclamos y la evolución de su SLA.

## Entradas

Dos Excel `.xlsx` que se suben juntos (el tipo se identifica por las columnas, no por el nombre):

- **Servicios**: una fila por servicio con su SLA prometido, el SLA entregado y las horas de reclamos
  del origen (`Horas Reclamos Todos`).
- **Reclamos**: una fila por reclamo con número de reclamo, evento, línea, primer servicio, fechas
  de inicio y cierre, `Tipo Solución Reclamo`, carrier y las horas del problema.

Valores medidos con los archivos reales de `docs/Doc Privada/` (corrida del 2026-10-05 en dev):
7228 servicios, 4517 reclamos, 402 eventos distintos.

## Reglas de cálculo

- **Fecha de corte**: automática, es el máximo de `Fecha Cierre Problema Reclamo` del Excel de
  reclamos (en la corrida real: 2026-10-02). No se pide al usuario.
- **Ventana**: 365 días hacia atrás desde la fecha de corte.
- **Base**: `Horas Netas Problema Reclamo`, en **horas**.
- **Presupuesto** del servicio: `(1 − SLA/100) · 8760` horas.
- **% del presupuesto** = `horas / ((1 − SLA/100) · 8760)`.
- **pp** (puntos porcentuales de SLA consumidos) = `horas / 8760 · 100`.

Ejemplo real (línea 88102, SLA 99,7): presupuesto 26,28 h; el reclamo 1277261 con 6,2839 h consume
23,91 % del presupuesto.

## Grupos de cierre

El `Tipo Solución Reclamo` se clasifica por el código que va entre paréntesis al final
(`core/sla_consumo/clasificador.py`):

| Grupo | Cuenta para el SLA |
|---|---|
| FO (excepto Cod 3) | Sí |
| FO Cod 3 (Corte en Bandeja) | Sí |
| Carrier | Sí |
| Otros | Sí |
| Cierre Cliente | **No** (sólo este grupo no cuenta) |

Hoy ningún tipo de solución cae en Cierre Cliente: la lista es configurable con la variable
`SLA_CIERRE_CLIENTE_VALORES` (valores de `Tipo Solución Reclamo` separados por `;`, comparación sin
acentos ni mayúsculas) y por defecto está **vacía**. Ver `deploy/env.sample` y `deploy/env.dev.sample`.

Distribución real de los 4517 reclamos: FO (excepto Cod 3) 2808, Otros 974, Carrier 581,
FO Cod 3 154, Cierre Cliente 0.

## Idempotencia

- Cada ingesta registra el **hash del par de archivos**. Subir el mismo par de nuevo responde
  `ya_ingestado: true` y no modifica ninguna tabla (verificado: 4517 reclamos y 7228 fotos antes y
  después).
- Los reclamos se hacen **upsert por `numero_reclamo`**, de modo que archivos nuevos que se solapan con
  los anteriores actualizan en lugar de duplicar.
- La foto de SLA es una por `(numero_linea, fecha_corte)` en `app.servicio_sla_snapshot`.

## Salidas

- **XLSX** con las hojas: Resumen, Eventos, Servicios, Servicio x Reclamo, Código de cierre,
  Detalle tipo solución y Carrier x Cliente.
- **DOCX** con tablas y gráficos de repercutores (y PDF opcional si `SOFFICE_BIN` está disponible).
- Archivos en `REPORTS_DIR/sla_consumo/AAAAMM/SLA_consumido_<fecha_corte>_<sello>.{xlsx,docx}`.
- Tablas: `app.reclamos` (ampliada), `app.sla_ingestas`,
  `app.servicio_sla_snapshot` y la vista de eventos (migración `20261005_02`).

## Endpoint y SPA

- `POST /api/reports/sla-consumo` (multipart con los dos `.xlsx`, `pdf_enabled` opcional, CSRF).
  Se usa desde `/sla`, pestaña **SLA consumido**.
- `report_history`: `period_month/period_year` es el **mes de la corrida** (la tabla los exige NOT
  NULL); la `fecha_corte` real va en `output_metadata`.
- El detalle de servicio (`GET /servicios/detail`) ahora devuelve `reclamos` (con `pct_presupuesto` y
  `cuenta_sla`) y `sla_historico` (una fila por fecha de corte).

## Corrección de `/ingest/reclamos`

La ingesta legacy escribía mal las horas: ahora guarda **horas** (antes minutos), acepta duraciones
mayores a 24 h, corrige la inversión día/mes en fechas, convierte `-` en NULL y limpia IDs que llegaban
como float.

## Nota de conciliación

El SLA oficial del origen (`Horas Reclamos Todos` del Excel de servicios) difiere de la suma de horas
netas de los reclamos en **99 líneas**. El informe usa las **horas netas** por decisión del usuario
(2026-10-05). Para la línea 88102 ambas coinciden: 390,0589 h.

Verificación de totales: Σ horas netas del Excel 44769,4097 h vs. 44769,4071 h en la base (la diferencia
es el redondeo a 4 decimales al persistir).
