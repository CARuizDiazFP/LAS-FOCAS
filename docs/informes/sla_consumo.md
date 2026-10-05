# Nombre de archivo: sla_consumo.md
# Ubicación de archivo: docs/informes/sla_consumo.md
# Descripción: Informe de SLA consumido — servicio unificado, semáforos, estados, impacto de eventos, salidas y contrato web

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
- **Ventana**: 365 días hacia atrás desde la fecha de corte. Entran los reclamos que **solapan** la
  ventana (`fecha_inicio < fin AND (fecha_inicio >= inicio OR fecha_cierre >= inicio)`): un reclamo
  iniciado antes del comienzo de la ventana y cerrado dentro de ella se cuenta **completo**.
- **Base**: `Horas Netas Problema Reclamo`, en **horas**.
- **Presupuesto** del servicio: `(1 − SLA/100) · 8760` horas.
- **% del presupuesto** = `horas / ((1 − SLA/100) · 8760)`.
- **pp** (puntos porcentuales de SLA consumidos) = `horas / 8760 · 100`.

Ejemplo real (línea 88102, SLA 99,7): presupuesto 26,28 h; el reclamo 1277261 con 6,2839 h consume
23,91 % del presupuesto.

## Grupos de cierre

El `Tipo Solución Reclamo` se clasifica en `core/sla_consumo/clasificador.py` con esta regla:

- **Carrier**: el texto es exactamente `Carrier`.
- **FO**: el texto empieza con `PE-`; si el código entre paréntesis al final es 3 es **FO Cod 3**,
  en cualquier otro caso **FO (excepto Cod 3)**.
- **Cierre Cliente**: el texto está en la lista configurable (abajo).
- **Otros**: todo lo demás.

**Reclasificación al calcular**: el grupo y el código se derivan de `tipo_solucion` cada vez que se
calcula el informe (no se confía en lo guardado), por lo que un cambio en
`SLA_CIERRE_CLIENTE_VALORES` se aplica **retroactivamente** a todo el histórico y las filas ingeridas
por la ruta legacy (sin grupo) quedan igualmente clasificadas; Σ de los grupos = Σ del total.

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
- **Upsert monótono**: un reclamo existente sólo se pisa si la ingesta que lo escribió por última vez
  tiene `fecha_corte` <= la de la ingesta actual (o si es una fila legacy sin ingesta). Subir un
  Excel más viejo no sobrescribe reclamos más nuevos; esas filas se informan como `reclamos_sin_cambios`.
- La foto de SLA es una por `(numero_linea, fecha_corte)` en `app.servicio_sla_snapshot`.

## Servicio unificado e ID visible

Un mismo servicio puede cambiar de número de línea (upgrades). El informe lo unifica en
`core/sla_consumo/identidad.py`:

- **Clave interna**: `numero_primer_servicio` (si falta, la propia `numero_linea`). Sólo se usa para unificar.
- **ID visible**: la línea **numéricamente mayor** del grupo (comparación como entero: 9 y 10 dan 10; las
  no numéricas pierden contra las numéricas). Es la línea más actualizada.
- **No se muestra la "línea original"** del reclamo (`Número Línea Reclamo`); el reclamo se vincula por
  primer servicio y se muestra bajo el servicio unificado. El detalle conserva `lineas_asociadas`.
- SLA prometido y métricas oficiales salen **sólo de la fila de referencia**, nunca se suman entre líneas.
- Los reclamos no vinculables (ni por primer servicio ni por línea) quedan en `no_vinculados`, sin
  presupuesto, y se informan aparte.
- El universo del informe son **todos** los servicios de la foto del corte, con o sin reclamos.

## Causas, semáforo y estados (`core/sla_consumo/metricas.py`)

- **Causa** por grupo de cierre: **FO** = FO general + FO Cod 3; **Carrier**; **Otros**. Cierre
  Cliente (o 0 h) queda **excluido**: no computa.
- **Indicador del reclamo**: Rojo si su causa es FO; Verde si es Carrier u Otros; sin color si no computa.
- **Semáforo del servicio** (sobre horas computables): Rojo = sólo FO (general o Cod 3); Amarillo = FO
  y además Carrier/Otros; Verde = sólo Carrier/Otros; sin color = sin horas computables. El color
  describe la causa, **no el cumplimiento**: un servicio Verde puede estar excedido por causas ajenas a FO.
- **Estado del presupuesto**: Sin consumo / Dentro de SLA / Presupuesto agotado (consumo igual al
  presupuesto) / SLA excedido (mayor) / No evaluable (sin SLA prometido o sin presupuesto válido).
- **Tolerancia**: `EPS_HORAS = 1e-6` h (3,6 ms) absorbe el ruido de punto flotante. Un presupuesto es
  válido si es finito y `> EPS_HORAS`. Los estados comparan valores **sin redondear**; con 26 h
  exactas consumidas el servicio queda Agotado, no Dentro.

## Métricas por servicio

Presupuesto (h), horas netas, computables, excluidas, FO, FO general, FO Cod 3, Carrier, Otros,
restantes, excedidas, % real del presupuesto (puede superar 100 %), % visible (tope 100 %), aporte FO
(% del presupuesto) y participación FO (% de lo consumido), cantidad de reclamos, de eventos reales y de
reclamos sin evento, semáforo y estado. Valores sin redondear en el XLSX; formato `h:mm` en pantalla.

## Acumulados por servicio y sus límites (`core/sla_consumo/impacto.py`)

Los reclamos de un servicio se ordenan por `fecha_inicio` y, a igualdad, por `numero_reclamo` numérico;
para cada uno se calculan consumo acumulado antes y después, horas restantes y excedidas tras el
reclamo, y si **alcanza** o **supera** el presupuesto por primera vez. **Límite**: el acumulado es una
**atribución por orden**, no el instante físico en que se agotó el presupuesto; dos reclamos
solapados se ordenan igual.

## Impacto Evento × Servicio

Para cada par (evento real, servicio unificado) se calculan las horas aportadas, el % real al
presupuesto, el consumo total y estado final del servicio, y tres indicadores:

- **Suficiente solo**: el evento, por sí solo, agota o excede el presupuesto (`agota` / `excede` / `no`).
- **Cruza el umbral**: en el orden de atribución, el evento es quien lleva el acumulado a alcanzar o
  superar el presupuesto por primera vez.
- **Determinante al excluir**: si se lo excluye, el servicio deja de estar agotado/excedido. Exigir "por
  debajo" del presupuesto: si sin el evento el servicio queda **exactamente** en el presupuesto, el
  evento cruza (`cruza=True`) pero no es determinante (`determinante=False`).

`participa_en_excedido` se informa aparte. **Participación ≠ causa**: haber aportado horas a un servicio
agotado o excedido no implica haberlo causado ni es una atribución de responsabilidad.

El **resumen por evento** trae: rango observado (mínimo y máximo de fechas de sus reclamos, **no** la
duración oficial), reclamos, servicios unificados afectados (sin duplicar líneas), **horas-servicio**
(suma de las horas de cada reclamo en cada servicio: un evento que afecta a 10 servicios durante 2 h suma
20 h-servicio, no 2 h), servicios agotados/excedidos al cierre, cantidad y listado por indicador y
desglose por causa. Los reclamos **sin evento** tienen la misma vista con el ID de reclamo como clave.

## Reclamos sin vincular e inconsistencias

- **No vinculados**: reclamos sin servicio en el universo; sus horas se informan aparte y no entran en
  la torta ni en los totales de horas vinculadas.
- **Inconsistencias**: reclamos **Carrier con número de evento** (la regla de negocio no asocia Carrier
  a eventos FO), eventos que mezclan FO y no-FO, no vinculados y servicios no evaluables. Se listan; **la
  causa no se reasigna**.

## Totales (`totales`)

`reclamos` y `horas_netas` cuentan **todos** los reclamos; las demás horas (computables, excluidas,
FO general, FO Cod 3, Carrier, Otros) cuentan **sólo los vinculados**; `horas_no_vinculadas` va aparte.

## Salidas

Archivos en `REPORTS_DIR/sla_consumo/AAAAMM/SLA_consumido_<fecha_corte>_<sello>[_ejecutivo|_exhaustivo].{xlsx,docx}`.

- **XLSX** (11 hojas, autofiltro, paneles inmovilizados, duraciones `[h]:mm`, porcentajes, colores de
  semáforo y estado, todas las filas): Resumen y leyendas, Servicios, Servicio x Reclamo, Eventos,
  Evento x Servicio, Reclamos sin evento, Inconsistencias, No vinculados, Codigo de cierre, Detalle tipo
  solucion y Carrier x Cliente.
- **DOCX ejecutivo**: resumen global, leyendas, **una torta global** de horas computables por causa
  (FO general / FO Cod 3 / Carrier / Otros; sin torta por servicio ni por reclamo), ranking de eventos por
  horas-servicio con gráfico de magnitud (top **`SLA_CONSUMO_TOP_EVENTOS`**, 20 por defecto) y fichas
  completas de los servicios **agotados o excedidos** con su detalle de reclamos y acumulados.
- **DOCX exhaustivo**: lo anterior sin límite de eventos, ficha completa de **todos los servicios con
  reclamos**, **tabla compacta** de los servicios sin reclamos (todos figuran), reclamos sin evento,
  inconsistencias y no vinculados.
- **PDF** opcional sólo del ejecutivo (si `SOFFICE_BIN` está disponible). El **exhaustivo nunca se
  convierte dentro del request**: LibreOffice tarda ~6,5 min.
- Tablas: `app.reclamos` (ampliada), `app.sla_ingestas`, `app.servicio_sla_snapshot` y la vista de
  eventos (migración `20261005_02`). Esta ampliación **no requiere migración nueva**.

## Endpoint y SPA

- `POST /api/reports/sla-consumo` (multipart con los dos `.xlsx`, `pdf_enabled` opcional, CSRF), todo
  en la **misma solicitud**. Se usa desde `/sla`, pestaña **SLA consumido**, con tres enlaces
  etiquetados.
- Respuesta: `ok`, `fecha_corte`, `totales`, `report_paths` con `xlsx`, `docx_ejecutivo`,
  `docx_exhaustivo` y `pdf_ejecutivo` (sólo si se generó). Si se pidió PDF, `pdf_omitido` explica por
  qué no hay `pdf_exhaustivo`.
- `report_history`: `period_month/period_year` es el **mes de la corrida** (la tabla los exige NOT
  NULL); la `fecha_corte` real va en `output_metadata`.
- El detalle de servicio (`GET /servicios/detail`) devuelve `reclamos` (con `pct_presupuesto` y
  `cuenta_sla`) y `sla_historico` (una fila por línea y fecha de corte, en orden cronológico; la vista
  toma la última como "Última foto de SLA"). Usa una ventana propia de **ahora − 365 días** y el
  `sla_prometido` de `app.servicios`, por lo que puede diferir levemente del informe.
- Si se pide PDF y `SOFFICE_BIN` no está configurado, la respuesta trae `pdf_omitido` y el SPA lo muestra.

## Limitaciones

- El acumulado es atribución por orden, no el instante físico (ver arriba).
- Horas-servicio no es la duración del evento; el rango observado no es la duración oficial.
- El DOCX ejecutivo mide ~290 páginas y el exhaustivo es mucho mayor (2368 fichas); no hay PDF del
  exhaustivo en línea.
- Carrier con evento no se reasigna: sólo se lista como inconsistencia.
- `SLA_CIERRE_CLIENTE_VALORES` vacía: ningún reclamo cae hoy en Cierre Cliente.
- Prod no está migrada ni desplegada con esta versión.

## Cifras reales (dev, corte 2026-10-02, medidas el 2026-10-05)

7228 servicios, 4517 reclamos (todos vinculados), 2368 servicios con reclamos, 1948 dentro de SLA, **420
excedidos**, 0 agotados, 4860 sin consumo, 402 eventos, 2184 filas Evento x Servicio, 2310 reclamos sin
evento, 68 inconsistencias (66 reclamos Carrier con evento en 19 eventos + 2 eventos mixtos). Horas netas
44769,4071 h: FO general 28949,6802, FO Cod 3 995,1343, Carrier 8898,3047, Otros 5926,2879. Corrida
completa en proceso (par ya ingestado, `ya_ingestado: true`): ~33 s sin PDF; el DOCX ejecutivo
convertido en el contenedor office tarda ~42 s (291 páginas).

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
