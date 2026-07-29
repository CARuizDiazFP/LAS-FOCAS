---
name: "las-focas-frontend-spa-architecture"
description: "Usar SIEMPRE antes de agregar, modificar o mover rutas, vistas o componentes en el frontend SPA de LAS-FOCAS. Valida el entry point activo, el router unificado y advierte sobre archivos huérfanos conocidos."
metadata:
  short-description: "Usar SIEMPRE antes de agregar rutas o vistas en el SPA de LAS-FOCAS. Valida entry point, router unificado y archivos huérfanos."
  source: ".github/skills/frontend-spa-architecture/SKILL.md"
  triggers:
    - "frontend-spa-architecture"
    - "spa"
    - "router"
    - "ruta"
    - "rutas"
    - "vue-router"
    - "admin"
    - "vista"
    - "vistas"
    - "componente"
    - "entry-point"
    - "index.html"
    - "main.ts"
    - "src/router"
    - "admin/router"
    - "RouterLink"
    - "RouterView"
    - "children"
    - "path-match"
    - "huerfano"
    - "frontend"
  globs:
    - "web/frontend/src/router/**"
    - "web/frontend/src/admin/**"
    - "web/frontend/src/views/**"
    - "web/frontend/index.html"
    - "web/frontend/vite.config.ts"
  commands:
    - |
      grep -n "src/main" web/frontend/index.html
    - |
      grep -n "from.*router" web/frontend/src/main.ts
    - |
      grep -n "pathMatch" web/frontend/src/router/index.ts
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-frontend-spa-architecture/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/frontend-spa-architecture/SKILL.md

# Skill portable: frontend-spa-architecture

> Fuente original: `.github/skills/frontend-spa-architecture/SKILL.md`. Copia portable generada para el entorno OpenAI Codex.

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

### Archivos huérfanos — NO usar como referencia de rutas

| Archivo | Estado | Motivo |
|---|---|---|
| `web/frontend/src/admin/router/index.ts` | **Huérfano** | Nunca importado por ningún entry point activo |
| `web/frontend/src/admin/main.ts` | **Huérfano** | `index.html` solo referencia `src/main.ts`; este archivo existe pero no está conectado |

> **TRAMPA FRECUENTE**: modificar `src/admin/router/index.ts` creyendo que es el router del panel admin. No tiene efecto en runtime. El único router es `src/router/index.ts`.

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
  path: 'mi-modulo',            // relativo a /admin → resulta en /admin/mi-modulo
  name: 'admin-mi-modulo',
  component: AdminMiVista,
  meta: { requiresAdmin: true },
},
{ path: ':pathMatch(.*)*', redirect: '/admin' },  // catch-all SIEMPRE AL FINAL
```

### 3. Guard de navegación

El `router.beforeEach` en `src/router/index.ts` usa `useSession()`:
- Verifica `state.value.authenticated` — si no, redirige a `/login`.
- Verifica `state.value.role === 'admin'` para rutas con `meta.requiresAdmin` — si no, redirige a `/`.

---

## Patrón para agregar una ruta del panel (no admin)

Agregar como `children` de la ruta raíz `{ path: '/', component: AppShell }`:

```typescript
{
  path: 'mi-seccion',
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

---

## Guardrails

1. **No modificar** `src/admin/router/index.ts` para agregar rutas operativas — no tiene efecto en runtime.
2. **No crear** `src/admin/main.ts` como entry point alternativo sin actualizar `index.html` y `vite.config.ts`.
3. **No importar** el router huérfano desde ningún componente nuevo.
4. **Siempre** colocar el catch-all `':pathMatch(.*)*'` como último elemento de los `children` de `/admin`.
5. **Siempre** usar lazy imports (`() => import(...)`) para componentes de ruta en el router unificado.

## Relación con otras skills

- `dev-workflow`: ejecutar antes de hacer commits con los cambios de rutas.
- `frontend-specs`: reglas de componentes Vue 3 y TypeScript.
