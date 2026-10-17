# Nombre de archivo: fo_monitor.md
# Ubicación de archivo: docs/fo_monitor.md
# Descripción: Módulo FO Monitor — verificación PRE/POST de servicios por cable con burritoIA, semáforo y mapa offline

# FO Monitor

Cuando un técnico entra a una cámara o botella, FO Monitor compara el estado de última milla de los
servicios que pasan por los cables de esa cámara al ingreso (PRE) y al egreso (POST), y lo muestra
con un semáforo por cable en un mapa offline (`/infra/fo-monitor`). El estado lo obtiene burritoIA
(bot LLM de terceros en Slack, `U0A2HE3K950`), al que LAS-FOCAS menciona en un canal y del que parsea
las respuestas.

Relevamiento y decisiones: cuestionario de 80 preguntas + aclaraciones A1–A10 (2026-10-13/14).

## Estado (2026-10-17)

| Pieza | Estado |
|---|---|
| Fases 0–4 (PoC, modelo, worker, API, SPA + mapa base) | Integrado a `dev` y desplegado en **dev** (cierre 2026-10-17) |
| Piloto en dev | **Inactivo**. Sólo procesaría ingresos de `#baneo-de-camaras-prueba` (`C08UB8ML3LP`) |
| Producción | **Stand-by hasta nuevo aviso** (sin migrar ni desplegar). El canal productivo `C015UKWP2MS` no está habilitado |

## Arquitectura

```
app.ingresos ──(polling, marca de agua por id)──► fo_monitor_worker (:8098)
                                                   │ máquina de estados en app.fomon_* (proximo_evento_en)
                                                   │ WebClient bot token ──► chat.postMessage  @Burrito-IA verificar servicios …
                                                   │                     ◄── conversations.replies (polling 15 s)
web /api/fo-monitor/* ──► SPA FoMonitorView (MapLibre + PMTiles local, polling 30 s)
```

- **Sin hooks en `ingreso_service` ni en el listener.** El worker detecta ingresos nuevos por
  `ingresos.id > fomon_config.ultimo_ingreso_id_procesado` (no por fecha: revalidar/forzar ingreso
  escriben `fecha_inicio` en el pasado). La marca avanza siempre, aun con el piloto apagado.
- **Nunca Socket Mode en el worker**: sólo `WebClient` con `slack_bot_token_v1`. Una segunda conexión
  Socket Mode con el app token le quitaría eventos al listener de ingresos.
- **Todo el estado en la base**; un reinicio retoma. Una consulta marcada ENVIADA sin `slack_ts` se
  reconcilia buscando su token `FOMON-Q<id>` en el canal. `pg_try_advisory_lock` = una sola instancia.

## Reglas

**Alcance**: cámara del ingreso → CromoBotellas vigentes → cables vigentes clase 51/52/59/60 con
extremo en ellas → servicios `es_verificable` y "Activo". Primero la botella objetivo (la del
ingreso o la **Botella 1** = la hija sin sufijo "Bot N"); después el resto de la cámara. Un servicio
en varios cables se consulta una vez. La lista se congela al crear la intervención.

**Semáforo por cable** (orden de evaluación): GRIS (sin verificables o cobertura < 50 %) → ROJO
(100 % de los conocidos DOWN, aun con caídas nuevas) → AMARILLO (UP en PRE → DOWN en POST,
reverificado a los 4 min y no reconocido como ajeno) → VERDE (≥ 80 % UP) → NARANJA (resto).
`ADMIN_DOWN` y `NO_SOPORTADO` no cuentan. Lógica pura en `core/services/fo_monitor/semaforo.py`.

**Tiempos**: PRE válido de −15 a +20 min del ingreso (si no, "sin línea base": no hay amarillo);
POST tardío si se toma > 30 min después del egreso; "Sin egreso" a las 8 h; ingresos detectados con
más de 8 h se ignoran (reproceso histórico).

**Egreso**: todas las filas vinculadas con `fecha_fin`; o un EGRESO huérfano posterior en la misma
cámara (`egreso_inferido`); o una fila cerrada y otra abierta > 30 min.

## burritoIA

Resultados de la PoC real (2026-10-14, `scripts/fo_monitor_poc_burrito.py`, registros crudos en
`Logs/fo_monitor_poc/`):

- Responde menciones de **otro bot**, en el hilo del mensaje raíz.
- 1/3/5/10 servicios por mensaje en 20–76 s (procesa en paralelo). En el E2E un lote de 2 tardó
  213 s → timeout = 240 s + 20 s por servicio.
- El prompt importa: "SOLO última milla" (v1/v2) cae en un perfil de tráfico sin estado de puertos;
  **v3/v4** arrancan como un operador ("verificar servicio(s) X") y piden un bloque final
  `FOMON|<id>|<ESTADO>|<extremo>|<motivo>`. **v4** (default) además pide, si el equipo de acceso no
  es gestionable, validar la interfaz del equipo troncal/uplink (2 de 3 corridas lo hicieron; 1
  infirió por tráfico — variabilidad del LLM, a conversar con el dueño de burritoIA).
- Lotes mixtos (inexistente/FO entre válidos) responden línea por línea; un lote 100 % inválido
  corta sin bloque → el worker reintenta de a uno los IDs sin línea o DESCONOCIDO (hasta 3).

## Mapa (SPA)

- La red completa (~34k cables) **no se carga de entrada**: checkbox "Red FO completa" a pedido
  (1,4 MB gzip, ETag). La carga inicial es por buscador **Servicio / Cable / Cámara**.
- **Servicio**: 1 a 8 IDs (separados por coma, o tildando en la ficha del cable); un color por
  servicio (paleta OKLCH lejos de los tonos del semáforo) y líneas paralelas sólo de cerca
  (`line-offset` 0 hasta z12, `indice × 4 px` a z15). Fuentes GeoJSON con `tolerance: 0` (con la
  simplificación por defecto los tramos cortos desaparecían al alejar).
- **Clic en un cable** fuera de una intervención → ficha lateral: ID, nombre, extremos y servicios
  con estado comercial, verificable y último estado medido por FO Monitor.
- MapLibre 6 necesita su worker importado con `?worker&url` + `setWorkerUrl` (si no, Vite no lo
  emite y el mapa queda vacío): ver guardrail en `frontend-spa-architecture`.

## Configuración y operación

- **Kill switch**: fila `fo_monitor` de `app.config_servicios` (`activo`, `slack_channels` = canal
  donde se publican consultas y avisos).
- **`app.fomon_config`** (singleton, editable en la vista para admin; cada cambio queda en
  `fomon_config_auditoria`): ventana del piloto, tope diario de **mensajes** a burritoIA (400, día
  en hora AR), lote, timeouts, concurrencia, versión de prompt y **`canales_ingreso`** (canales cuyos
  ingresos se verifican; default sólo `C08UB8ML3LP`).
- **Geometría**: `python scripts/fo_monitor_generar_geo.py` (incremental por `vmax`; ~24 s la
  primera vez para 33.659 cables). Correrlo después de cada ingesta de cables Cromo.
- **Mapa base offline**: `scripts/fo_monitor_descargar_basemap.sh` (dry-run por defecto;
  `--aplicar --destino <checkout>/data/fo_monitor`). Recorte AMBA z15 = 66 MB + 14 MB de fuentes. Se
  monta de sólo lectura en el web (`FOMON_BASEMAP_DIR`). Sin el archivo, el mapa usa raster OSM.
- **Simular un ingreso en dev**: `python scripts/fo_monitor_simular_ingreso.py --sugerir` y luego
  `--camara-id <id> --tipo Ingreso|Egreso` (pasa por `registrar_movimiento_ingreso`).

## Hallazgos de datos

- **Cámaras sin Botella 1 propia**: 522 cámaras de prod tienen sólo botellas "Bot N" (la principal
  quedó asociada a una cámara duplicada, p. ej. "Cra Balcarce 520 CF" vs "C.F"). FO Monitor toma la
  de número más bajo y lo avisa (`botella_1_inferida`).
- 6 cables con el trazado a > 100 m de su botella (`fomon_cable_geo.calidad = 'extremo_lejano'`) y
  6 botellas con coordenadas inválidas (lon −150, en el mar).

## Archivos

- Núcleo: `core/services/fo_monitor/` (`alcance`, `prompt`, `parser`, `semaforo`, `estado`,
  `motor`, `slack_gateway`, `avisos`, `geometria`, `consultas_web`).
- Worker: `modules/fo_monitor_worker/`, `deploy/docker/fo_monitor_worker.Dockerfile`.
- Datos: `db/models/fo_monitor.py`, migración `20261014_02`.
- Web: `web/fo_monitor_routes.py`; SPA `web/frontend/src/views/FoMonitorView.vue` +
  `components/fo-monitor/`.
- Tests: `tests/test_fo_monitor_*.py` (los `*_real_db.py` corren en una transacción que se revierte
  porque las tablas de resultados son append-only).
