# Nombre de archivo: 2026-10-27-p10-spa-capa-api-infratab-viewers.md
# Ubicación de archivo: docs/superpowers/plans/2026-10-27-p10-spa-capa-api-infratab-viewers.md
# Descripción: Plan de implementación de P10 (auditoría 2026-10-24) — capa api/ única, partición de InfraTab.vue y viewers comunes

# P10 — Capa `api/` única, partición de `InfraTab.vue` y viewers comunes — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que todo el HTTP del SPA pase por `src/api/` (CSRF y `ApiError` centralizados), partir `InfraTab.vue` por responsabilidad y extraer la paginación/SSE copiados en los viewers, sin cambio visible.

**Architecture:** Funciones tipadas por dominio en `src/api/*.ts` sobre `request`/`requestJson`/`requestDownload` de `client.ts`; `InfraTab.vue` queda como orquestador de modales hijos que poseen su composable y emiten eventos; `usePaginatedSearch` (estado) + `ViewerShell.vue` (layout y scroll infinito) para los viewers; `useCorridaSse` como único cliente SSE.

**Tech Stack:** Vue 3 `<script setup>` + TypeScript, Vite, `vue-tsc`; pytest (escaneo estático de `src/`).

**Spec:** `/home/support-focal-01/prompts-auditoria-2026-10-24/P10_front_refactor.md`

## Global Constraints

- Worktree: `/home/support-focal-01/LAS-FOCAS-agentes/claude-web-refactor-spa-capa-api-infratab-viewers`, rama `refactor/claude-web-refactor-spa-capa-api-infratab-viewers`. Nada en el checkout de control.
- **No tocar backend.** Si falta un endpoint, se reporta; no se crea.
- Sin dependencias nuevas de npm (no hay runner de tests de front; no se agrega vitest en este frente).
- Prohibido CSRF a mano en componentes: ni `csrf_token: csrf()` en bodies, ni header `X-CSRF-Token` manual, ni `useSession().csrf` para pedidos. El header lo pone `request()` en todo método ≠ GET.
- Archivos nuevos con encabezado de 3 líneas (Nombre de archivo / Ubicación / Descripción).
- Mismas clases CSS y mismo DOM visible en `InfraTab`; colores sólo por tokens (`nocturne-token-compliance`).
- Mensajes de error: `ApiError.message` ya prioriza `error` → `detail` → `message` del payload; no reimplementar esa lectura en componentes.
- Meta (no dogma): ningún componente tocado por encima de ~600 líneas.
- Disco: `df --output=avail -BM /` antes de cada `npm run build`; con < 3 GB, detenerse.
- Verificación por tarea: `cd web/frontend && npm run build` (= `vue-tsc --noEmit` + `vite build`) en verde y `pytest -q tests/test_spa_capa_api.py`.

## Hallazgos reverificados (2026-10-27, `dev` @ 330f621)

| Hallazgo del prompt | Estado real |
|---|---|
| ~35 `fetch` en 13 archivos fuera de `api/` | **33 en 14 archivos** (InfraTab 13, CamaraDetailView 4, resto 1-2) |
| `GET /api/infra/ban/{id}` no existe en `web` | **Confirmado.** Sólo existe en el servicio `api`; el catch-all del SPA responde HTML 200, `res.json()` tira y cae al `catch`: siempre se usa la plantilla local. Además `email_subject/email_body` sólo los escribe `api`, nunca el flujo de `web`. → código muerto |
| `downloadEml` manda `FormData` a un endpoint JSON | **Confirmado.** `EmlDownloadRequestModel` (JSON: `incident_id`, `recipients`, `subject`, `html_body`) → 422 hoy |
| `window.CSRF_TOKEN` sin lectores | **Confirmado** (sólo `client.ts` lo escribe y lo lee como fallback) |
| `reporteRepetitividad` en `ServicioDetalleView` | **Confirmado**: se pide y nunca se muestra |
| `api/cromo.ts` ~892 líneas | **799 líneas**, 7 subdominios por comentario de sección |
| Helpers de presentación en `api/cromoPath.ts` | 8 funciones: `tipoNodoLabel`, `tipoNodoIcono`, `etiquetaExtremo/Tramo/Adicional/Posicion`, `mensajeErrorCromoPath`, `mensajeErrorPosicionVigente` |
| 6 viewers con `LIMIT = 30` | `LIMIT` real: Botellas 30, Servicios 30, Cámaras 60, SinOdf 60, Huérfanos 100, Inconsistencias 100. Huérfanos e Inconsistencias **no** usan `IntersectionObserver` |
| SSE duplicado en Huérfanos e Ingesta Cromo | **Confirmado.** `streamUrlAuditoria`, `streamUrlIngestaCromo` y `streamUrlCorrida` son la misma URL. Ingesta Cromo además escucha `fase` y **no** reconecta con backoff |
| Uploads con `XMLHttpRequest` (camaras, servicios, clientesCategoria) | Ya en `api/`, ya ponen `CSRF_HEADER`. Se quedan (necesitan progreso de subida) |
| Build base | `npm ci` + `npm run build` en verde (sólo el aviso preexistente de chunk > 500 kB) |

## Review Focus

1. **Tipear mientras carga una página** (viewers): hoy `reloadFromZero` durante una carga se pierde por el `if (loading) return` y queda la página de la consulta vieja. Esperado: el resultado final corresponde a la última consulta → `usePaginatedSearch` descarta respuestas de una generación anterior (Task 7).
2. **Error de backend con payload JSON en descargas** (`.eml`, tracking, export de Cámaras): esperado el toast con el `error`/`detail` del backend, no "Error 422" mudo ni un archivo con el JSON adentro → `requestDownload` ya lo cubre; las tareas sólo deben usarlo, no reimplementarlo (Task 4).
3. **Sesión vencida a mitad de un flujo** (baneo, aviso): esperado el mismo mensaje de error en el toast que hoy, sin excepción no capturada → cada `catch` sigue mostrando `e.message` (Tasks 4-5).
4. **Caída del SSE de Ingesta Cromo**: hoy el navegador reintenta solo sin `?desde=`; al pasar a `useCorridaSse` reanuda con backoff y no duplica eventos. Esperado: el progreso no salta ni retrocede (Task 9).
5. **Cerrar un modal hijo de `InfraTab` con Escape o clic afuera durante un envío**: esperado el mismo bloqueo que hoy (`force` sólo desde el propio envío) → se conserva la firma `cerrar(force = false)` en cada modal (Task 5).

---

## Task 1: Guardia estática de la capa `api/` y del CSRF

**Files:**
- Create: `tests/test_spa_capa_api.py`

**Interfaces:**
- Produces: `PENDIENTES_FETCH: set[str]` (rutas relativas a `web/frontend/src`) que cada tarea vacía a medida que migra; la Task 10 lo deja vacío.

- [ ] **Step 1: Escribir los tests**

Escaneo de texto sobre `web/frontend/src/**/*.{ts,vue}` (sin backend):
- `test_fetch_solo_en_capa_api`: los archivos con `fetch(` fuera de `src/api/` ⊆ `PENDIENTES_FETCH`.
- `test_pendientes_siguen_pendientes`: cada entrada de `PENDIENTES_FETCH` todavía contiene `fetch(` (obliga a sacarla al migrar; el set sólo se achica).
- `test_sin_csrf_a_mano_fuera_de_api`: fuera de `src/api/` ningún archivo contiene `csrf_token`, `X-CSRF-Token` ni `csrf()`; excepciones: archivos de `PENDIENTES_FETCH` (se limpian en la misma tarea que su `fetch`).
- `test_transportes_crudos_solo_en_api_o_composables`: `XMLHttpRequest` sólo en `src/api/`; `new EventSource` sólo en `src/composables/` + los archivos de `PENDIENTES_SSE = {"admin/views/AdminHuerfanosViewer.vue", "admin/views/AdminIngestaCromo.vue"}`.
- `test_xhr_mutante_lleva_header_csrf`: todo archivo de `src/api/` con `xhr.open('POST'|'PUT'|'PATCH'|'DELETE'` contiene `setRequestHeader(CSRF_HEADER`.

`PENDIENTES_FETCH` inicial = los 14 archivos del inventario de la sección de hallazgos.

- [ ] **Step 2: Correr y ver verde** — `pytest -q tests/test_spa_capa_api.py` → 5 passed. Romper a propósito (agregar un `fetch(` en un `.vue` fuera del set en una copia temporal) para confirmar que falla y revertir.
- [ ] **Step 3: Commit** — `test(spa): guardia estática de fetch, CSRF y transportes fuera de api/ (P10)`

## Task 2: Limpiezas decididas por el usuario

**Files:**
- Modify: `web/frontend/src/api/client.ts` (quitar `legacyWindow`, `syncLegacyCsrfToken`; `getCsrfToken()` devuelve `csrfToken ?? ''`)
- Modify: `web/frontend/src/views/ServicioDetalleView.vue:286,601,606,610` (quitar `reporteRepetitividad` y su pedido; `loadReportesResumen` pide sólo SLA)

- [ ] **Step 1:** `grep -rn "CSRF_TOKEN\|reporteRepetitividad" web/frontend/src` antes → sólo los usos listados.
- [ ] **Step 2:** Aplicar los cambios; el mismo grep → 0.
- [ ] **Step 3:** `npm run build` verde. Commit `refactor(spa): quitar window.CSRF_TOKEN y el pedido de repetitividad sin uso (P10)`.

## Task 3: Migrar los `fetch` fuera de `InfraTab` a `src/api/`

**Files (nuevos y modificados en `web/frontend/src`):**
- Modify `api/camaras.ts`: `buscarCamaras(params: URLSearchParams): Promise<…>` (la usan **tres** modales hoy duplicados: `ModalUnificarCamara`, `ModalAsociarHuerfanas`, `admin/components/ModalAsociarSinMatch`), `unificarCamaras(body)`, `fusionarGrupoCamaras(body)`, `obtenerEstadoCamara(id)`, `cambiarEstadoCamara(id, estado: string, motivo: string)`, `obtenerCamara(id)`, `obtenerAliasesCamara(id)`, `obtenerRegistrosCamara(id, qs: string)`, `obtenerBotellasCamara(id)`.
- Modify `api/botellas.ts`: `listarBotellasHuerfanas(params: URLSearchParams)`, `obtenerEstadoAsociacionBotella(nId: number)`, `asociarBotellasHuerfanas(body)`.
- Create `api/infra.ts`: por ahora sólo `obtenerTrackingRuta(rutaId: number)` (de `composables/useTracking.ts:41`); la Task 4 lo completa.
- Create `api/informes.ts`: `listarHistorialInformes(query: string)`, `generarRepetitividad(data: FormData)`; mover acá `getUltimoReporte` y `ReportsHistoryResponse`/`ReportHistoryItem` desde `api/servicioSecciones.ts` y actualizar sus importadores.
- Create `api/herramientas.ts`: `compararVlans(textA: string, textB: string)`.
- Create `api/chat.ts`: `subirAdjuntoChat(file: File): Promise<{ name: string; path: string; size: number }>` (`formData`), `enviarMensajeChat(text: string): Promise<{ reply?: string }>` (body `URLSearchParams`, `Accept: application/json`; se mantiene urlencoded).
- Modify los 13 consumidores (todos los de `PENDIENTES_FETCH` salvo `views/tabs/InfraTab.vue`): llamar a las funciones nuevas, borrar `useSession().csrf` y los `csrf_token` del body.
- Modify `tests/test_spa_capa_api.py`: sacar esos 13 archivos de `PENDIENTES_FETCH`.

**Interfaces:**
- Produces: los nombres de arriba. Tipos de respuesta: los que hoy declara cada componente (`as {…}`), movidos al módulo `api/` como `export interface`.

- [ ] **Step 1:** Por cada archivo, leer el `fetch` y su manejo de error; la función nueva usa `requestJson` (o `request` si el componente lee `res.status`). Si el componente distinguía un status puntual (p. ej. 404), conservarlo vía `ApiError.status`.
- [ ] **Step 2:** Sacar los 13 archivos del set; `pytest -q tests/test_spa_capa_api.py` verde.
- [ ] **Step 3:** `grep -rn "csrf" web/frontend/src --include=*.vue` → sólo `InfraTab.vue` y `LoginView.vue` (este último guarda el token de login: legítimo).
- [ ] **Step 4:** `npm run build` verde. Commits por grupo (cámaras/botellas; informes/herramientas/chat; tracking).

## Task 4: `api/infra.ts` completo y `InfraTab` sin `fetch` (incluye los 2 bugs)

**Files:**
- Modify `web/frontend/src/api/infra.ts`: `smartSearch(body)`, `rutasDeServicio(servicioId: string)`, `descargarTrackingRuta(rutaId: number): Promise<string>` (`requestDownload`), `baneosActivos()`, `levantarBaneo(body)`, `crearBaneo(body)`, `notificarBaneoEmail(body)`, `descargarEmlBaneo(body: { incident_id: number; recipients: string; subject: string; html_body: string }): Promise<string>` (`requestDownload` con `json`, `fallbackFilename: aviso_baneo_<id>.eml`), `analizarTracking(data: FormData)`, `resolverTracking(body)`, `limpiarEmpalmesServicio(servicioId: string)` (DELETE), `exportarCamaras(params: URLSearchParams): Promise<string>` (`requestDownload`). Tipos (`IncidenteActivo`, `AnalyzeResult`, `BanRutaOption`, …) se mueven acá desde `InfraTab.vue`.
- Modify `web/frontend/src/views/tabs/InfraTab.vue`: usar esas funciones; quitar `useSession`.
- Modify `tests/test_spa_capa_api.py`: `PENDIENTES_FETCH` queda vacío.

- [ ] **Step 1 (bug 1):** borrar el `fetch('/api/infra/ban/${inc.id}')` de `openAvisoModal`: el resultado visible no cambia (hoy siempre cae a la plantilla local). Reportar en el PR diario que la plantilla guardada sólo existe en el servicio `api`.
- [ ] **Step 2 (bug 2):** `downloadEml` arma el JSON del modelo: `recipients: toList.join(', ')` (string vacío si no hay), `subject` y `html_body` con `trim()`.
- [ ] **Step 3:** reemplazar el resto de `fetch` y los tres blob+anchor inline por `requestDownload`.
- [ ] **Step 4:** `useSession().csrf` queda sin consumidores: quitarlo del `return` de `composables/useSession.ts` (el estado `csrf` se conserva: lo usa `setCsrfToken`). `pytest -q tests/test_spa_capa_api.py` verde con el set vacío; `npm run build` verde.
- [ ] **Step 5:** Commits: `fix(spa): descarga del .eml de baneo con el JSON que espera el endpoint (P10)` y `refactor(spa): InfraTab usa api/infra.ts (P10)`.

## Task 5: Partir `InfraTab.vue`

Mapa de la partición (template actual: modales en `:31-476`, contenido principal `:478-632`; script `:640-1525`; estilos `:1527-1889`):

| Destino | Origen en `InfraTab.vue` | Responsabilidad |
|---|---|---|
| `composables/infra/useInfraBusqueda.ts` | script `:664-846` | términos, smart-search, paginación, filtro por estado, leyenda, no operativas |
| `composables/infra/useBaneoWizard.ts` + `components/infra/infratab/BaneoWizardModal.vue` | template `:31-199`, script `:850-995`, `:1237-1295` | wizard 3 pasos, rutas, descarga de tracking, alta del baneo |
| `composables/infra/useBaneosActivos.ts` + `components/infra/infratab/BaneosActivosModal.vue` | template `:339-411`, script `:999-1117` | lista, levantar baneo, abre el aviso |
| `composables/infra/useNotificacionEmail.ts` + `components/infra/infratab/AvisoEmailModal.vue` | template `:413-455`, script `:1004-1068`, `:1118-1235` | plantilla local, envío, `.eml`, destinatarios guardados |
| `composables/infra/useTrackingAnalisis.ts` + `components/infra/infratab/TrackingResolveModal.vue` | template `:201-337`, script `:1297-1444` | archivo/drag&drop, analizar, resolver |
| `components/infra/infratab/LimpiarServicioModal.vue` | template `:457-476`, script `:1446-1480` | limpiar empalmes |
| `InfraTab.vue` (orquestador) | resto | toasts, búsqueda y resultados, menú de descarga, apertura de modales |

**Interfaces:**
- `type Notificar = (tipo: 'success' | 'error' | 'warning' | 'info', titulo: string, mensaje?: string) => void` en `composables/infra/tipos.ts`. Cada modal recibe la prop `notificar: Notificar`.
- Cada modal: `defineExpose({ abrir })` y `cerrar(force = false)` interno con la misma regla de hoy. Eventos: `BaneoWizardModal` emite `baneo-creado`; `BaneosActivosModal` emite `baneo-levantado` y abre `AvisoEmailModal` (hijo suyo); `TrackingResolveModal` emite `tracking-resuelto`; `LimpiarServicioModal` emite `servicio-limpiado`. `InfraTab` re-ejecuta la búsqueda en cada uno sólo si `hasSearched` (comportamiento actual).
- El input oculto de archivo y el drag&drop se quedan donde están en el DOM; `useTrackingAnalisis` expone `elegirArchivo()`, `onDrop(e)`, etc.
- CSS: las reglas compartidas `.infra-generic-modal*` van a `components/infra/infratab/infra-modal.css` y cada modal la importa con `<style scoped src="./infra-modal.css">`; las reglas propias de cada modal se mudan con él, mismos selectores. `InfraTab` conserva las del contenido principal.

- [ ] **Step 1:** Extraer composables uno por uno (empezar por `useInfraBusqueda`); `npm run build` verde tras cada uno.
- [ ] **Step 2:** Extraer cada modal con su CSS; `npm run build` verde tras cada uno.
- [ ] **Step 3:** Diff de DOM: `vite build` de antes y después y comparar el conjunto de clases usadas: `grep -oh 'class="[^"]*"' ` sobre los `.vue` de origen y destino → mismo conjunto (más/menos sólo nombres de componente).
- [ ] **Step 4:** `wc -l` de `InfraTab.vue` y de cada archivo nuevo ≤ ~600; `nocturne-token-compliance` sobre los archivos nuevos → sin hex/rgba literales nuevos.
- [ ] **Step 5:** Commit por extracción (`refactor(spa): extraer <X> de InfraTab (P10)`).

## Task 6: Cohesión de la capa `api/` de Cromo

**Files:**
- Create en `web/frontend/src/api/`: `cromoIngesta.ts` (corridas, modos, catálogo, histórico, detalle; `cromo.ts:7-195`), `cromoScheduler.ts` (`:197-259`), `cromoVerificacion.ts` (verificadores por cable/tubo/botella/ODF; `:261-328`, `:784-799`), `cromoInventario.ts` (cables, ODF, PON; `:330-376`, `:646-743`), `cromoDetalle.ts` (detalle de cable y de ODF, empalmes, conectores, visor en vivo, validación, cables detectados; `:378-644`, `:745-782`).
- Modify `api/cromo.ts` → sólo `export * from './cromoX'` de los cinco (los 12 importadores no cambian).
- Create `web/frontend/src/utils/cromoPathPresentacion.ts` con las 8 funciones de presentación de `api/cromoPath.ts`; actualizar sus 6 importadores (`components/infra/Cromo*.vue`, `ModalAsociarOdf.vue`, `composables/useCromoPath.ts`). `api/cromoPath.ts` no las re-exporta (una capa `api` no depende de `utils`).

- [ ] **Step 1:** Mover sin cambiar cuerpos; `npm run build` verde.
- [ ] **Step 2:** `wc -l api/cromo*.ts` → ninguno > ~300; `grep -n "export function etiqueta\|tipoNodo\|mensajeError" api/cromoPath.ts` → 0.
- [ ] **Step 3:** Commit `refactor(spa): partir api/cromo.ts por subdominio y sacar presentación de cromoPath (P10)`.

## Task 7: `usePaginatedSearch` + `ViewerShell` y migración del **primer** viewer

**Files:**
- Create `web/frontend/src/composables/usePaginatedSearch.ts`
- Create `web/frontend/src/components/viewer/ViewerShell.vue`
- Modify `web/frontend/src/admin/views/AdminServiciosSinOdfViewer.vue` (el más chico, 427 líneas, con scroll infinito)

**Interfaces:**
```ts
export interface PaginaViewer<T> { items: T[]; total: number }
export interface OpcionesPaginatedSearch<T, R extends PaginaViewer<T>> {
  limit: number;
  cargarPagina: (offset: number, limit: number) => Promise<R>;
  claveItem: (item: T) => string | number;   // dedupe al mergear (mergeItems de hoy)
  alRecibir?: (respuesta: R) => void;         // p. ej. conteos de chips
  mensajeError: string;
  debounceMs?: number;                        // default 320
}
export function usePaginatedSearch<T, R extends PaginaViewer<T>>(o: OpcionesPaginatedSearch<T, R>): {
  items: Ref<T[]>; total: Ref<number>; loading: Ref<boolean>; error: Ref<string>; hasMore: Ref<boolean>;
  cargarSiguiente(): Promise<void>; recargarDesdeCero(): Promise<void>; recargarConDebounce(): void;
}
```
- `hasMore = items.length === limit && offset < total` (la regla actual). Contador de generación: `recargarDesdeCero` incrementa la generación y una respuesta de generación vieja se descarta (Review Focus 1). `onBeforeUnmount` limpia el timer.
- `ViewerShell.vue` — props `{ bloque: string; loading: boolean; error: string; vacio: boolean; hayMas: boolean; textoVacio: string; textoCargando: string; scrollInfinito?: boolean /* default true */ }`, emite `cargar-mas` cuando el sentinel entra en vista (el `IntersectionObserver` vive en el shell, con root = su contenedor de scroll; mismo `rootMargin` que hoy). Slots: `toolbar`, `default` (grilla), `vacio` (opcional). La raíz lleva las clases `viewer-shell` y `bloque` (la del viewer). Las reglas que el diff del Step 1 muestre **idénticas** en los 6 viewers pasan al shell como `viewer-shell__toolbar`, `__state-box`, `__spin`, `__scroll`, `__loading-more`, `__sentinel`, `__inline-error`, etc.; las que difieren quedan en el viewer colgadas de su `bloque`. Resultado visual idéntico; registrar la tabla del diff en el commit.

- [ ] **Step 1:** `diff` de los bloques de estilo `__toolbar|__state-box|__spin|__scroll|__loading-more|__count|__chip|__search|__sentinel|__grid` entre los 6 viewers → tabla de reglas idénticas vs. distintas.
- [ ] **Step 2:** Implementar composable y shell; migrar `AdminServiciosSinOdfViewer`; `npm run build` verde.
- [ ] **Step 3:** Commit `refactor(spa): usePaginatedSearch y ViewerShell; migrar Servicios sin ODF (P10)`.
- [ ] **Step 4: DETENERSE Y PREGUNTAR** (lo pide el spec): mostrar al usuario el diff del viewer y pedirle que lo pruebe logueado antes de seguir. Para que pueda verlo hace falta desplegar el SPA en el stack dev compartido (lease `env:docker-compose`, rebuild de `web`) — preguntar si lo autoriza o si prefiere seguir y probar todo al final.

## Task 8: Migrar los otros 5 viewers

**Files:** `admin/views/AdminBotellasViewer.vue`, `AdminCamarasViewer.vue`, `AdminHuerfanosViewer.vue`, `AdminInconsistenciasCromoViewer.vue`, `views/ServiciosView.vue`.

- Cada uno conserva su `LIMIT` (30/60/100) y sus filtros/acciones masivas; Huérfanos e Inconsistencias usan `ViewerShell` con `scrollInfinito: false` (hoy no tienen observer) o sólo el composable si su layout no encaja — justificarlo en el commit.

- [ ] **Step 1:** Un viewer por commit; `npm run build` verde tras cada uno.
- [ ] **Step 2:** `grep -rn "IntersectionObserver\|setTimeout(.*320\|reloadFromZero" web/frontend/src/admin/views web/frontend/src/views` → 0 (salvo `ViewerShell`/composable).
- [ ] **Step 3:** `wc -l` de los 6 viewers: reportar antes/después.

## Task 9: SSE único vía `useCorridaSse`

**Files:**
- Modify `web/frontend/src/composables/useCorridaSse.ts`: agregar `onFase?: (data: Record<string, unknown>) => void` y `onErrorDatos?: (data: Record<string, unknown>) => void` (se llama con el JSON del evento de negocio `error`, además de `onErrorNegocio`).
- Modify `admin/views/AdminHuerfanosViewer.vue` (`:425-510`) y `admin/views/AdminIngestaCromo.vue` (`:426-470`): usar `useCorridaSse`; Ingesta Cromo gana reconexión con backoff y `?desde=` (su `recargarEstado` = la función que hoy relee la corrida).
- Delete `streamUrlAuditoria` (`api/huerfanos.ts:168`) y `streamUrlIngestaCromo` (`api/cromoIngesta.ts`) si quedan sin uso.
- Modify `tests/test_spa_capa_api.py`: `PENDIENTES_SSE` vacío.

- [ ] **Step 1:** Migrar Huérfanos (mismos callbacks que hoy) → build verde → commit.
- [ ] **Step 2:** Migrar Ingesta Cromo → build verde → commit.
- [ ] **Step 3:** `pytest -q tests/test_spa_capa_api.py` verde; `grep -rn "new EventSource" web/frontend/src` → sólo `useCorridaSse.ts`.

## Task 10: Cierre técnico, docs y checklist

**Files:**
- Modify `tests/test_spa_capa_api.py`: quitar los sets `PENDIENTES_*` (ya vacíos) y el test que los recorre.
- Modify `.agentes-comunes/skills/frontend-spa-architecture/SKILL.md` (lease `skill:frontend-spa-architecture`, luego `scripts/sync_agentes_comunes.sh` y `scripts/check_skill_mirror_drift.sh`): regla "todo HTTP en `src/api/`, guardado por `tests/test_spa_capa_api.py`", `usePaginatedSearch`/`ViewerShell` y `useCorridaSse` como únicos patrones.
- Create/Modify `docs/PR/2026-10-27.md` (o la fecha del día) con la sección P10: módulos `api/` nuevos/partidos, mapa de `InfraTab`, viewers, bugs, `GET /api/infra/ban/{id}` reportado.

- [ ] **Step 1:** `grep -rn "fetch(" web/frontend/src --include=*.vue --include=*.ts | grep -v "src/api/"` → 0.
- [ ] **Step 2:** `npm run build` verde; `pytest -q tests/test_spa_capa_api.py tests/test_web_csrf.py` verde.
- [ ] **Step 3:** Grafo de imports: todo `.ts/.vue` de `src/` alcanzable desde `src/main.ts` (mismo chequeo que P09).
- [ ] **Step 4:** `wc -l` de todo componente tocado; listar los > 600 con motivo.
- [ ] **Step 5:** Checklist de pruebas logueadas para el usuario: Infra (buscar, smart-search, filtros por estado, paginar, baneo completo de 3 pasos con descarga de tracking, baneos activos, levantar, aviso por email, descargar `.eml` — **antes daba error**, analizar y resolver tracking por cada estado, limpiar servicio, exportar xlsx/csv), los 6 viewers (buscar tipeando rápido, chips/filtros, scroll infinito o "cargar más", acciones masivas), Ingesta Cromo (progreso SSE, fases, errores; cortar la red un momento y ver que retoma), Huérfanos (auditoría en vivo), chat (adjunto y mensaje), Cámara detalle (estado, alias, registros, botellas), modales de unificar/fusionar/asociar, VLAN, Repetitividad, historial de informes.
- [ ] **Step 6:** Commit y push a la rama efímera. Integración a `dev` sólo con `/cierre-sesion`.
