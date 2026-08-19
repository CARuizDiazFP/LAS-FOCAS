# Nombre de archivo: skill-nocturne-token-compliance.md
# Ubicación de archivo: .gemini/rules/skill-nocturne-token-compliance.md
# Descripción: Regla Gemini portable migrada desde .github/skills/nocturne-token-compliance/SKILL.md
---
name: "skill-nocturne-token-compliance"
description: "Usar antes de dar por cerrada cualquier tarea de UI/CSS en el SPA: audita colores hardcodeados fuera de tokens.css (vista + todo su árbol de imports) y define cómo verificar el resultado real cuando no hay navegador disponible en la sesión"
source: ".github/skills/nocturne-token-compliance/SKILL.md"
triggers:
  - "nocturne-token-compliance"
  - "habilidad"
  - "nocturne"
  - "tokens"
  - "tokens.css"
  - "colores"
  - "hardcodeados"
  - "css"
  - "frontend"
  - "vue"
  - "audita"
  - "verificar"
  - "las-focas"
globs:
  - "web/frontend/src/**/*.vue"
  - "web/frontend/src/**/*.css"
  - "web/frontend/src/assets/styles/tokens.css"
commands:
  - |
    grep -nE "#[0-9a-fA-F]{3,6}|rgba?\(" ruta/Vista.vue
  - |
    grep -n "^import" ruta/Vista.vue
  - |
    grep -rlE "#[0-9a-fA-F]{3,6}|rgba?\(" web/frontend/src/components/infra/*.vue
  - |
    which chromium chromium-browser google-chrome 2>/dev/null
    python3 -c "import playwright" 2>&1 | head -1
  - |
    # 1. Build local — atrapa errores de sintaxis/tipos antes de gastar tiempo de Docker
    npm --prefix web/frontend run build

    # 2. Rebuild + restart SOLO del servicio web en dev (ver skill docker-rebuild para el
    #    checklist de drift de red antes de un `up` incremental)
    docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev build web
    docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev up -d web

    # 3. Confirmar en el CSS REALMENTE servido dentro del contenedor corriendo — no en tu
    #    dist/ local, que no es lo que el usuario tiene abierto en el navegador
    CSS=$(docker exec lasfocasdev-web sh -c "ls /app/frontend/dist/assets | grep '^NombreVista.*\.css$'")
    docker exec lasfocasdev-web grep -c "<hex-viejo>" "/app/frontend/dist/assets/$CSS"
    docker exec lasfocasdev-web grep -o "color-mix(in srgb,var(--TOKEN-nuevo)" "/app/frontend/dist/assets/$CSS" | head -1
  - |
    grep -rn 'class="btn"' web/frontend/src --include=*.vue
---

# Regla Skill: nocturne-token-compliance

> Fuente original: `.github/skills/nocturne-token-compliance/SKILL.md`. Usar esta regla cuando Gemini/Codex IDE detecte los triggers o globs declarados.

# Habilidad: Nocturne Token Compliance

Procedimiento para que un cambio de estilo en el SPA Vue 3 quede realmente unificado con el tema
oscuro Nocturne (`web/frontend/src/assets/styles/tokens.css`), en vez de "arreglar la vista que se
ve mal" y dejar componentes hijos con la misma paleta vieja. Nace del cierre de sesión
2026-08-14 18:52 (`docs/cierres/2026-08-14.md`): una corrección de paleta en `CamaraDetailView.vue`
necesitó dos ciclos completos de build+rebuild de Docker porque el primer barrido de colores
hardcodeados sólo miró el archivo de la vista, no los 9 componentes de `components/infra/` que esa
vista importa y que compartían el mismo problema por copy-paste.

## Regla de oro

Ningún componente `.vue` — vista, modal, card, o cualquier otro — puede usar un color hex o `rgba()`
literal para **superficie, texto, borde o estado semántico**. Sólo variables de `tokens.css`, o
`color-mix()` construido sobre ellas.

**Excepciones explícitas, ya identificadas en este proyecto — no las trates como violaciones:**

- **Paletas categóricas de datos**: colores de ruta/serie en diagramas (`TrackingDetail.vue`,
  `views/tabs/InfraTab.vue` — `PRINCIPAL`/`BACKUP`/`ALTERNATIVA`/`CUARTO`). Son marcas de un
  gráfico, no colores de tema; deliberadamente vívidos e independientes del modo claro/oscuro.
- **Scrims de backdrop de modal**: `rgba(4, 8, 14, 0.7-0.82)` sobre `::backdrop` de `<dialog>`. Son
  overlays neutros estándar, no superficies del tema.
- **Texto blanco sólido sobre fondos de acento/estado** (`color: #fff` sobre `background:
  var(--primary)`/`var(--warning)`/`var(--error)`): contraste garantizado independiente del token
  de fondo: es más simple y correcto que derivar un "texto-sobre-acento" que `tokens.css` no define.

## Mapa de tokens (`tokens.css`)

| Rol | Token | Uso típico |
|---|---|---|
| Fondo de página | `--color-bg` | fondo de tarjetas internas, inputs, tracks |
| Superficie elevada | `--color-surface` | fondo de cards, modales, headers |
| Texto principal | `--color-text` | títulos, valores |
| Texto atenuado | `--muted` / `color-mix(in srgb, var(--color-text) N%, transparent)` | subtítulos, hints |
| Borde/divisor | `--color-divider` / `--border` | bordes de card, filas de tabla |
| Acento (marca) | `--color-accent`, `--color-accent-200/300` | links, eyebrows, chips activos |
| Fondo tintado de acento | `--color-brand-primary-tint` (8%) / `--color-brand-primary-soft` (14%) | chips, hover de accent |
| Estado OK | `--success` (= `--color-state-ok`) | LIBRE, badges de éxito |
| Estado warn | `--warning` (= `--color-state-warn`) | OCUPADA, avisos |
| Estado error | `--error` (= `--color-state-error`) | BANEADA, mensajes de error |
| Estado neutro/idle | `--color-state-idle` | NO_OPERATIVA, "desconocido" |
| Sombra | `--shadow-sm` / `--shadow-md` / `--shadow-lg` | elevación (nunca inventar `box-shadow` con rgba(0,0,0,x) propio salvo scrims) |

Para un color con transparencia que no sea un alias ya definido, usar
`color-mix(in srgb, var(--TOKEN) N%, transparent)` — nunca `rgba()` con el equivalente hex del
token copiado a mano (se desincroniza en cuanto alguien cambie el token).

> **Nunca reintroducir verdes/ámbares/rojos saturados tipo Tailwind** (`#16a34a`, `#f59e0b`,
> `#ef4444`, `#34d399`, `#facc15`, `#f87171`…) para estados semánticos. El comentario de
> `tokens.css` es explícito: "Nocturne es monocromo... no reemplazar por los verdes/rojos saturados
> del panel viejo." Si ves uno de estos hex en un diff nuevo, es casi siempre una regresión.

## Procedimiento de auditoría (el paso que falló el 2026-08-14)

1. Grepear colores hardcodeados en el/los archivo(s) que motivan la tarea:
   ```bash
   grep -nE "#[0-9a-fA-F]{3,6}|rgba?\(" ruta/Vista.vue
   ```
2. **Trazar el árbol de imports de esa vista/componente** — no asumas que el problema está sólo ahí:
   ```bash
   grep -n "^import" ruta/Vista.vue
   ```
   Cada componente Vue importado (típicamente en `components/infra/`, `components/servicios/`,
   `components/app-shell/`) puede tener exactamente el mismo problema y no aparece en un grep
   acotado a `views/`. Repetir el paso 1 sobre cada uno, recursivamente si un hijo importa a otro.
3. Repetir sobre el directorio completo relevante para no depender sólo del árbol de imports leído a
   mano (los componentes de infra en este proyecto se comparten entre varias vistas):
   ```bash
   grep -rlE "#[0-9a-fA-F]{3,6}|rgba?\(" web/frontend/src/components/infra/*.vue
   ```
4. Antes de tocar una hoja de estilos **global y sin scope** (`web/frontend/src/admin/admin.css`,
   `web/frontend/src/panel.css`, ambas importadas juntas y sin scope en `main.ts`), verificar que la
   clase que vas a agregar/tocar no exista ya con otro valor en la otra hoja — la carga por
   `<script>` sin scope hace que la cascada CSS normal (misma especificidad, último import gana
   *por propiedad*, no por regla completa) decida en silencio cuál gana. Casos reales ya detectados:
   - `.container` estaba definida en ambos con valores distintos y **muerta** en las dos (ningún
     template la usaba) — eliminada de `admin.css`.
   - `.btn` sigue definida en ambos con `border` en conflicto (`var(--border)` en `admin.css` vs.
     `transparent` en `panel.css`, que carga después y gana esa propiedad) — **sin resolver
     todavía**, afecta a los usos de `class="btn"` sin modificador (`.primary`/`.subtle`/etc.).
     Verificar con `grep -rn 'class="btn"' web/frontend/src --include=*.vue` antes de asumir que un
     botón "simple" se ve como en `admin.css`.

## Verificación sin navegador disponible

Esta sesión (y probablemente la tuya) no tiene Chromium/Playwright instalado en el entorno de
ejecución. Confirmalo antes de asumir que no hay forma de verificar visualmente:

```bash
which chromium chromium-browser google-chrome 2>/dev/null
python3 -c "import playwright" 2>&1 | head -1
```

Si no hay nada, **no te quedes con "no se puede verificar"** — probá primero la skill/tool `run`
(catalogada para "confirmar que un cambio funciona en la app real"; puede que sí tenga un mecanismo
de captura que este checklist no conoce). Si `run` tampoco resuelve el caso navegador, el sustituto
válido es verificar contra el **bundle realmente servido**, no sólo contra `npm run build` local
(eso sólo prueba que compila, no que el color cambió en lo que el usuario ve):

```bash
# 1. Build local — atrapa errores de sintaxis/tipos antes de gastar tiempo de Docker
npm --prefix web/frontend run build

# 2. Rebuild + restart SOLO del servicio web en dev (ver skill docker-rebuild para el
#    checklist de drift de red antes de un `up` incremental)
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev build web
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev up -d web

# 3. Confirmar en el CSS REALMENTE servido dentro del contenedor corriendo — no en tu
#    dist/ local, que no es lo que el usuario tiene abierto en el navegador
CSS=$(docker exec lasfocasdev-web sh -c "ls /app/frontend/dist/assets | grep '^NombreVista.*\.css$'")
docker exec lasfocasdev-web grep -c "<hex-viejo>" "/app/frontend/dist/assets/$CSS"   # debe dar 0 o error (no matches)
docker exec lasfocasdev-web grep -o "color-mix(in srgb,var(--TOKEN-nuevo)" "/app/frontend/dist/assets/$CSS" | head -1
```

Documentar explícitamente en el PR diario (`docs/PR/YYYY-MM-DD.md`) que la verificación fue por
bundle servido y no visual, y dejar la confirmación visual humana como pendiente explícito — no
como implícitamente resuelto.

## Checklist antes de cerrar una tarea de UI/color

- [ ] Grep de hex/rgba limpio en el archivo tocado.
- [ ] Grep de hex/rgba limpio en **todo el árbol de imports** de ese archivo (paso 2-3 arriba).
- [ ] Ningún estado semántico nuevo usa verde/ámbar/rojo saturado — sólo
      `--color-state-ok/warn/error/idle`.
- [ ] Si se tocó una hoja de estilos global sin scope (`admin.css`/`panel.css`), se revisó que la
      clase no colisione con la otra hoja.
- [ ] Se intentó `run` (o se confirmó que no hay Chromium/Playwright) antes de recurrir a la
      verificación por bundle servido.
- [ ] El PR diario dice explícitamente si la verificación fue visual real o por bundle/grep.
