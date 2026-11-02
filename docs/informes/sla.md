# Nombre de archivo: sla.md
# Ubicación de archivo: docs/informes/sla.md
# Descripción: Documentación del informe de SLA (motor único, columna P) para consumo desde SPA y API

## Resumen

Desde P25 (2026-11-02) hay **un solo cálculo de SLA** en el repositorio: el de `core/sla_consumo`
(`engine.calcular`). Lo usan el informe **SLA consumido** (`/api/reports/sla-consumo`, ver
`docs/informes/sla_consumo.md`) y el **informe SLA mensual** de esta
página, en sus dos modos:

1. **Modo Excel**: dos archivos, "Servicios" (normalmente el filtrado "Servicios Fuera de SLA") y "Reclamos".
2. **Modo base** ("Usar base de datos"): `app.reclamos` y las fotos de `app.servicio_sla_snapshot`.

El informe mensual no calcula: `core/sla/informe.py` arma los datos desde el motor y
`core/sla/legacy_report.py` los vuelca en la plantilla heredada (`Templates/Template_Informe_SLA.docx`).

## Regla de cálculo

- **Horas**: columna P del Excel de reclamos, **"Horas Netas Cierre Problema Reclamo"**. Es la que se usó
  siempre (confirmado por el usuario el 2026-10-29) y la única que reproduce el "SLA Entregado" oficial:
  medido el 2026-11-02 con los Excel reales, coincide en **7.228 de 7.228** servicios (con la N, 6.136;
  con la U, 5.185). La N ("Horas Netas Problema Reclamo") se sigue guardando porque la usa Repetitividad;
  la U ("Horas Netas Reclamo") no se usa.
- **SLA entregado** = 1 − horas computables / 8.760, sobre los **365 días** al corte. Computables = todas
  las horas P salvo los cierres "Cliente" (`SLA_CIERRE_CLIENTE_VALORES`, vacía hoy).
- **Diferencia con el oficial**: el sistema de origen redondea sus horas de otra forma; la diferencia
  máxima medida es 2,7·10⁻⁶ (≈ 1,2 min/año). Mostrado con dos decimales, algún servicio en el borde del
  redondeo puede diferir en 0,01 punto (3 de 388 en el golden del 2026-11-02).
- **Vinculación reclamo → servicio**: por "Número Primer Servicio" si existe en el universo, si no por
  "Número Línea" (`core/sla_consumo/identidad.py`).
- Un reclamo **sin columna P** (ingerido antes de P25 y no completado) cuenta 0 h y se informa
  (`totales.reclamos_sin_horas_cierre` y la inconsistencia "Reclamo sin Horas Netas Cierre (columna P)").

## Modo Excel

- Encabezados obligatorios de Reclamos: Número Reclamo, Número Línea, Nombre Cliente, Fecha Inicio/Cierre
  Problema Reclamo, Horas Netas Problema Reclamo (N), **Horas Netas Cierre Problema Reclamo (P)** y Tipo
  Solución Reclamo. De Servicios: Número Línea, Nombre Cliente, SLA Prometido y Horas Reclamos Todos
  (`core/sla_consumo/parser.py`). Las fechas y horas se leen como las guarda Excel (seriales y `[h]:mm`).
- El informe trae **un servicio por fila del Excel de Servicios**, de mayor a menor SLA, con todas las
  horas P de sus reclamos del archivo (el export ya es de 12 meses) y el detalle de cada reclamo. La fecha
  del detalle es "Fecha Inicio Problema Reclamo" (hasta P25 salía `01-ene-70` en todas las filas: el
  serial de Excel se leía como 1970).
- El modo Excel no escribe en la base (el que persiste es "SLA consumido").

## Modo base

- Corte = último día del mes pedido; reclamos de los 365 días al corte (`app.reclamos`, columna
  `horas_netas_cierre`); universo y SLA prometido = la **última foto conocida de cada línea** en
  `app.servicio_sla_snapshot` (las fotos se cargan al subir "SLA consumido").
- Servicios del informe: los que tienen algún reclamo **del mes** (cierre en el mes, o inicio en el mes si
  no tiene cierre; mismo criterio que Repetitividad). Sus horas y su SLA son los de los 12 meses.
- Medido en `focas_dev` el 2026-11-02: con corte 02/10/2026 coincide con la foto oficial en 7.228/7.228;
  septiembre 2026 da 445 servicios y 99,736 % de promedio.
- Mismo documento que el modo Excel (antes de P25 el modo base usaba otra plantilla y otro cálculo:
  horas de reloj apertura→cierre del mes).

## Uso por Web Panel

**Endpoint**: `POST /api/reports/sla` (`web/app/routers/informes.py::generar_informe_sla_web`, requiere
sesión y `csrf_token` en el form). Campos del form: `mes`/`anio` (o `periodo_mes`/`periodo_anio`),
`pdf_enabled`, `use_db` y `files` (multipart). Vista `/sla` de la SPA.

- Sin `use_db` se requieren **exactamente 2 archivos `.xlsx`**; el tipo de cada uno se reconoce por sus
  columnas (`legacy_report.identificar_excel`).
- "Generar PDF" lo convierte `office_service` (`core/services/office_client.py`); si falla, se entrega el
  DOCX y el aviso `pdf_error`.
- Códigos de rechazo (`{"ok": false, "error": "..."}`, cada uno registrado en el historial): 403 CSRF
  inválido, 422 período no numérico o fuera de rango, 400 si no llegan exactamente dos archivos o uno
  está vacío, 415 si un archivo no es `.xlsx`, 422 si un Excel no se reconoce, se repite el tipo o le falta
  una columna obligatoria (por ejemplo la P), y 500 `Error interno (ref …)` ante un fallo inesperado (la
  ref permite ubicarlo en `Logs/web.log`).
- Cada generación registra una entrada en `app.report_history` (fuente `excel-legacy` o `db`).

```json
{
  "ok": true,
  "message": "Informe SLA generado correctamente",
  "report_paths": {
    "docx": "/reports/sla/202510/InformeSLA_20251105_143012.docx",
    "pdf": "/reports/sla/202510/InformeSLA_20251105_143012.pdf"
  },
  "source": "excel-legacy"
}
```

`report_paths.pdf` sólo aparece si se pidió PDF y la conversión funcionó. En los dos modos el archivo es
`sla/AAAAMM/InformeSLA_<AAAAMMDD_HHMMSS>.docx` y se descarga con `GET /reports/{ruta}` (requiere sesión).

## Otras rutas

- `POST /api/flows/sla` (panel, sin consumidores en la SPA): un Excel de **reclamos** opcional; sin
  archivo usa el modo base. Con archivo, el universo de servicios es la última foto de la base y los
  servicios del informe, los que tienen reclamos del mes. Devuelve `metrics` con las claves de siempre.
- API (`api/app/routes/reports.py`, API key): `POST /reports/sla` y `GET /reports/sla/preview`. Contrato en
  `docs/api.md`. Desde P25, `disponibilidad_pct` es el SLA entregado a 12 meses y `downtime_h` las horas P
  de esos 12 meses (antes: disponibilidad del mes con horas de reloj).

## Paths y variables de entorno

- Informes en `REPORTS_DIR` (`/app/data/reports/` en el contenedor); plantilla en
  `SLA_TEMPLATE_PATH` (default `${TEMPLATES_DIR}/Template_Informe_SLA.docx`).
- `OFFICE_SERVICE_BASE` (default `http://office:8090`): servicio que convierte el PDF; `web`/`api` no
  tienen LibreOffice.
- `SLA_TIMEZONE`, `SLA_MERGE_GAP_MINUTES` y `SLA_MIN_DOWNTIME_MINUTES` ya no existen (eran de la pila
  retirada en P25).

## Completar la columna P en una base existente

Los reclamos ingeridos antes de P25 no tienen `horas_netas_cierre`. Dos formas de completarla (sólo
escribe donde está en NULL):

- Re-subir el mismo par en "SLA consumido": responde "ya estaban ingestados" y completa
  (`horas_cierre_completadas` en la respuesta).
- `scripts/sla_completar_horas_cierre.py --reclamos <xlsx> [--aplicar]` (dry-run por defecto; instrucciones
  en el encabezado del script). En `focas_dev` (2026-11-02): 4.517 completados, quedan 16 de una ingesta
  posterior cuyo archivo no está.

## Tests

- `tests/test_sla_informe.py`: modo base (filtro del mes, ventana de 12 meses), contrato JSON y preview.
- `tests/test_sla_legacy_report.py`: render (horas P, SLA calculado, fechas reales, columna P obligatoria).
- `tests/test_api_reports_sla.py`, `tests/test_web_sla_flow.py`, `tests/test_web_sla_generar_ramas.py`:
  contratos de las rutas. Fixtures con los encabezados reales en `tests/soporte_sla.py`.
- Motor: `tests/test_sla_consumo_*.py`.

## Historia

- 2025-11 / 2026-01: correcciones del flujo web y un cambio a la columna U que el código nunca aplicó (el
  render siempre leyó la P).
- 2026-10-05: "SLA consumido" se construyó con la columna N (`docs/decisiones.md`), corregido en P25.
- 2026-11-02 (P25): motor único sobre la columna P; se retiraron `core/sla/engine.py` (`calcular_sla`),
  `core/sla/parser.py`, `core/sla/report.py` y `modules/informes_sla`.
