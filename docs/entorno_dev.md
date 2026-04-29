# Nombre de archivo: entorno_dev.md
# Ubicación de archivo: docs/entorno_dev.md
# Descripción: Guía completa para trabajar en el entorno de Desarrollo (Dev) de LAS-FOCAS

# Entorno de Desarrollo (Dev) — LAS-FOCAS

## Regla de oro

> **Nunca probar directamente en producción.**
>
> Todo trabajo de exploración, feature, bug-fix o experimento se realiza sobre la rama `dev` y el stack `lasfocasdev`. Los cambios solo llegan a producción (`main` / stack `lasfocas`) mediante Pull Request revisado.

---

## Modelo de ramas

```
main  ──────────────────────────────────────►  producción (192.168.241.28:8080)
  └─ dev  ──────────────────────────────────►  desarrollo  (localhost:8090)
       └─ feature/xxx  ──────────────────────►  (opcional, para features largas)
```

| Rama | Propósito | Stack |
|------|-----------|-------|
| `main` | Refleja exactamente lo que corre en producción. **Protegida.** | `lasfocas` (`compose.yml`) |
| `dev` | Rama de trabajo habitual. Recibe todos los commits nuevos. | `lasfocasdev` (`docker-compose.dev.yml`) |
| `feature/xxx` | Opcional, para features largas. Mergear a `dev`, nunca directo a `main`. | `lasfocasdev` |

---

## Stack de desarrollo (Docker)

El entorno dev corre en paralelo al productivo sin compartir puertos, volúmenes ni red.

### Puertos

| Servicio             | Producción                   | Dev (loopback)      |
|----------------------|------------------------------|---------------------|
| PostgreSQL           | `127.0.0.1:5432`             | `127.0.0.1:5433`    |
| API (docs: `/docs`)  | `:8001`                      | `:8011`             |
| Web (panel)          | `192.168.241.28:8080`        | `127.0.0.1:8090`    |
| pgAdmin (profile)    | `:5050`                      | `:5051`             |
| NLP / Office / Slack | interno                      | interno             |

El panel dev está vinculado a `127.0.0.1:8090`. Para acceso desde una máquina remota:

```bash
ssh -L 8090:localhost:8090 usuario@192.168.241.28
```

---

## Setup inicial (primera vez)

### 1. Posicionarse en la rama dev

```bash
git checkout dev
# Si no existe todavía:
git checkout -b dev
git push -u origin dev
```

### 2. Configurar variables de entorno dev

```bash
cp deploy/env.dev.sample .env.dev
# Editar credenciales — en particular:
#   SLACK_BOT_TOKEN y SLACK_APP_TOKEN  →  app Slack de desarrollo separada
#   POSTGRES_PASSWORD                  →  nunca usar la de producción
nano .env.dev
```

### 3. Levantar el stack dev

```bash
./scripts/start_dev.sh
```

El script hace automáticamente:
- Crear `Logs/dev/` si no existe
- Crear `.env.dev` desde el sample si no existe (con aviso para completar tokens)
- Levantar todos los servicios con build
- Esperar a que Postgres esté healthy
- Aplicar migraciones Alembic
- Verificar el health de todos los servicios

---

## Flujo de trabajo diario

### Levantar el entorno

```bash
# Build completo (primera vez o tras cambios de Dockerfile / dependencias)
./scripts/start_dev.sh

# Sin rebuild (iteración rápida de código Python/Vue)
./scripts/start_dev.sh --no-build

# Reinicio limpio (detiene y vuelve a levantar)
./scripts/start_dev.sh --down
```

### Clonar DB de producción a dev

Reproduce bugs con datos reales. Requiere que el stack prod esté corriendo.

```bash
./scripts/start_dev.sh --clone-db
```

### Detener el entorno dev

```bash
docker compose -f deploy/docker-compose.dev.yml down
```

### Ver logs en tiempo real

```bash
# Todos los servicios
docker compose -f deploy/docker-compose.dev.yml logs -f

# Un servicio específico
docker compose -f deploy/docker-compose.dev.yml logs -f web
docker compose -f deploy/docker-compose.dev.yml logs -f slack_baneo_worker
```

### Acceso al panel dev

- Panel web: `http://localhost:8090/`
- API docs (Swagger): `http://localhost:8011/docs`
- pgAdmin: `docker compose -f deploy/docker-compose.dev.yml --profile pgadmin up -d` → `http://localhost:5051`

---

## Flujo de commits en rama dev

```bash
# 1. Asegurarse de estar en dev
git checkout dev

# 2. Hacer los cambios...

# 3. Staging y commit
git add .
git commit -m "feat(módulo): descripción técnica del cambio"
git push origin dev
```

### Convención de commits

| Prefijo     | Cuándo usarlo |
|-------------|---------------|
| `feat:`     | Nueva funcionalidad |
| `fix:`      | Corrección de bug |
| `refactor:` | Refactoring sin cambio de comportamiento |
| `test:`     | Tests nuevos o ajustes |
| `docs:`     | Solo documentación |
| `chore:`    | Mantenimiento (deps, config, infraestructura) |
| `ci:`       | Scripts CI/CD |

---

## Variables de entorno (`.env.dev`)

| Variable              | Producción                       | Dev                         |
|-----------------------|----------------------------------|-----------------------------|
| `POSTGRES_DB`         | `FOCALDB`                        | `focas_dev`                 |
| `API_BASE`            | `http://192.168.241.28:8080`     | `http://localhost:8090`     |
| `WEB_INFERRED_ORIGIN` | `http://192.168.241.28:8080`     | `http://localhost:8090`     |
| `SLACK_BOT_TOKEN`     | app Slack prod                   | app Slack dev (separada)    |
| `SLACK_APP_TOKEN`     | app Slack prod                   | app Slack dev (separada)    |
| `LLM_PROVIDER`        | `openai`                         | `heuristic` (sin costo)     |
| `LOG_LEVEL`           | `INFO`                           | `DEBUG`                     |
| `ENV`                 | `production`                     | `development`               |

---

## Archivos clave del entorno dev

| Archivo                         | Descripción |
|---------------------------------|-------------|
| `deploy/docker-compose.dev.yml` | Stack Docker Compose completo con puertos alternativos |
| `deploy/env.dev.sample`         | Plantilla de variables de entorno dev |
| `.env.dev`                      | Variables activas — **no versionado en git** |
| `scripts/start_dev.sh`          | Script de inicio con flags, migraciones y healthchecks |

---

## Reglas del entorno dev para agentes (Copilot/Cursor)

Ver `.github/skills/dev-workflow/SKILL.md` para el protocolo completo. Reglas mínimas:

1. Verificar que la rama activa sea `dev` antes de modificar código: `git branch --show-current`.
2. No modificar `deploy/compose.yml`, `.env` ni ningún archivo de producción sin aprobación explícita.
3. Usar siempre `docker compose -f deploy/docker-compose.dev.yml` para operaciones Docker en dev.
4. Hacer push siempre a `origin/dev`, nunca directo a `origin/main`.
5. Los merges a `main` se hacen solo mediante PR revisado.

---

## Limitaciones conocidas

### Panel admin y docker.sock

El servicio `web` monta `/var/run/docker.sock` para controlar contenedores desde el panel admin. En producción busca `lasfocas-slack-baneo-worker`. En dev el contenedor es `lasfocasdev-slack-baneo-worker`, por lo que el toggle admin del panel dev no controla el worker dev vía socket. El worker funciona autónomamente sin problema.

### Slack App de desarrollo

Se requiere crear una **Slack App separada** en `https://api.slack.com/apps` (ej: "LAS-FOCAS Dev") con sus propios tokens `SLACK_BOT_TOKEN` y `SLACK_APP_TOKEN`. Sin esto el listener de ingresos técnicos quedará inactivo en dev — comportamiento esperado.

---

## Referencias

- [deploy/docker-compose.dev.yml](../deploy/docker-compose.dev.yml)
- [deploy/env.dev.sample](../deploy/env.dev.sample)
- [scripts/start_dev.sh](../scripts/start_dev.sh)
- [docs/infra.md](infra.md) — sección "Entorno de Desarrollo"
- [.github/skills/dev-workflow/SKILL.md](../.github/skills/dev-workflow/SKILL.md)
