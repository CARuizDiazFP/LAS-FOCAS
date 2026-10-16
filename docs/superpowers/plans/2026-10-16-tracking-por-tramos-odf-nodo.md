# Plan: ODF Nodo (clase 86), tracking por tramos y auditoría de huérfanos

## Contexto

El 2026-10-05, `@Registrador track 102452` devolvió sólo el primer tramo del servicio y listó 163 pelos como "huérfanos". El diagnóstico, verificado contra Cromo real y la base de dev, encontró tres causas:

1. **Cromo corta el camino en las ODF Nodo.** En "NODO Alejandro KORN", el servicio entra por O-1259853-1:39/40 y sigue por O-1259853-2:3/4, pero no hay patch cargado entre esos conectores. `/path` devuelve un tramo por vez.
2. **La regla de caminos esperados no sirve para servicios segmentados.** La moda de pelos por cable da 2, así que el lazo corta después del primer tramo. Los otros tramos reales quedan como huérfanos. El 102452 tiene 3 tramos grandes, de 2 hilos cada uno, más 21 caminos chicos residuales.
3. **La clase 86 no se ingiere.** Es "ODF Nodo" según la web de Cromo, una clase aparte: hay 154 objetos de clase 86 contra 7.973 de clase 69. `app.cromo_clases` la tiene rotulada como `NODO` con `ingerible=false`. Por eso sus conectores no existen en LAS-FOCAS.

Pedido del usuario:
- Corregir el catálogo e ingerir la clase 86.
- Tracking por tramos, con los trackings descargados por separado.
- Quitar el aviso de huérfanos de Slack.
- Auditar los huérfanos, con normalización asistida.
- Confirmar las ODF de cada servicio como fuente de verdad.
- Declarar cuántos trackings se esperan por servicio.

Decisiones del usuario:
- La clase 86 lleva un tipo nuevo, `ODF_NODO`.
- Los huérfanos tienen causas distintas: cambio de cable por daño, cable en desuso, pelo dañado y migración de sitio. Se validan con una auditoría.
- No se excluye nada a ciegas. Una FO que sale de una ODF Nodo y no termina en otra ODF **no** es huérfana.
- Una ODF sin confirmar sigue funcionando como hoy.
- Para el 102452 se esperan 4 o 6 trackings, todavía por validar.

## Forma de trabajo

- Se trabaja en un worktree propio: `python scripts/agent_worktree.py start --agent claude-cromo --type feat --task tracking-por-tramos-odf-nodo`.
- Lease `db:migrations` durante las migraciones.
- Ejecución por SDD, una tarea por bloque.
- Sólo dev. Prod queda para un despliegue aparte con aviso al usuario, según la directiva vigente.
- Cada tarea arranca con TDD. Las tareas de datos se miden primero contra Cromo y la base reales, siguiendo las skills `cromo-diagnostico-real` y `pytest-focas`.

## Task 1: Catálogo e ingesta de la clase 86

**Migración `db/alembic/versions/20261016_01_cromo_odf_nodo.py`**, reversible:
- En `cromo_clases`, la 86 pasa a `entidad='ODF_NODO'`, `ingerible=true`, `motivo_exclusion=NULL` y `count_cromo=154`.
- El CHECK de `cromo_odfs.tipo_elemento` suma `ODF_NODO`. Se toma como plantilla `20260929_03_cromo_clases_cables_terceros.py`.
- Columna nueva `cromo_odf_conectores.patch_conector_n_id BIGINT NULL`.

**`core/services/cromo/ingesta.py`**
- `CLASES_ODF = (69, 86)`.
- Se usa en `CLASES_CONTEO` (:80), en el filtro de `fase_odfs` (:1232, con `",".join(...)` como en `fase_botellas`), en `SOLO_ODF.clases_objetivo` (:2222) y en `clases_a_contar` (:2325).
- `_procesar_odf_directo` (:1174) registra el evento con `odf.clase`.

**`core/services/cromo/parser.py`**
- `_DISPATCH` agrega `86: parse_odf`.
- `parse_odf` asigna `tipo_elemento='ODF_NODO'` cuando la clase es 86, sin pasar por el regex de nombre.
- **Bug latente en `parse_odf_conectores`** (:783-786): el fallback `pelo_n_id = tp[0].id_to` guarda un conector o una fusión ODF como si fuera un pelo.
  - Ahora `pelo_n_id` sólo sale de `tp` de clase 130.
  - Un `tp` de clase 136 va a `patch_conector_n_id`.
  - Hay que medir en dev cuántas filas actuales tienen hoy un `pelo_n_id` que no es un pelo, y corregirlas con un backfill.

**`core/services/cromo/normalizacion_consistencia_service.py`**
- `relevar_odf` (:248) acepta `CLASES_ODF`.
- Los eventos de :253 y :327 se registran con la clase real.

**`core/services/cromo/camino_optico_service.py`**
- `_CLASES_FALLBACK` agrega `86: "ODF_NODO"`.
- `_TABLAS_VINCULABLES` agrega `ODF_NODO` apuntando a `cromo_odfs`.
- La rama `_CLASE_NODO` (:565) se mantiene para el nombre.

**Frontend**
- Badge y filtro `ODF_NODO` en `InventarioOdfsCromoView.vue` y `OdfDetalleCromoView.vue`.
- Tipo `ODF_NODO`, con etiqueta "ODF Nodo", en `api/cromoPath.ts`.
- Etiqueta de `SOLO_ODF` en `api/cromo.ts:106`: "ODFs y ODF Nodo (clases 69 y 86)".

**Efecto lateral a verificar:** `core/services/nodos_catalogo.py:118` va a sumar los nombres de las ODF Nodo al catálogo de nodos del listener de ingresos. Hay que correr `tests/test_busqueda_camaras_sin_match.py` y revisar casos reales.

**Datos en dev**
- Corrida `SOLO_ODF` desde el admin.
- Después, `scripts/cromo_backfill_conectores_odf.py --apply` dentro del contenedor.
- Validar que NODO Alejandro KORN aparezca con sus 456 conectores, y que el 102452 tenga posiciones en O-1259853-1:39/40 y O-1259853-2:3/4.

## Task 2: Tracking por tramos

**`core/services/cromo/tracking_service.py`**
- `trackings_por_camino` deja de cortar en `esperados`. Pide caminos hasta cubrir **todas** las semillas, salteando las ya cubiertas.
- Tiene un tope de seguridad `max_llamadas`, con default 80 y configurable por env `CROMO_TRACKING_MAX_LLAMADAS`. Si se llega al tope, se avisa como incompleto.
- Se mantiene `max_fallidos`.
- Cada `TrackingGenerado` suma `extremos`: el primer y el último nodo de `secuencia_para_tracking`, con tipo, ODF, clase, patchera y conector, más un `rol`, que puede ser `TRAMO` o `RESIDUAL`.

**Clasificación**, en una función pura nueva `clasificar_caminos` con test propio:
- `TRAMO` es un camino con al menos un extremo en un conector de ODF o de ODF Nodo. Así quedan protegidas las FO que salen de una ODF Nodo y no terminan en otra ODF.
- También es `TRAMO` un camino que toca una ODF confirmada del servicio (ver Tarea 4).
- Si el servicio no tiene ninguna ODF, como el 94673, son `TRAMO` los caminos que tienen par: otro camino con los mismos cables.
- El resto es `RESIDUAL`.
- **Antes de fijar la regla se mide sobre 102452, 42351, 93154 y 94673 contra Cromo real.** Los umbrales salen de esa medición, no de una suposición.

**Caché**
- Migración: columna `cromo_tracking_cache.extremos JSONB NULL`, con `none_as_null=True` (ver la memoria sobre JSONB).
- Un registro con `extremos IS NULL` se regenera, igual que se hizo con `pelos_camino`.
- Se tocan `tracking_cache.py` y el modelo en `db/models/cromo.py:575`.

**`TrackingsDelServicio`**
- Se reemplaza `huerfanos` y `completo` por `tramos`, `residuales`, `esperados_declarados` (Tarea 4) y `completo`. `completo` pasa a significar "no se tocó el tope de llamadas".

**Nombres de archivo**
- `nombre_archivo_tramo` arma `"{at62} CROMO T{n} pelo {n_id}.txt"`.
- Se conserva el sufijo `CROMO`, que el parser de alias no reconoce.
- El orden de tramos es estable, por cantidad de pelos descendente y después por `pelo_n_id`.
- Test en `tests/test_cromo_tracking_nombres.py`.

## Task 3: Slack y web: archivos separados y sin aviso de huérfanos

**`modules/slack_baneo_notifier/tracking_servicio.py`**
- Se suben sólo los `TRAMO`, un `files_upload_v2` por archivo. Eso ya existe en `listener.py:1299`.
- `mensaje_resumen` deja de listar huérfanos. Se borran `_MAX_HUERFANOS_LISTADOS` y `_describir_pelo`.
- Queda una sola línea, y sólo cuando aplica:
  - "Servicio segmentado en N tramos".
  - Si hay cantidad declarada y no coincide: "Se esperaban X trackings y se generaron Y".
  - Si se tocó el tope de llamadas: aviso de incompleto.
- Los residuales no se mencionan en Slack. Van a la auditoría.
- Se actualiza el docstring del módulo.

**`web/app/main.py`, `GET …/camino-optico/caminos` (:8876)**
- El contrato nuevo devuelve `tramos[{n, pelo_n_id, nombre_archivo, extremos, pelos_en_camino}]`, `residuales[...]`, `esperados_declarados` y `completo`.

**Frontend**
- En `useCromoPath.ts` y `CromoCaminoPanel.vue`, cada tramo muestra su etiqueta, por ejemplo "Tramo 1 · ODF X:39 → ODF Nodo KORN O-1259853-1:39", y tiene su propio botón de descarga.
- "Descargar todos" baja un `.txt` por tramo, en serie, como hoy.
- El bloque de huérfanos se reemplaza por un contador de residuales con un enlace a la auditoría.
- `ServicioCaminoView.vue` actualiza la etiqueta del botón.

**Tests:** se reescriben los casos señalados de `tests/test_cromo_tracking_por_camino.py` (:226, :252, :307, :332), `tests/test_slack_track_servicio.py` (:224, :264) y `tests/test_web_cromo_camino_optico.py` (:647-684).

## Task 4: ODF confirmadas y trackings esperados por servicio

**Migración**
- Tabla `app.servicio_odf_confirmada` con `id`, `servicio_id` (FK con CASCADE), `odf_n_id` (referencia blanda), `rol`, `confirmado_por`, `confirmado_en` y `vigente`.
  - `rol` es Text con CHECK: `EXTREMO` o `TRANSITO`.
  - `UNIQUE(servicio_id, odf_n_id)` entre las filas vigentes.
  - Se des-confirma con `vigente=false`, no se borra la fila, para conservar el historial.
- Columna `app.servicios.trackings_esperados SMALLINT NULL`, con CHECK mayor a 0.
- No reemplaza `cromo_servicio_odf_override`, que sigue siendo el escudo de "servicios sin ODF". La tabla nueva admite varias ODF por servicio.

**Servicio `core/services/cromo/servicio_odf_confirmacion.py`**
- `listar`, `confirmar` (en lote, desde las ODF del camino), `desconfirmar` y `declarar_trackings_esperados`.
- Sin ODF confirmadas, todo funciona como hoy.

**Endpoints admin con CSRF** en `web/app/main.py`, junto a los de pelos excluidos (:8946):
- `GET/POST /api/admin/infra/servicios-odf/{id}/odf-confirmadas`.
- `POST …/trackings-esperados`.

**UI** en el Detalle de Servicio, pestaña Camino:
- Lista de las ODF del camino, con extremo o tránsito y un botón "Confirmar". Las confirmadas llevan una marca.
- Un campo para "Trackings esperados".

## Task 5: Auditoría de huérfanos con normalización asistida

**Persistencia**, en una migración:
- `app.cromo_auditoria_huerfanos`: corrida, servicio, pelo, camino semilla, causa sugerida, evidencia JSONB, estado y fecha.
  - `estado` puede ser `PENDIENTE`, `NORMALIZADO` o `DESCARTADO`.
- `cromo_servicio_pelo_excluido` suma `origen` (`MANUAL` o `AUDITORIA`) y `auditoria_id`, para que quede la traza.

**Clasificación de causa** en una función pura con test. Cada señal se mide contra datos reales antes de fijarla:
- **Pelo dañado:** el residual comparte cable con un tramo del mismo servicio, en otro pelo.
- **Cambio de cable por daño:** el residual va en paralelo a un tramo, entre las mismas botellas o empalmes extremos, por un cable distinto.
- **Cable en desuso:** el cable del residual no lleva pelos de ningún servicio activo, o tiene un estado de baja en Cromo. Antes hay que verificar qué campo real lo indica, entre `cromo_pelos.estado_cromo` y el estado del cable.
- **Migración de sitio:** el residual termina en una ODF o botella distinta de las ODF confirmadas o de las de los tramos.
- **Sin clasificar:** cualquier otro caso.
- **Nunca es candidato** un camino con extremo en una ODF o ODF Nodo, ni un camino que toque una ODF confirmada.

**Ejecución**
- Por servicio: se audita al resolver los caminos, reutilizando el resultado de la Tarea 2 sin volver a Cromo.
- Global: un job en `modules/botellas_recalculo_worker` (cola Redis, patrón de `botella_recompute_queue.py`) o una corrida en `cromo_worker`.
  - Se registra como corrida sintética con eventos, con el patrón de `normalizar_inconsistencias` (`normalizacion_consistencia_service.py:353`).
  - El progreso se informa por el WebSocket admin.
  - Se recorren primero los servicios con más pelos, con un tope configurable.

**Normalización**
- Nunca es automática silenciosa. El admin filtra por causa, revisa la evidencia y aplica "Normalizar" en lote.
- Normalizar reusa `pelos_excluidos.excluir_pelos`, con `origen=AUDITORIA` y el motivo igual a la causa.
- Restaurar sigue disponible.
- El primer lote habilitado es "cable en desuso", como pidió el usuario. Las demás causas quedan sólo para revisar hasta validarlas.

**UI:** un Viewer admin `AdminHuerfanosViewer.vue` en `/admin/servicios/viewer/Huerfanos`, siguiendo `AdminServiciosSinOdfViewer.vue`.
- Columnas: servicio, pelo, cable, causa, evidencia y acción.
- Ruta en `src/router/index.ts`, con `requiresAdmin`.

## Task 6: Documentación y cierre

- Se actualizan `docs/slack_app_cables.md`, `docs/infra.md` y `docs/db.md`, con las tablas y columnas nuevas.
- Se actualiza la memoria del proyecto: [[project_track_un_txt_por_camino_2026_09_29]] y la referencia de la clase 86.
- El cierre va con `/cierre-sesion`.

## Verificación

1. **Tests:** `source .venv/bin/activate && LLM_PROVIDER=heuristic pytest tests/test_cromo_ingesta.py tests/test_cromo_parser.py tests/test_cromo_tracking_por_camino.py tests/test_slack_track_servicio.py tests/test_web_cromo_camino_optico.py tests/test_cromo_camino_clases_pon.py tests/test_busqueda_camaras_sin_match.py` más los tests nuevos y la suite completa, verificando el exit code real.
2. **Migraciones:** `alembic upgrade head`, `downgrade -1` y `upgrade` de nuevo en dev.
3. **Ingesta real en dev:** `SOLO_ODF`, después el backfill de conectores. Se consulta `cromo_odfs WHERE clase=86`, con 154 filas esperadas, y los conectores de 9295436.
4. **Tracking real**, con `lasfocasdev-web` y los workers reconstruidos (ver la memoria sobre verificar la imagen del contenedor):
   - Resolver caminos del 102452 desde el portal. Se esperan entre 4 y 6 tramos con su etiqueta de extremos y los residuales enviados a la auditoría.
   - Repetir con 42351, 93154 y 94673 sin regresiones: 2 tramos cada uno.
   - `@sandy02 track 102452` en Slack de dev: un archivo por tramo, sin lista de huérfanos.
5. **Auditoría:** correrla en dev sobre el 102452. Revisar las causas sugeridas con el usuario antes de habilitar la normalización de "cable en desuso".
