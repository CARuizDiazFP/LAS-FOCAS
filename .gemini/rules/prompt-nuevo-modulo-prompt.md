# Nombre de archivo: prompt-nuevo-modulo-prompt.md
# Ubicación de archivo: .gemini/rules/prompt-nuevo-modulo-prompt.md
# Descripción: Regla Gemini portable para andamiar modulos frontend SPA desacoplados
---
name: "prompt-nuevo-modulo-prompt"
description: "Contrato reusable para crear modulos/submodulos en Vue 3 con servicio API desacoplado"
source: ".github/prompts/nuevo-modulo.prompt.md"
triggers:
  - "nuevo-modulo"
  - "modulo"
  - "submodulo"
  - "frontend"
  - "vue"
  - "spa"
  - "router"
  - "api"
globs:
  - "web/**"
  - "docs/**"
  - ".github/**"
  - ".gemini/**"
commands:
  []
---

# Regla Prompt: nuevo-modulo.prompt

> Fuente original: `.github/prompts/nuevo-modulo.prompt.md`. Usar como contrato reutilizable cuando el pedido coincida con esta automatización.

---
name: Nuevo Módulo
description: "Crea un modulo/submodulo moderno para la SPA Vue 3, con rutas, componentes y servicio API desacoplado"
argument-hint: "Nombre del modulo, dominio y alcance, por ejemplo: Servicios/Ingesta con vista, rutas y API client"
agent: "agent"
---

# Crear Nuevo Módulo

Crear un modulo o submodulo frontend alineado al stack moderno del proyecto. Si faltan datos, inferir estructura minima y declarar supuestos.

## Objetivo

- andamiar una funcionalidad nueva en la SPA (vista + componentes + ruta + servicio API)
- forzar separacion frontend/backend con comunicacion estricta REST JSON (y WebSocket cuando aplique)
- impedir practicas legacy (Jinja, DOM directo, Vanilla JS como patron principal)
- actualizar documentacion relacionada y reglas inconsistentes detectadas

## Entradas esperadas

- nombre del modulo/submodulo
- objetivo funcional y flujo de usuario
- endpoint(s) API a consumir o contrato esperado
- contexto de navegacion (menu, ruta padre, permisos)
- alcance: solo frontend o frontend + requerimientos para API

## Flujo de trabajo

### 1. Definir alcance y limites

Antes de crear archivos, establecer:

- que resuelve el modulo
- que datos consume/produce
- que parte vive en SPA y que parte vive en API
- que validaciones y estados de error se mostraran en UI

### 2. Crear estructura estandar del modulo frontend

**Estructura real confirmada (2026-08-10) contra los modulos ya existentes** — `ServiciosView.vue`,
`InventarioCablesCromoView.vue`, `BotellasInventarioView.vue` — ninguno usa subcarpeta por modulo ni
sufijo `.api.ts`:

```
web/frontend/src/
├── views/<Modulo>View.vue          # PLANO bajo views/, nunca views/<Modulo>/<Modulo>View.vue
├── components/<modulo>/
│   └── <Modulo>Card.vue            # si hay vista de tarjeta + lista con toggle
├── composables/use<Modulo>.ts      # SOLO si el estado se comparte entre 2+ vistas — si vive solo en
│                                     # la vista, queda inline en su <script setup>
├── api/<modulo>.ts                  # NUNCA <modulo>.api.ts — cero archivos con ese sufijo en el repo
└── router/index.ts (agregar la ruta ahi, es unico)
```

Si el alcance requiere backend, no mezclarlo en la vista: documentar contrato API y coordinar handoff con `api.agent.md`.

### 3. Reglas obligatorias de implementacion

1. Composition API obligatoria (`<script setup lang="ts">`, `ref`, `reactive`, `computed`).
2. Capa API separada en `src/api/`, sin fetch/axios embebido en template.
3. Estado y logica de pantalla en composables reutilizables.
4. UI con CSS modular y tokens del proyecto.
5. Respuesta de errores UX clara (loading, empty, error, retry).

### 4. Prohibiciones no negociables

1. Prohibido `document.querySelector`, `innerHTML`, mutaciones manuales de DOM para flujo principal.
2. Prohibido Jinja o render server-side para pantallas nuevas de frontend.
3. Prohibido Vanilla JS clasico para manejo de estado en nuevos modulos.
4. Prohibido usar `v-html` con contenido no confiable.

### 5. Seguridad obligatoria

1. Validar payloads en backend con Pydantic (si hay cambios de API).
2. Asegurar CORS estricto por allowlist en produccion.
3. Sanitizar o escapar cualquier contenido dinamico mostrable.
4. Respetar auth/sesion/CSRF de la capa web cuando aplique.

### 6. Actualizacion de rutas y navegacion

1. Registrar ruta en Vue Router segun convencion existente.
2. Integrar el modulo en menu o acceso correspondiente.
3. Mantener guards/permisos si la seccion es protegida.

### 7. Tests y documentacion

- agregar o actualizar pruebas unitarias del modulo/composable/API client
- documentar el flujo en `docs/web.md` o documento funcional relacionado
- actualizar `docs/Mate_y_Ruta.md` si cambia arquitectura, flujo o estado operativo

## Criterios universales de aceptacion

1. Se entrega vista, componentes reutilizables, ruta y servicio API desacoplado.
2. No hay Jinja, no hay DOM directo y no hay Vanilla JS de estado en el modulo nuevo.
3. El flujo consume API JSON de forma tipada y manejando errores.
4. Se actualiza documentacion relacionada y se corrigen contradicciones legacy detectadas.
5. La salida queda lista para sincronizar en `.github/` y `.gemini/`.

## Salida esperada del agente

1. Crear los archivos concretos del modulo frontend con estructura estandar.
2. Explicar decisiones de arquitectura (estado, rutas, API, seguridad).
3. Indicar validaciones ejecutadas y pendientes.
4. Dejar lista la sincronizacion de reglas equivalentes para Gemini cuando aplique.

## Nota de alcance

Este prompt organiza creacion de modulos para la SPA. No reemplaza skills de backend; cuando se requieran endpoints nuevos, activar handoff a `api.agent.md` y mantener separacion de capas.
