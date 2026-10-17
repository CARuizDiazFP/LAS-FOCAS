# Plan: cuarentena de inconsistencias de Cromo (islas, cables sin extremo) y fusiones de ODF (clase 141)

## Contexto

Al analizar el 102452 aparecieron inconsistencias de inventario en Cromo:
- **Cámara 10238011.** Los cables F-GTTttttttt-002-A-A-A y F-GTTttttt-003-B están fusionados 1:1 adentro, pero ninguno tiene su otro extremo. Los pelos llevan etiquetas de 8 servicios.
- **Medido en dev el 2026-10-17:**
  - 1.437 fusiones isla en uso, en 983 servicios y 648 elementos;
  - 228 elementos isla en uso;
  - 743 cables en uso sin algún extremo.
- **Validado contra Cromo en vivo:** una muestra de 12 cables confirma que el faltante es de Cromo y no de nuestra ingesta.

Cromo es la fuente de verdad y LAS-FOCAS sólo lo lee. Por eso no se borra ni se deja de ingerir nada. Lo que se corta es el paso en que esos pelos se vuelven "uso" de un servicio en LAS-FOCAS, mediante una cuarentena. La lista se reporta para corregirla en Cromo, y cada caso se cierra solo cuando Cromo queda bien.

**Reglas del usuario:**
- Lo que termina en ODF u ODF Nodo, o es ambiguo, va a revisión manual.
- Un servicio puede no terminar en ODF, pero todos sus pelos deben tener sus fusiones.
- La isla pura se pone en cuarentena automáticamente. El usuario aprobó el plan propuesto en el chat.

**Prerrequisito:** la conectividad por pelo hoy está inflada porque no ingerimos las fusiones de ODF (clase 141). En dev hay 18.115 conectores con `pelo_n_id` NULL que apuntan a una 141, repartidos en 1.639 ODF. Esos pelos figuran "sin fusión" en su extremo de ODF.

## Forma de trabajo

- **Worktree:** `python scripts/agent_worktree.py start --agent claude-inconsist --type feat --task cuarentena-inconsistencias-cromo`.
- **Leases y migraciones:** lease `db:migrations`. Antes de crear cada migración, ver `alembic heads` sobre origin/dev, porque otras sesiones integran.
- **Ejecución:** SDD, una tarea por bloque, con TDD.
- **Medición previa:** cada señal se mide contra la base y contra Cromo reales antes de fijarla (skills `cromo-diagnostico-real` y `pytest-focas`).
- **Alcance:** sólo dev. Prod va con aviso aparte.

## Task 1: Fusiones de ODF (clase 141) en los conectores

**Diagnóstico previo, sin escribir nada.** Confirmar contra Cromo si la respuesta completa de `get_inner` de una ODF trae los objetos 141 (por ejemplo KORN 6646686), o si sólo vienen en el `inner` liviano del barrido.
- Medido en `payload_raw`: 8.732 fusiones 141 tienen `tp` {130,136}, 262 tienen {136,136} y 9 no tienen `tp`.

**Parser.** `core/services/cromo/parser.py` `parse_odf_conectores` (~719-797) arma un mapa `{n_id de la 141: tp}` desde el mismo `inner`. Para cada conector cuyo `tp` apunte a una 141:
- **141 de tipo {136,130}:** `pelo_n_id` toma el pelo de la 141 y una columna nueva `fusion_odf_n_id` guarda la 141.
- **141 de tipo {136,136}:** `patch_conector_n_id` toma el otro conector.
- **141 sin `tp`:** todo queda NULL.

**Ingesta.** El parser recibe el `inner` que corresponda según el diagnóstico, en dos lugares:
- `_procesar_odf_directo` (`ingesta.py` ~1145-1200);
- el flujo paralelo de `relevar_odf` (`normalizacion_consistencia_service.py` ~248-272).

**Migración** `20261017_01_cromo_odf_fusion_conector`: columna `cromo_odf_conectores.fusion_odf_n_id BIGINT NULL` más el modelo. Downgrade real. Sin backfill: el `payload_raw` está desactualizado y lo resuelve una corrida SOLO_ODF.

**Consistencia del camino.** En `camino_optico_service.py`:
- `_pelo_del_conector` (~423-447) y `auditar_consistencia` resuelven conector → 141 → pelo usando el nodo `TIPO_FUSION_ODF` del `/path` (`pelos_fusionados`). Si no, la regla `REGLA_CONECTOR` marcaría DISCREPA en miles de conectores.
- Test con un conector que apunta a una 141.

**Datos.** Corrida SOLO_ODF en dev. Medir antes y después: conectores con `pelo_n_id` NULL, servicios "sin ODF" y pelos en uso sin unión.

## Task 2: Detector de inconsistencias y tabla de casos

**Migración** `20261017_02_cromo_inconsistencias`, reversible:
- **Tabla `app.cromo_inconsistencia`:**
  - `id`;
  - `tipo`: Text con CHECK `ISLA_FUSION`, `CABLE_SIN_EXTREMO` o `ELEMENTO_ISLA`;
  - `objeto_n_id`, `objeto_clase`, `nombre`, `localidad`;
  - `revision`: `AUTO` o `MANUAL`;
  - `estado`: `PENDIENTE`, `CUARENTENA`, `REPORTADA`, `CORREGIDA` o `ACEPTADA`;
  - `evidencia` JSONB con `none_as_null`;
  - `primera_vez`, `ultima_vez`, `actualizado_por`, `actualizado_en`;
  - UNIQUE (`tipo`, `objeto_n_id`).
- **Tabla `app.cromo_inconsistencia_pelo`:** (`inconsistencia_id` con FK CASCADE, `pelo_n_id`) como PK, con índice por pelo.

**Servicio** `core/services/cromo/inconsistencias_cromo.py`. El detector es SQL agrupado, sin consultas por fila; las consultas manuales de esta sesión tardaban entre 2 y 5 minutos, así que hay que medir y agregar índices si hace falta.
- **ISLA_FUSION:** una fusión 132 donde ninguno de los dos pelos tiene otra unión, con al menos uno en uso. Las uniones se cuentan como fusiones 132 más conectores de ODF, incluidos los que llegan por una 141 (Tarea 1).
- **CABLE_SIN_EXTREMO:** cable de clase 51, 52, 59 o 60, vigente, con algún extremo NULL y pelos en uso.
- **ELEMENTO_ISLA:** una botella en la que todos sus cables incidentes terminan sin otro extremo, con pelos en uso.
- **Revisión AUTO, la isla pura:** una fusión isla dentro de una botella, sin ODF ni ODF Nodo en el grupo, con ambos cables sin el otro extremo, confirmado contra Cromo en vivo. Se hace una llamada por cable y se guarda en la evidencia. Un caso AUTO entra directo en `CUARENTENA`.
- **Revisión MANUAL:** todo lo demás, incluido cualquier caso con extremo, elemento o conector de ODF u ODF Nodo, y cualquier caso ambiguo. Un caso MANUAL entra en `PENDIENTE`.
- **Upsert idempotente:** se actualiza `ultima_vez` y la evidencia, sin tocar los estados `ACEPTADA` ni `REPORTADA`.
- **Cierre automático:** un caso que deja de detectarse pasa a `CORREGIDA`, y con eso se levanta su cuarentena.

**Ejecución:**
- Al final de las corridas COMPLETA, SOLO_ODF y SOLO_PELOS_INNER, como paso posterior al commit, siguiendo el patrón de `encolar_recalculo_duplicados_botellas` (`ingesta.py` ~2429).
- También a mano, como corrida sintética en `cromo_worker`. Se reutiliza el patrón de `auditoria_huerfanos_global.py`: `iniciar_si_no_hay_otra`, eventos PAGINA y el SSE de corridas.

**Medición previa.** Correr el detector en modo reporte sobre dev, validar una muestra de cada tipo contra Cromo y contar cuántos casos salen AUTO y cuántos MANUAL. Ajustar los criterios con esos datos.

## Task 3: Cuarentena efectiva en todo lo que consume el uso

**La vista.** Se crea `app.v_cromo_servicio_match_vigente`: `cromo_servicio_match` sin los pelos de casos en `CUARENTENA`. Va en la misma migración o en una `_03`.

**Los consumidores.** Los que hoy leen `cromo_servicio_match` para el uso pasan a leer la vista. El cambio es el mismo en todos: reemplazar la tabla en el FROM o JOIN.
- `core/services/cromo/verificador.py`. Cubre Slack (Info y Verificar cable), los endpoints web, FO Monitor, la API v1 de cables y la protección de baneos.
- `core/services/servicio_traza.py`, que es la API v1 de servicios.
- `core/services/cromo/servicios_sin_odf.py`, `detalle.py`, `inventario.py` y `odf_inventario.py`.
- `core/services/fo_monitor/consultas_web.py`.
- `core/services/cromo/camino_optico_service.py`, en semillas, conteos y moda.

**Escrituras sin cambios.** Las escrituras siguen sobre la tabla: `fase_servicios`, `conciliar_matches_de_cable`, bajas y fusión de servicios.

**La marca visible.** El detalle de cable web y "Info cable" de Slack muestran el pelo en cuarentena con la marca "en cuarentena (inconsistencia Cromo)", en lugar del servicio, para que no parezca libre.

**Tests.** Uno por consumidor principal, con un pelo en cuarentena que deja de contar, y un test que recorre el repo verificando que ningún SELECT de consumo lea la tabla directo. Los tests contra base real se saltean si no hay base disponible.

## Task 4: Revisión manual en el portal

**Endpoints admin con CSRF** en `web/app/main.py`, junto a los de huérfanos (~9100-9230):
- listado paginado con filtros de tipo, estado, revisión, localidad y servicio;
- acciones en lote: `cuarentena`, `aceptar`, `reportada`, `liberar` (de vuelta a `PENDIENTE`);
- disparo de la corrida manual del detector.

**Viewer** `web/frontend/src/admin/views/AdminInconsistenciasCromoViewer.vue` en `/admin/servicios/viewer/InconsistenciasCromo`, con `requiresAdmin`. Copia el patrón de `AdminHuerfanosViewer.vue` y de `api/huerfanos.ts`: chips por tipo, "cargar más", recuadro de rechazados y stream con `?desde=`. Sólo tokens Nocturne.

**Enlace desde el servicio.** El panel Camino (`CromoCaminoPanel.vue`) muestra un aviso cuando el servicio tiene pelos en cuarentena o en revisión, con enlace al Viewer filtrado.

## Task 5: Reporte para corregir en Cromo y aviso de casos nuevos

**Exportación XLSX** por localidad, con una hoja por localidad. Patrón: `/api/admin/infra/botellas/inconsistencias/exportar` (`main.py` ~7637). Columnas: tipo, objeto, nombre, qué falta, servicios afectados y el ID de Cromo para buscarlo.

**Aviso de casos nuevos** al terminar el detector:
- publicación en el WebSocket admin (`ADMIN_NOTIFICATIONS_CHANNEL`, tipo `cromo_inconsistencias_nuevas`);
- mensaje en Slack con el XLSX adjunto mediante `slack_gateway.publicar` y `files_upload_v2`, usando el patrón de `notifier.py` ~78-130. El canal sale de una fila nueva "Cromo Inconsistencias" en `app.config_servicios`, que se crea deshabilitada. Para activarla hay que cargarle canal desde el admin.

## Task 6: Documentación

- Actualizar `docs/infra.md`, `docs/db.md` y `docs/PR/<fecha>.md`.
- Actualizar la memoria del proyecto. La hace el controlador.

## Verificación

1. **Tests:** `LLM_PROVIDER=heuristic pytest` de los archivos tocados y la suite completa, revisando el exit code real. Los 4 fallos del shell SPA ya se conocen.
2. **Migraciones:** upgrade, downgrade -1 y upgrade en la base de dev, con `DATABASE_URL` hacia 127.0.0.1:5433. Confirmar antes el head con `alembic current`.
3. **Fusiones 141:** después de la corrida SOLO_ODF, KORN O-1259853-3:39 tiene que quedar con el pelo 7914406 y la fusión 8884671. Medir cuánto bajan los conectores con pelo NULL.
4. **Detector en dev:**
   - la cámara 10238011 sale `ISLA_FUSION` y `ELEMENTO_ISLA` AUTO en `CUARENTENA`, y sus cables salen `CABLE_SIN_EXTREMO`;
   - los racks de subte (ODF Nodo) salen MANUAL;
   - los conteos se comparan con 1.437, 228 y 743.
5. **Cuarentena:**
   - el `track 102452` sigue dando 6 tramos;
   - "Info cable F-GTTttttt-003-B" muestra los pelos en cuarentena;
   - la API v1 y el detalle del servicio ya no cuentan esos pelos.
6. **Cierre automático:** simular en dev un caso corregido, quitándolo del resultado del detector con un fixture real, y verificar que pasa a `CORREGIDA` y libera los pelos.
