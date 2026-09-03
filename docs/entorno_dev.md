# Nombre de archivo: entorno_dev.md
# Ubicación de archivo: docs/entorno_dev.md
# Descripción: Guía completa para trabajar en el entorno de Desarrollo (Dev) de LAS-FOCAS

# Entorno de Desarrollo (Dev) — LAS-FOCAS

## Regla de oro

> **Nunca probar directamente en producción.**
>
> Todo trabajo de exploración, feature, bug-fix o experimento se realiza sobre una rama efímera creada desde `dev` (stack `lasfocasdev`); nunca se commitea directo en `dev`. Los cambios llegan a `dev` vía `cierre-sesion`, y a producción (`main` / stack `lasfocas`) solo mediante Pull Request revisado.

---

## Modelo de ramas

```
main  ──────────────────────────────────────►  producción (172.18.208.162:8080)
  └─ dev  ──────────────────────────────────►  desarrollo  (localhost:8090)
       └─ <tipo>/<slug> (obligatoria)  ─────►  rama efímera por tarea/sesión
```

| Rama | Propósito | Stack |
|------|-----------|-------|
| `main` | Refleja exactamente lo que corre en producción. **Protegida.** | `lasfocas` (`compose.yml`) |
| `dev` | Rama de integración. Recibe únicamente merges automáticos de ramas efímeras vía `cierre-sesion`, nunca commits directos de agentes. | `lasfocasdev` (`docker-compose.dev.yml`) |
| `<tipo>/<slug>` | **Obligatoria** para todo cambio (`feat/`, `fix/`, `docs/`, `chore/`, `refactor/`, `test/`). Creada automáticamente por `dev-workflow` desde `origin/dev`; integrada a `dev` automáticamente por `cierre-sesion` al cerrar la sesión. Nunca commit directo en `dev`/`main`. | `lasfocasdev` |

---

## Stack de desarrollo (Docker)

El entorno dev corre en paralelo al productivo sin compartir puertos, volúmenes ni red.

### Red Docker

La red `lasfocas_dev_net` usa una subred explícita **`172.19.0.0/24`** (no el default `/16` que asigna Docker) para evitar que la ruta conectada del bridge "secuestre" tráfico hacia hosts externos reales que caigan dentro del mismo bloque `/16` (ver `docs/decisiones.md`, entrada 2026-08-05). Si se agrega una nueva red Docker a este repo, declarar siempre `ipam.config.subnet` explícito en vez de dejar que Docker asigne un `/16` por default.

### Puertos

| Servicio             | Producción                   | Dev (loopback)      |
|----------------------|------------------------------|---------------------|
| PostgreSQL           | `127.0.0.1:5432`             | `127.0.0.1:5433`    |
| API (docs: `/docs`)  | `:8001`                      | `:8011`             |
| Web (panel)          | `172.18.208.162:8080`        | `127.0.0.1:8090`    |
| pgAdmin (profile)    | `127.0.0.1:5050`             | `127.0.0.1:5051`    |
| NLP / Office / Slack | interno                      | interno             |

El panel dev está vinculado a `127.0.0.1:8090`. Para acceso desde una máquina remota:

```bash
ssh -L 8090:localhost:8090 usuario@172.18.208.162
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

> Esto es el setup inicial del repositorio en sí (crear la rama compartida `dev` si todavía no
> existe), **no** el flujo de trabajo por tarea: nunca se commitea directo en `dev`. La rama de
> trabajo de cada tarea es una rama efímera (`feat|fix|docs|chore|refactor|test/<slug>`) que crea
> `dev-workflow` desde `origin/dev`, y que `cierre-sesion` integra de vuelta a `dev` al cerrar la
> sesión.

### 2. Configurar variables de entorno dev y secretos

```bash
cp deploy/env.dev.sample .env.dev
# Editar valores no sensibles y placeholders de compatibilidad.
nano .env.dev

./scripts/setup_local_secrets.sh
```

El stack dev monta Docker Secrets desde `.secrets/*.txt`. Si falta un archivo,
el código Python cae a las variables tradicionales de `.env.dev` para no bloquear
la transición de otros desarrolladores.

### 3. Levantar el stack dev

```bash
./scripts/start_dev.sh
```

El script hace automáticamente:
- Crear `Logs/dev/` si no existe
- Crear `.env.dev` desde el sample si no existe (con aviso para completar tokens)
- Crear `.secrets/*.txt` si no existen y leerlos como Docker Secrets
- Construir `focas-base:latest` si `common-requirements.txt` cambió (via `scripts/build_base.sh`)
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

# Sin rebuild de servicios (iteración rápida de código Python/Vue)
./scripts/start_dev.sh --no-build

# Reinicio limpio (detiene y vuelve a levantar)
./scripts/start_dev.sh --down
```

> **Nota:** Si modificaste `common-requirements.txt` (agregaste una dependencia común), reconstruye primero la imagen base:
> ```bash
> ./scripts/build_base.sh
> ```
> `start_dev.sh` llama a `build_base.sh` automáticamente, pero si solo quieres verificar el estado de la imagen base sin levantar el stack, puedes ejecutarlo directamente.

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
- pgAdmin: `docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev --profile pgadmin up -d pgadmin` → `http://localhost:5051` (solo loopback). Requiere `PGADMIN_EMAIL` seteado en `.env.dev` y el secreto `.secrets/Dev_pgadmin_password_v1.txt` generado por `./scripts/setup_local_secrets.sh` — la password ya no es `admin`/`admin` hardcodeada, ver `docs/decisiones.md` entrada 2026-08-11.

---

## Flujo de commits en rama efímera

```bash
# 1. dev-workflow crea o reutiliza la rama efímera desde origin/dev
#    (formato <tipo>/<slug>, p. ej. feat/mi-cambio)

# 2. Hacer los cambios...

# 3. Staging y commit sobre la rama efímera
git add .
git commit -m "feat(módulo): descripción técnica del cambio"
git push -u origin HEAD

# 4. dev sólo recibe el merge final, ejecutado automáticamente por cierre-sesion
#    al cerrar la sesión. Nunca commitear ni pushear directo a dev/main.
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
| `API_BASE`            | `http://172.18.208.162:8080`     | `http://localhost:8090`     |
| `WEB_INFERRED_ORIGIN` | `http://172.18.208.162:8080`     | `http://localhost:8090`     |
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
| `.secrets/`                     | Docker Secrets locales dev — **no versionado en git** |
| `scripts/start_dev.sh`          | Script de inicio con flags, migraciones y healthchecks |
| `scripts/setup_local_secrets.sh` | Bootstrap idempotente de secretos locales |
| `scripts/check_no_plaintext_secrets.sh` | Control preventivo de secretos versionados |

---

## Reglas del entorno dev para agentes (Copilot/Cursor)

Ver `.github/skills/dev-workflow/SKILL.md` para el protocolo completo. Reglas mínimas:

1. Trabajar siempre sobre una rama efímera `<tipo>/<slug>` creada desde `origin/dev` — nunca commitear directo en `dev` ni en `main`. `dev-workflow` crea o reutiliza esa rama automáticamente al inicio de la sesión/tarea.
2. No modificar `deploy/compose.yml`, `.env` ni ningún archivo de producción sin aprobación explícita.
3. Usar siempre `docker compose -f deploy/docker-compose.dev.yml` para operaciones Docker en dev.
4. Hacer push siempre a la rama efímera activa (`git push -u origin HEAD`), nunca directo a `origin/dev` ni `origin/main`.
5. La integración a `dev` es automática al cierre de sesión (`cierre-sesion`), que mergea la rama efímera. Los merges de `dev` a `main` se hacen solo mediante PR revisado.

---

## Limitaciones conocidas

### Panel admin y control del worker de baneos

El panel admin controla el contenedor `slack_baneo_worker` sin montar `/var/run/docker.sock` en `web` (desde 2026-08-11): `web` habla con `docker-socket-proxy` (`tecnativa/docker-socket-proxy`, red dedicada `docker_proxy_dev_net`), acotado a `containers.get`/`.start`/`.reload` sobre un único contenedor — ver `docs/decisiones.md`, entrada 2026-08-11. En producción el panel busca `lasfocas-slack-baneo-worker`; en dev el contenedor es `lasfocasdev-slack-baneo-worker`, por lo que el toggle admin del panel dev sigue sin controlar el worker dev por nombre (limitación preexistente, no relacionada al proxy). El worker funciona autónomamente sin problema en ambos casos.

### Slack App de desarrollo

Se requiere crear una **Slack App separada** en `https://api.slack.com/apps` (ej: "LAS-FOCAS Dev") con sus propios tokens `SLACK_BOT_TOKEN` y `SLACK_APP_TOKEN`. Sin esto el listener de ingresos técnicos quedará inactivo en dev — comportamiento esperado.

---

## Referencias

- [deploy/docker-compose.dev.yml](../deploy/docker-compose.dev.yml)
- [deploy/env.dev.sample](../deploy/env.dev.sample)
- [scripts/start_dev.sh](../scripts/start_dev.sh)
- [docs/infra.md](infra.md) — sección "Entorno de Desarrollo"
- [.github/skills/dev-workflow/SKILL.md](../.github/skills/dev-workflow/SKILL.md)
