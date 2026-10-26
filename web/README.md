# Nombre de archivo: README.md
# Ubicación de archivo: web/README.md
# Descripción: Uso rápido del servicio Web (UI)

# Web (UI) — Uso rápido

La documentación completa del servicio (backend FastAPI por routers, SPA Vue 3, rutas, sesión,
endpoints, variables y Docker) está en [`docs/web.md`](../docs/web.md). Este archivo sólo deja los
comandos de trabajo.

## Rebuild en el stack dev (forma de validar)

Desde la raíz del repo:

```bash
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev up -d --build web
```

El `web/Dockerfile` compila el SPA (`npm ci` + `npm run build`) y lo copia en `/app/frontend/dist`.
El panel dev queda en `http://127.0.0.1:8090` (ver `docs/entorno_dev.md`).

## Frontend (`web/frontend/`)

Scripts de `package.json`:

| Comando | Qué hace |
|---|---|
| `npm run dev` | servidor de Vite |
| `npm run build` | build a `web/frontend/dist/` |
| `npm run preview` | sirve el build en el puerto 5173 |
| `npm run type-check` | `vue-tsc --noEmit -p tsconfig.json` |

`vite.config.ts` no define proxy hacia el backend: el `npm run dev` por sí solo no alcanza `/api/*`.
