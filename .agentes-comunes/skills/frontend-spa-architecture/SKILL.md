# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agentes-comunes/skills/frontend-spa-architecture/SKILL.md
# Descripción: Skill para verificar la arquitectura SPA unificada antes de agregar rutas, vistas o componentes en el frontend de LAS-FOCAS

---
name: frontend-spa-architecture
description: "Usar SIEMPRE antes de agregar, modificar o mover rutas, vistas o componentes en el frontend SPA de LAS-FOCAS. Valida el entry point activo, el router unificado y advierte sobre archivos huérfanos conocidos."
argument-hint: "Tarea frontend a realizar, por ejemplo: agregar ruta /admin/mi-modulo o crear vista AdminMiVista.vue"
---

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
entry point sin conectar. Se eliminaron en `9bb86f6` (2026-08-05); verificado otra vez el
2026-10-20: ningún `.vue`/`.ts` de `src/` queda sin importar. `src/admin/` sigue existiendo, pero
sólo con vistas, componentes y API client que importa el router unificado.

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
  component: MiVista,
  meta: {
    requiresAuth: true,
    navLabel: 'Mi Sección',
    navDescription: 'Descripción para el sidebar.',
    navOrder: 50,
    navSection: 'Operación',
  },
},
```

Si el módulo necesita aparecer en la navegación lateral, `navLabel`, `navOrder` y `navSection` son requeridos.

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
7. **Build desde un worktree con `node_modules` enlazado del checkout de control**: el
   `node_modules` del control no tiene `maplibre-gl` ni `@protomaps/basemaps` (dependencias de FO
   Monitor), así que `vite build` falla por algo ajeno a la tarea. Para verificar una tarea de UI sin
   tocar ese `node_modules`, usar un `vite.config` temporal **fuera del repo** que externalice
   `maplibre-gl`, `@protomaps/basemaps` y `pmtiles`, con `--outDir` en `/tmp`; nunca comitear el
   symlink ni el config temporal. La imagen Docker de `web` sí instala todo (build real ahí). Real
   2026-10-19 (pestañas del árbitro, ver `docs/cierres/2026-10-19.md`).

## Relación con otras skills

- `dev-workflow`: ejecutar antes de hacer commits con los cambios de rutas.
- `frontend-specs`: reglas de componentes Vue 3 y TypeScript.
