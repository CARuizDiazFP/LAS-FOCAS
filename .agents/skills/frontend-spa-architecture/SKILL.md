---
name: frontend-spa-architecture
description: "Usar SIEMPRE antes de agregar, modificar o mover rutas, vistas o componentes en el frontend SPA de LAS-FOCAS. Valida el entry point activo, el router unificado y advierte sobre archivos huérfanos conocidos."
argument-hint: "Tarea frontend a realizar, por ejemplo: agregar ruta /admin/mi-modulo o crear vista AdminMiVista.vue"
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agents/skills/frontend-spa-architecture/SKILL.md
# Descripción: Skill para verificar la arquitectura SPA unificada antes de agregar rutas, vistas o componentes en el frontend de LAS-FOCAS (mirror Agent Skills de .agentes-comunes/skills/frontend-spa-architecture/SKILL.md — fuente de verdad)

# Habilidad: Frontend SPA Architecture — Verificación de Arquitectura Antes de Tocar el Router

Protocolo de orientación para que cualquier agente que trabaje en el frontend de LAS-FOCAS
entienda la topología real del SPA antes de escribir código.

## Cuándo usar

Invocar esta skill **siempre** que el agente vaya a:

- Agregar una ruta nueva (panel, admin, o cualquier otra sección)
- Crear una vista nueva que necesite navegación
- Mover o renombrar componentes que el router importa
- Modificar guards de navegación o meta de rutas
- Trabajar con el directorio `src/admin/` o `src/views/`

---

## Arquitectura del SPA — Hechos Verificados

### Entry point único

```
web/frontend/index.html
  └── <script src="/src/main.ts">   ← ÚNICO entry point de Vite
        └── createApp(App).use(router).mount('#app')
              └── router: web/frontend/src/router/index.ts  ← ROUTER ACTIVO
```

Vite tiene un único `input` (`index.html`), por lo que **solo hay una instancia de Vue en runtime**.

### Router activo

**`web/frontend/src/router/index.ts`** — router unificado que contiene:

| Ruta base | Componente envoltorio | Sección |
|---|---|---|
| `/login` | `LoginView` | Pública |
| `/` | `AppShell` (children: panel, infra, servicios, sla, etc.) | Panel operativo |
| `/admin` | `AppShell` (children: dashboard, usuarios, servicios, ingesta, baneos) | Administración |

Módulos admin actuales bajo `/admin`:

| path (relativo a /admin) | Componente |
|---|---|
| `` (vacío) | `AdminDashboard` |
| `usuarios` | `AdminUsuarios` |
| `servicios` | `AdminServicios` |
| `Servicios/Baneos` | `AdminBaneos` |
| `ingesta` | `AdminIngesta` (hub de navegación) |
| `ingesta/servicios` | `AdminIngestaServicios` |
| `ingesta/camaras` | `AdminIngestaCamaras` |
| `:pathMatch(.*)*` | redirect `/admin` — **CATCH-ALL, debe ser la última** |

### Huérfanos históricos (ya eliminados)

`web/frontend/src/admin/router/index.ts` y `web/frontend/src/admin/main.ts` eran un router y un
entry point sin conectar. Se eliminaron en `9bb86f6` (2026-08-05). `src/admin/` sigue existiendo, pero
sólo con vistas, componentes y API client que importa el router unificado.

`src/chat/main.ts` (cliente DOM viejo del chat, reemplazado por `views/tabs/ChatTab.vue`) también se
eliminó el 2026-10-26 (frente P09 de la auditoría). Verificado ese día: los 134 `.ts`/`.vue`/`.css`
de `src/` son alcanzables desde `src/main.ts`.

> **Si reaparece un router o un `main.ts` bajo `src/admin/`, no tiene efecto en runtime.** El único
> router es `src/router/index.ts` y el único entry point es `src/main.ts`.

---

## Procedimiento de verificación (antes de escribir código)

### 1. Confirmar el entry point activo

```bash
grep -n "src/main" web/frontend/index.html
```

Debe devolver exactamente una línea apuntando a `src/main.ts`.

### 2. Confirmar el router activo

```bash
grep -n "from.*router" web/frontend/src/main.ts
```

Debe importar `./router/index` (el router unificado).

### 3. Verificar que la ruta nueva no colisiona con el catch-all

El catch-all `{ path: ':pathMatch(.*)*', redirect: '/admin' }` debe ser siempre el **último elemento** del array `children` de `/admin`. Al agregar una ruta nueva, insertarla antes de ese elemento.

---

## Patrón para agregar una ruta admin nueva

### 1. Agregar el import en `src/router/index.ts`

```typescript
const AdminMiVista = () => import('../admin/views/AdminMiVista.vue');
```

### 2. Agregar la ruta como `children` de `/admin`, antes del catch-all

```typescript
{
  path: '/admin',
  component: AppShell,
  meta: { requiresAuth: true, requiresAdmin: true },
  children: [
    // ... rutas existentes ...
    {
      path: 'mi-modulo',            // relativo a /admin → resulta en /admin/mi-modulo
      name: 'admin-mi-modulo',
      component: AdminMiVista,
      meta: { requiresAdmin: true },
    },
    { path: ':pathMatch(.*)*', redirect: '/admin' },  // catch-all SIEMPRE AL FINAL
  ],
},
```

### 3. Guard de navegación

El `router.beforeEach` en `src/router/index.ts` usa `useSession()` de `src/composables/useSession.ts`:
- Verifica `state.value.authenticated` — si no, redirige a `/login`.
- Verifica `state.value.role === 'admin'` para rutas con `meta.requiresAdmin` — si no, redirige a `/`.

No hay guard separado; toda lógica de sesión vive en `src/router/index.ts`.

---

## Patrón para agregar una ruta del panel (no admin)

Agregar como `children` de la ruta raíz `{ path: '/', component: AppShell }`:

```typescript
{
  path: 'mi-seccion',               // relativo a / → resulta en /mi-seccion
  name: 'mi-seccion',
  component: () => import('../views/MiVista.vue'),
  meta: { requiresAuth: true },     // requiresAdmin: true para rutas de admin
},
```

**El router sólo lee `meta.requiresAuth` y `meta.requiresAdmin`** (`router.beforeEach` en
`src/router/index.ts`). Las claves `navLabel`, `navDescription`, `navOrder` y `navSection` no las leía
nadie y se eliminaron del router el 2026-10-26 (56 apariciones, decisión del usuario en el frente
P09). No volver a agregarlas: no tienen efecto.

**El menú lateral se edita a mano** en `src/components/app-shell/AppShell.vue`: `primaryLinks`
(`SidebarItem`: `id`, `label`, `icon`, `to`) y los módulos desplegables (`SidebarModule`:
`infraFo`, `reportes`, `dwdmCiena`, `toolKit`). Una vista nueva que deba verse en el menú necesita
la ruta en el router **y** el ítem en `AppShell.vue`.

---

## Capa API, viewers paginados y SSE — Hechos Verificados (P10, 2026-10-28)

- **Todo HTTP va en `src/api/` (o `src/admin/api/`)**, un módulo por dominio, y lo vigila
  `tests/test_spa_capa_api.py`: falla ante `fetch(`, CSRF armado a mano (`csrf_token`, `X-CSRF-Token`,
  `csrf()`), `XMLHttpRequest` fuera de `api/`, `new EventSource` fuera de `composables/` y `fetch(` en
  cualquier archivo que no sea `api/client.ts`. `test_cliente_http_solo_desde_capa_api` además impide que
  fuera de `api/` se importen `request`, `requestJson` o `requestDownload` de `client` (sí se permiten
  `ApiError`, `saveBlob`, `setCsrfToken`/`clearCsrfToken` y tipos). Los componentes y composables sólo
  llaman funciones tipadas de `api/`: el invariante se cumple en todo el SPA, sin excepciones.
- **El CSRF lo pone `request()`** (`api/client.ts`) en todo método ≠ GET. No mandar `csrf_token` en el
  body ni leerlo de `useSession()`. Errores: `ApiError` (mensaje de `error`, `detail`, `message`, o `Error N`).
- **Descargas**: `requestDownload` descarga, guarda el archivo con `saveBlob` y devuelve el nombre usado (el del header `Content-Disposition` o el de respaldo); nunca `fetch` + `blob()` a mano.
- **Viewers paginados**: `composables/usePaginatedSearch.ts` + `components/viewer/ViewerShell.vue`.
  Props clave del shell: `anchoEstado` (`max-width` de la caja de estado), `errorInline` (`false` si el
  viewer pinta su propia caja de error), `scrollInfinito` (`false` si usa botón "Cargar más").
  **Trampa**: pasar siempre en `error` el error real, aunque `errorInline` sea `false`; con `error=""` la
  guarda de re-medición del sentinel se cumple tras un fallo y `cargar-mas` se emite en bucle (ServiciosView, P10).
  Fuera del patrón queda `BotellasInventarioView` (paginación propia, pendiente).
- **SSE de corridas**: `composables/useCorridaSse.ts` es el único cliente (reconexión con backoff, `?desde=`,
  eventos repetidos ignorados por id, cierre en `onBeforeUnmount`). No crear `EventSource` nuevos.
- **Helpers de presentación** (etiquetas, íconos, mensajes de error) van en `src/utils/`; `api/` no
  depende de `utils/` (`utils/` puede importar de `api/`).
- **Vistas grandes**: `InfraTab` se partió en `composables/infra/` + `components/infra/infratab/`; seguir
  ese patrón (orquestador + composables + modales con `defineExpose({ abrir })`) antes de pasar ~600 líneas.

---

## Guardrails

1. **No crear** un segundo router (p. ej. `src/admin/router/index.ts`): las rutas van en `src/router/index.ts`.
2. **No crear** `src/admin/main.ts` como entry point alternativo sin actualizar `index.html` y `vite.config.ts`.
3. **No importar** un router que no sea `src/router/index.ts` desde ningún componente.
4. **Siempre** colocar el catch-all `':pathMatch(.*)*'` como último elemento de los `children` de `/admin`.
5. **Siempre** usar lazy imports (`() => import(...)`) para componentes de ruta en el router unificado.
6. **Librerías con Web Worker resuelto en runtime (MapLibre GL ≥ 6, y cualquiera que haga
   `new URL('./x-worker.mjs', import.meta.url)` con el nombre calculado): Vite no emite el worker** y
   la librería falla en silencio (MapLibre: el mapa nunca dispara `load`; sólo se ve el header del
   PMTiles en los logs, ni teselas ni glyphs). Importarlo explícito con
   `import workerUrl from '<pkg>/dist/<worker>.mjs?worker&url'`, registrarlo (`maplibregl.setWorkerUrl`)
   antes de crear la instancia, y `worker: { format: 'es' }` en `vite.config.ts`. Verificar que
   `dist/assets/` contenga el `*-worker-*.js`. MapLibre 6 tampoco tiene export default (`import * as
   maplibregl`) y sus tipos (`kdbush`) requieren TS ≥ 5.7 → `skipLibCheck: true` con TS 5.5.
   Hallazgo real (2026-10-14, `FoMonitorMap.vue`, ver `docs/cierres/2026-10-17.md`).
7. **No agregar `fetch`, CSRF manual ni `EventSource` fuera de la capa api/composables** (ver sección
   anterior): `tests/test_spa_capa_api.py` lo rechaza y no hay lista de excepciones.
8. **Build desde un worktree: `npm ci` adentro, no el `node_modules` del control.** El
   `node_modules` del checkout de control no tiene `maplibre-gl`, `pmtiles` ni `@protomaps/basemaps`
   (FO Monitor), así que enlazarlo hace fallar `vue-tsc` (la auditoría del 2026-10-24 midió 27 errores ajenos) y
   `vite build`. Desde el
   2026-10-26 la vía es `npm ci --no-audit --no-fund` dentro de `web/frontend/` del worktree: unos
   3 s, instala el lockfile completo y queda excluido de git (`info/exclude`). Desde ese día
   `npm run build` es `vue-tsc --noEmit && vite build`, así que un solo comando verifica tipos y
   plantillas. El aviso de `agent_worktree.py start` ("enlazar desde el control") es anterior.
   El `vite.config` temporal que externalizaba MapLibre (2026-10-19) ya no hace falta.

## Relación con otras skills

- `dev-workflow`: ejecutar antes de hacer commits con los cambios de rutas.
- `frontend-specs`: reglas de componentes Vue 3 y TypeScript.
