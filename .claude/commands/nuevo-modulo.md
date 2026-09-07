# Nombre de archivo: nuevo-modulo.md
# Ubicación de archivo: .claude/commands/nuevo-modulo.md
# Descripción: Comando Claude Code para andamiar módulos frontend SPA Vue 3

Crea un módulo o submódulo frontend alineado al stack moderno del proyecto. Argumento requerido: $ARGUMENTS (nombre del módulo, objetivo funcional y alcance; por ejemplo: "Servicios/Ingesta con vista, rutas y API client").

Si faltan datos, inferir estructura mínima y declarar supuestos.

## Objetivo

- andamiar una funcionalidad nueva en la SPA (vista + componentes + ruta + servicio API)
- forzar separación frontend/backend con comunicación estricta REST JSON (y WebSocket cuando aplique)
- impedir prácticas legacy (Jinja, DOM directo, Vanilla JS como patrón principal)
- actualizar documentación relacionada

## Flujo de trabajo

### 1. Definir alcance y límites

Antes de crear archivos, establecer:
- qué resuelve el módulo
- qué datos consume/produce
- qué parte vive en SPA y qué parte vive en API
- qué validaciones y estados de error se mostrarán en UI

### 2. Crear estructura estándar del módulo frontend

**Estructura real confirmada (2026-08-10) contra los módulos ya existentes** — `ServiciosView.vue`,
`InventarioCablesCromoView.vue`, `BotellasInventarioView.vue` — ninguno usa subcarpeta por módulo ni
sufijo `.api.ts`:

```
web/frontend/src/
├── views/<Modulo>View.vue          # PLANO bajo views/, nunca views/<Modulo>/<Modulo>View.vue
├── components/<modulo>/
│   └── <Modulo>Card.vue            # si hay vista de tarjeta + lista con toggle (ver ServiciosView)
├── composables/use<Modulo>.ts      # SÓLO si el estado se comparte entre 2+ vistas — si vive sólo en
│                                     # la vista (caso más común), queda inline en su <script setup>
├── api/<modulo>.ts                  # NUNCA <modulo>.api.ts — cero archivos con ese sufijo en el repo
└── router/index.ts (agregar la ruta ahí, es único)
```

Si el alcance requiere backend, documentar contrato API y coordinar con el agente `api`.

### 3. Reglas obligatorias de implementación

1. Composition API obligatoria (`<script setup lang="ts">`, `ref`, `reactive`, `computed`).
2. Capa API separada en `src/api/`, sin fetch/axios embebido en template.
3. Estado y lógica de pantalla inline en la vista salvo que se comparta entre 2+ vistas.
4. UI con CSS modular y tokens del proyecto.
5. Respuesta de errores UX clara (loading, empty, error, retry).

### 4. Prohibiciones no negociables

1. Prohibido `document.querySelector`, `innerHTML`, mutaciones manuales de DOM para flujo principal.
2. Prohibido Jinja o render server-side para pantallas nuevas de frontend.
3. Prohibido Vanilla JS clásico para manejo de estado en nuevos módulos.
4. Prohibido usar `v-html` con contenido no confiable.

### 5. Seguridad obligatoria

1. Validar payloads en backend con Pydantic si hay cambios de API.
2. Asegurar CORS estricto por allowlist en producción.
3. Sanitizar o escapar cualquier contenido dinámico mostrable.
4. Respetar auth/sesión/CSRF de la capa web cuando aplique.

### 6. Actualización de rutas y navegación

1. Registrar ruta en Vue Router según convención existente.
2. Integrar el módulo en menú o acceso correspondiente.
3. Mantener guards/permisos si la sección es protegida.

### 7. Tests y documentación

- Agregar o actualizar pruebas unitarias del módulo/composable/API client.
- Documentar el flujo en `docs/web.md` o documento funcional relacionado.
- Actualizar `docs/Mate_y_Ruta.md` si cambia arquitectura, flujo o estado operativo.

## Criterios de aceptación

- [ ] Vista, componentes reutilizables, ruta y servicio API desacoplado entregados
- [ ] Sin Jinja, sin DOM directo, sin Vanilla JS de estado en el módulo nuevo
- [ ] Flujo consume API JSON de forma tipada manejando errores
- [ ] Documentación relacionada actualizada

## Salida esperada

1. Archivos concretos del módulo frontend con estructura estándar.
2. Decisiones de arquitectura explicadas (estado, rutas, API, seguridad).
3. Validaciones ejecutadas y pendientes.
4. Sincronización con agentes y documentación indicada.
