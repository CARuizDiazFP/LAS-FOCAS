# Nombre de archivo: skill-docker-rebuild.md
# Ubicación de archivo: .gemini/rules/skill-docker-rebuild.md
# Descripción: Regla Gemini portable migrada desde .github/skills/docker-rebuild/SKILL.md
---
name: "skill-docker-rebuild"
description: "Usar cuando haya que reconstruir servicios Docker, refrescar imágenes o verificar un rebuild selectivo de LAS-FOCAS"
source: ".agentes-comunes/skills/docker-rebuild/SKILL.md"
triggers:
  - "docker-rebuild"
  - "habilidad"
  - "docker"
  - "rebuild"
  - "reconstruir"
  - "servicios"
  - "refrescar"
  - "im-genes"
  - "verificar"
  - "selectivo"
  - "las-focas"
globs:
  - "deploy/**"
  - "**/Dockerfile"
  - "scripts/**"
commands:
  - |
    # Desde la raíz del proyecto:
    docker compose -f deploy/compose.yml --env-file .env build <servicio>

    # Servicios disponibles:
    # - api
    # - web
    # - bot
    # - nlp_intent
    # - office
    # - postgres
    # - repetitividad_worker (profile: reports-worker)
    # - pgadmin (profile: pgadmin)
  - |
    docker compose -f deploy/compose.yml --env-file .env build --no-cache <servicio>
  - |
    docker compose -f deploy/compose.yml --env-file .env build <servicio>
    docker compose -f deploy/compose.yml --env-file .env up -d <servicio>
  - |
    docker compose -f deploy/compose.yml --env-file .env build
    docker compose -f deploy/compose.yml --env-file .env up -d
  - |
    docker compose -f deploy/compose.yml --env-file .env ps
  - |
    # Todos los servicios
    docker compose -f deploy/compose.yml --env-file .env logs -f

    # Servicio específico
    docker compose -f deploy/compose.yml --env-file .env logs -f <servicio>

    # Últimas N líneas
    docker compose -f deploy/compose.yml --env-file .env logs --tail=100 <servicio>
  - |
    # Un servicio
    docker compose -f deploy/compose.yml --env-file .env restart <servicio>

    # Todos
    docker compose -f deploy/compose.yml --env-file .env restart
  - |
    # Detener sin eliminar
    docker compose -f deploy/compose.yml --env-file .env stop

    # Eliminar contenedores (no toca volúmenes)
    docker compose -f deploy/compose.yml --env-file .env down --remove-orphans

    # Eliminar incluyendo volúmenes (CUIDADO: borra datos)
    docker compose -f deploy/compose.yml --env-file .env down -v
  - |
    docker compose -f deploy/compose.yml --env-file .env --profile reports-worker up -d
  - |
    docker compose -f deploy/compose.yml --env-file .env --profile pgadmin up -d
  - |
    docker compose -f deploy/compose.yml --env-file .env build --progress=plain <servicio>
  - |
    docker compose -f deploy/compose.yml --env-file .env exec <servicio> bash
    # o sh si no tiene bash
    docker compose -f deploy/compose.yml --env-file .env exec <servicio> sh
  - |
    docker stats
  - |
    docker image prune -f
  - |
    docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev build <servicio>
    docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev up -d <servicio>
    docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev down --remove-orphans
    docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev ps
  - |
    ./Start
    ./scripts/start_dev.sh
---

# Regla Skill: docker-rebuild

> Fuente original: `.github/skills/docker-rebuild/SKILL.md`. Usar esta regla cuando Gemini/Codex IDE detecte los triggers o globs declarados.

# Habilidad: Docker Rebuild

Comandos y procedimientos para reconstruir contenedores Docker en LAS-FOCAS.

## Ubicación del Compose

> **IMPORTANTE**: El archivo de Compose está en `deploy/compose.yml` (prod) o `deploy/docker-compose.dev.yml` (dev), NO en la raíz.

> **CRÍTICO — `--env-file` obligatorio**: todo comando `docker compose` suelto (fuera de `./Start` / `./scripts/start_dev.sh`) sobre estos archivos debe incluir siempre `--env-file .env` (prod) o `--env-file .env.dev` (dev). Sin el flag, Compose busca el `.env` en `deploy/` (donde no existe), no resuelve `${POSTGRES_DB}`/`${POSTGRES_USER}` del servicio `postgres` y lo **recrea con esas variables vacías** — pasó en producción el 2026-07-29 al recrear solo `web`. Detalle en `docs/decisiones.md`, entrada 2026-07-29. Todos los comandos de esta skill ya incluyen el flag; no lo omitas si los adaptás.

## Comandos Básicos (producción — `deploy/compose.yml`)

### Reconstruir un servicio específico

```bash
# Desde la raíz del proyecto:
docker compose -f deploy/compose.yml --env-file .env build <servicio>

# Servicios disponibles:
# - api
# - web
# - bot
# - nlp_intent
# - office
# - postgres
# - repetitividad_worker (profile: reports-worker)
# - pgadmin (profile: pgadmin)
```

### Reconstruir sin cache

```bash
docker compose -f deploy/compose.yml --env-file .env build --no-cache <servicio>
```

### Reconstruir y reiniciar

```bash
docker compose -f deploy/compose.yml --env-file .env build <servicio>
docker compose -f deploy/compose.yml --env-file .env up -d <servicio>
```

### Reconstruir todos los servicios

```bash
docker compose -f deploy/compose.yml --env-file .env build
docker compose -f deploy/compose.yml --env-file .env up -d
```

## Gestión de Servicios (producción)

### Ver estado

```bash
docker compose -f deploy/compose.yml --env-file .env ps
```

### Ver logs

```bash
# Todos los servicios
docker compose -f deploy/compose.yml --env-file .env logs -f

# Servicio específico
docker compose -f deploy/compose.yml --env-file .env logs -f <servicio>

# Últimas N líneas
docker compose -f deploy/compose.yml --env-file .env logs --tail=100 <servicio>
```

### Reiniciar servicios

```bash
# Un servicio
docker compose -f deploy/compose.yml --env-file .env restart <servicio>

# Todos
docker compose -f deploy/compose.yml --env-file .env restart
```

### Detener servicios

```bash
# Detener sin eliminar
docker compose -f deploy/compose.yml --env-file .env stop

# Eliminar contenedores (no toca volúmenes)
docker compose -f deploy/compose.yml --env-file .env down --remove-orphans

# Eliminar incluyendo volúmenes (CUIDADO: borra datos)
docker compose -f deploy/compose.yml --env-file .env down -v
```

## Perfiles

### Activar worker de reportes

```bash
docker compose -f deploy/compose.yml --env-file .env --profile reports-worker up -d
```

### Activar pgAdmin

```bash
docker compose -f deploy/compose.yml --env-file .env --profile pgadmin up -d
```

## Troubleshooting

### Ver logs de build

```bash
docker compose -f deploy/compose.yml --env-file .env build --progress=plain <servicio>
```

### Entrar a un contenedor

```bash
docker compose -f deploy/compose.yml --env-file .env exec <servicio> bash
# o sh si no tiene bash
docker compose -f deploy/compose.yml --env-file .env exec <servicio> sh
```

### Ver uso de recursos

```bash
docker stats
```

### Limpiar imágenes no usadas

```bash
docker image prune -f
```

## Entorno Dev — `deploy/docker-compose.dev.yml`

El stack `lasfocasdev` corre en paralelo al productivo (`lasfocas`) sin compartir puertos, volúmenes ni red. Usa siempre `--env-file .env.dev`:

```bash
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev build <servicio>
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev up -d <servicio>
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev down --remove-orphans
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev ps
```

**No tocar `deploy/compose.yml` ni contenedores `lasfocas-*` (producción) sin instrucción explícita y puntual del usuario en ese momento** — ver `docs/decisiones.md`, directiva post-migración Nocturne (2026-07-29). Todo trabajo nuevo por default va a dev.

## Redes Docker (IPAM)

Ambas redes (`lasfocas_net` en prod, `lasfocas_dev_net` en dev) declaran subred **`/24` explícita** en `ipam.config` (`172.20.0.0/24` prod, `172.19.0.0/24` dev) — no se deja en manos del pool `/16` por default de Docker, que puede "secuestrar" rutas del host hacia destinos reales de la intranet dentro del mismo `/16`. Detalle completo, causa raíz y procedimiento de aplicación en ventana de mantenimiento para prod: `docs/mantenimiento_redes_produccion.md` y `docs/decisiones.md` (entradas 2026-08-05). Si se agrega una red nueva a este repo, declarar siempre `ipam.config.subnet` explícito — nunca dejar el default de Docker.

**Docker no permite cambiar la subred de una red existente sin recrearla** (`down` + `up`). Ningún servicio del proyecto usa `ipv4_address` (IP estática); si se agrega una, debe quedar entre `.1` y `.254` del `/24` correspondiente.

## Antes de un `up` incremental sobre servicios ya corriendo: verificar drift de red

**CRÍTICO**: antes de `docker compose ... up -d <un_servicio>` (contenedores ya arriba, no un stack recién levantado), comparar la subred *declarada* en el compose contra la *real* de la red viva:

```bash
docker network inspect <proyecto>_lasfocas_net --format '{{json .IPAM.Config}}'   # real
grep -A6 '^networks:' deploy/compose.yml                                          # declarada
```

Si difieren (ej. código ya migrado a `/24` pero la red viva sigue en `/16` de una migración pendiente — ver `docs/mantenimiento_redes_produccion.md`), Compose intenta recrear la red en el primer `up` que detecte el drift, **aunque se pida un solo servicio**. Si otros contenedores siguen conectados, la eliminación de la red falla a mitad de camino y deja esos contenedores desconectados (DNS de servicio roto entre ellos, sin un error obvio) — pasó en prod el 2026-08-11 con un `up -d api` que dejó a `api`/`postgres` sin poder resolverse mutuamente. Se reconecta a mano con `docker network connect --alias <nombre_servicio> <red> <contenedor>` (el alias de servicio no se restaura solo).

**Regla**: si hay drift de subred pendiente, no hacer `up` incremental de un servicio — usar `./Start` (down + up completo de los 6 servicios), que recrea la red limpia sin dejar nada a mitad de camino.

## Antes de agregar `useradd`/`USER` a `deploy/docker/base.Dockerfile`

`slack_baneo_worker.Dockerfile` y `cromo_worker.Dockerfile` heredan de `focas-base:latest` y crean su propio usuario con UID hardcodeado (antes: `useradd -m -u 1000 worker`; hoy reutilizan el `focas` compartido de la base). Si se agrega o cambia un usuario en la base con un UID que algún hijo ya usa, ese `useradd` falla en build con `UID <n> is not unique` y tumba el `docker compose up --build` completo si corre en el mismo `bake` — pasó en prod el 2026-08-11 al agregar `focas` (UID 1000) a la base sin revisar los hijos primero: outage completo de los 6 contenedores hasta corregirlo. Detalle en `docs/decisiones.md`, entrada 2026-08-11.

**Checklist obligatorio antes de tocar `base.Dockerfile`**:
```bash
grep -rn 'useradd\|^USER' deploy/docker/*.Dockerfile api/Dockerfile web/Dockerfile
```
Si algún Dockerfile hijo ya crea un usuario con el mismo UID que se va a agregar/cambiar en la base, migrarlo para que reutilice el usuario compartido (`chown -R <user>:<user> /app` + `USER <user>`) **en el mismo cambio**, no como nota al margen para después — el `user: "UID:GID"` de `compose.yml` manda en runtime independientemente del `USER` del Dockerfile, así que ese refactor no cambia el comportamiento real del contenedor.

## Contenedores `api` vs `web` en dev: mismo comando, código fuente distinto

`lasfocasdev-api` y `lasfocasdev-web` corren ambos `uvicorn app.main:app` desde el mismo path interno `/app/app/main.py` (sólo cambia el puerto: 8000 vs 8080) — pero cada imagen copia ahí un archivo fuente **distinto** del repo:

- `lasfocasdev-api` → `api/app/main.py` ("LAS-FOCAS API", auth por API key, rutas `reports`/`ingest`/`infra`/`servicios` para consumidores externos/scripts).
- `lasfocasdev-web` → `web/app/main.py` (backend de la SPA Vue 3, auth por sesión/CSRF — la mayoría de los endpoints `/api/infra/...`/`/api/admin/...` que se tocan en el día a día).

**Síntoma real** (2026-08-12, verificando un endpoint nuevo de `web/app/main.py`): un `docker exec lasfocasdev-api curl ...` contra un endpoint de la SPA devuelve 404 con `{"detail":"Not Found"}` — no porque la ruta esté mal, sino porque ese contenedor corre otra app FastAPI completa. `GET /openapi.json` en `lasfocasdev-api` no lista ningún `/api/infra/...` de la SPA (misma prueba rápida para confirmar cuál es cuál: `docker inspect <contenedor> --format '{{.Config.Cmd}}'` da el mismo comando en los dos, pero `docker exec <contenedor> grep -n 'Ubicación de archivo' /app/app/main.py` muestra el path real distinto).

**Regla**: para verificar wiring de un endpoint de `web/app/main.py` (nuevo o modificado), apuntar siempre a `lasfocasdev-web`:

```bash
docker exec lasfocasdev-web curl -s http://localhost:8080/api/infra/...
```

`docker exec`/`docker cp` para SCRIPTS batch (`scripts/*.py`, que sólo dependen de `core/`, `db/`, `scripts/`) sí es válido en `lasfocasdev-api` — esos directorios existen en ambas imágenes; el mix-up sólo afecta a endpoints HTTP servidos por `web/app/main.py`.

Si un curl da 404 con `{"detail":"Not Found"}` en vez del 401/403 esperado para un endpoint autenticado real, sospechar primero del contenedor equivocado antes de asumir que la ruta está mal registrada (para el otro patrón real de fallo — 422 por orden de registro de rutas en el mismo archivo — ver `docs/infra.md`, hallazgo de routing 2026-08-11).

## El directorio `scripts/` no está incluido en ninguna imagen

Ni `api/Dockerfile` ni `web/Dockerfile` copian `scripts/` a la imagen — es intencional (son scripts de mantenimiento/backfill manual, no parte del runtime de la app). Esto significa que **tras cualquier `build` seguido de `up -d`/`up -d --force-recreate`**, el contenedor recreado NO tiene `/app/scripts` — aunque una sesión anterior lo haya copiado ahí a mano con `docker cp`, ese cambio vivía sólo en la capa *writable* del contenedor viejo y se pierde al recrearlo desde la imagen.

**Síntoma real** (2026-08-12): después de un `build`+`up -d --force-recreate` de `api`, `docker cp scripts/mi_script.py lasfocasdev-api:/app/scripts/mi_script.py` falló con `Could not find the file /app/scripts` — el directorio padre no existía en el contenedor nuevo.

**Fix**: copiar el directorio completo (no archivo por archivo) para recrearlo de una:

```bash
docker cp scripts lasfocasdev-api:/app/scripts
```

Después de eso, los `docker cp` de archivos individuales dentro de `scripts/` vuelven a funcionar hasta la próxima recreación del contenedor.

## Antes de una verificación E2E real de cierre: reconstruir, no asumir que el contenedor está al día

Un `curl`/prueba real de cierre contra un contenedor ya corriendo puede fallar (o peor, "funcionar"
mostrando comportamiento viejo) aunque todos los tests hayan pasado en verde — los tests de
integración de este repo (`TestClient(app)` in-process, o `pytest` corrido directo desde el host)
ejercitan el código del *checkout*, nunca la imagen realmente deployada en el contenedor. Si nadie
reconstruyó desde el último cambio relevante, el contenedor sigue corriendo código viejo sin ningún
error ni warning que lo delate.

**Síntoma real** (2026-08-26): al cerrar un ciclo largo de `subagent-driven-development` (trazabilidad
de IDs de Servicios SLA), un `curl` real de verificación end-to-end contra `POST /servicios/ingest`
en `lasfocasdev-api` dio `IntegrityError: duplicate key ... servicio_id=X` — parecía un bug nuevo no
cubierto por ninguna revisión previa. Diagnóstico: `docker inspect lasfocasdev-api --format
'{{.Created}}'` mostraba la imagen construida ~4 horas antes de que se aplicara cualquiera de los
fixes del día (`git log --date=iso-strict` de los commits). Los ~20 tests/revisiones de ese ciclo
nunca podían haberlo detectado, porque ninguno corre contra la imagen deployada.

**Regla**: antes de cualquier verificación E2E real de cierre (un `curl`/request real contra un
endpoint, no un test), reconstruir primero los contenedores que ese código toca:

```bash
docker inspect <contenedor> --format '{{.Created}}'   # cuándo se construyó la imagen actual
git log --date=iso-strict -1 <archivo_relevante>       # cuándo se commiteó el último cambio real
# si el commit es posterior a la imagen, reconstruir antes de confiar en cualquier resultado:
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev build <servicio>
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev up -d <servicio>
```

No alcanza con que el servicio esté `healthy` — un healthcheck sólo confirma que el proceso responde,
no que corra el código más reciente.

**Segunda instancia real (2026-08-28), que amplía la regla**: no alcanza con reconstruir "los
contenedores que ya se sabe que el ciclo tocó" — hay que chequear **cualquier contenedor nuevo** en
el que se vaya a `docker exec`/curl por primera vez en la sesión, aunque nunca antes haya dado
problemas. Al cerrar un plan de `subagent-driven-development` (submódulo ODFs), la primera ingesta
real dentro de `lasfocasdev-cromo-worker` falló con `TypeError: ejecutar_ingesta() got an unexpected
keyword argument 'modo'` — ese contenedor nunca se había reconstruido durante todo el ciclo. Regla
ampliada: antes de `docker exec` dentro de CUALQUIER contenedor para una acción real, sin importar
si "nunca dio problemas antes", chequear su fecha de build contra el último commit relevante.

### Verificación real vía `TestClient` dentro de un contenedor: usar el context manager

Cuando no hay credenciales de admin para un `curl` autenticado real, entrar al contenedor y usar
`starlette.testclient.TestClient` contra la app real. Si se hacen varias llamadas sueltas (sin
`with`), puede aparecer `RuntimeError: ... Future ... attached to a different loop`. Usar siempre
`with TestClient(app) as client:` (login y todos los `GET`/`POST` posteriores dentro del mismo
bloque) — mantiene un único loop estable.

## Script de Inicio Rápido

```bash
./Start                    # Prod: down --remove-orphans + up -d --build + healthchecks
./scripts/start_dev.sh     # Dev: idem, con --env-file .env.dev incluido
```

## Consideraciones

1. **PostgreSQL**: no reconstruir postgres si hay datos importantes (usa volumen `postgres_data` / `postgres_dev_data`)
2. **Orden de inicio**: respetar dependencias definidas en compose
3. **Red**: cada stack tiene su propia red con subred `/24` explícita (`lasfocas_net` prod, `lasfocas_dev_net` dev) — nunca dejar el default `/16` de Docker
4. **Versiones**: nunca cambiar a `latest`, mantener versiones fijas
5. **`--env-file` obligatorio**: en todo comando `docker compose` manual sobre estos archivos (ver aviso arriba)
6. **Producción**: no bajar/recrear contenedores `lasfocas-*` sin autorización explícita y puntual del usuario
7. **Drift de red antes de `up` incremental**: comparar subred declarada vs. real antes de tocar un solo servicio de un stack ya corriendo (ver sección arriba)
8. **UID compartido en `base.Dockerfile`**: verificar colisiones con `useradd`/`USER` de los Dockerfiles hijos antes de tocar la imagen base (ver sección arriba)
9. **Contenedores `api`/`web`, mismo comando distinto `main.py`**: antes de un curl de verificación contra un endpoint de `web/app/main.py`, confirmar que se apunta a `lasfocasdev-web`, no a `lasfocasdev-api` (ver sección arriba)
10. **`scripts/` no está en ninguna imagen**: tras cualquier rebuild/recreate de `api`/`web`, `docker cp scripts <contenedor>:/app/scripts` antes de intentar correr un script vía `docker exec` (ver sección arriba)


## Script contra dev real desde el HOST (fuera de un contenedor)

Un script de mantenimiento (`scripts/*.py`) corrido directamente con el `.venv` del host (no vía `docker exec`) no puede resolver `POSTGRES_HOST=postgres` (nombre DNS interno del compose) y necesita las 4 variables explícitas para apuntar al puerto publicado de dev:

```bash
source .venv/bin/activate
POSTGRES_USER=FOCALBOT \
POSTGRES_PASSWORD="$(cat .secrets/Dev_db_password_v1.txt)" \
POSTGRES_HOST=localhost \
POSTGRES_PORT=5433 \
POSTGRES_DB=focas_dev \
python scripts/mi_script.py --dry-run
```

`.env`/`.env.dev` NO sirven para esto: `POSTGRES_PASSWORD` ahí es un placeholder que nunca se usa en runtime real (los contenedores arrancan con `POSTGRES_PASSWORD_FILE`, ver `docs/decisiones.md`), y sourcearlos con `source .env.dev` puede romper el shell si algún valor trae paréntesis o dos puntos sin comillas (ej. `SMTP_FROM_NAME`). El puerto real de Postgres dev (`5433`) y el nombre de la base (`focas_dev`, no `lasfocas`) están declarados en `deploy/docker-compose.dev.yml`/`.env.dev` — confirmar ahí si cambian.
