---
name: "las-focas-docker-rebuild"
description: "Usar cuando haya que reconstruir servicios Docker, refrescar imágenes o verificar un rebuild selectivo de LAS-FOCAS"
metadata:
  short-description: "Usar cuando haya que reconstruir servicios Docker, refrescar imágenes o verificar un rebuild selectivo de LAS-FOCAS"
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

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-docker-rebuild/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/docker-rebuild/SKILL.md

# Skill portable: docker-rebuild

> Fuente original: `.agentes-comunes/skills/docker-rebuild/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

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

## Correr el código de un worktree DENTRO de un contenedor, sin reconstruir la imagen

Para verificar contra Cromo o la base real **antes** de integrar (el host no tiene la config de Cromo:
`CromoConfigError` desde el `.venv`), copiar los paquetes del worktree a un directorio temporal del
contenedor y ponerlo primero en `PYTHONPATH`. Usado cuatro veces el 2026-09-29 (dry-run y apply de un
backfill, generación de trackings de punta a punta) sin tocar la imagen:

```bash
docker exec lasfocasdev-web sh -c 'rm -rf /tmp/wt && mkdir -p /tmp/wt'
tar cf - --exclude=__pycache__ core db scripts modules | docker exec -i lasfocasdev-web tar xf - -C /tmp/wt
docker exec -w /tmp/wt lasfocasdev-web sh -c 'PYTHONPATH=/tmp/wt:/app python scripts/<script>.py --dry-run'
docker exec lasfocasdev-web rm -rf /tmp/wt          # siempre al terminar
```

- **Copiar `modules/` también** si el código toca el bot o los workers: la imagen web no lo tiene en
  la ruta que espera `modules.slack_baneo_notifier...` (`ModuleNotFoundError` real).
- `web` no trae `scripts/` en la imagen: para un script ya commiteado alcanza con
  `docker cp scripts/<script>.py lasfocasdev-web:/tmp/`, y correrlo con `PYTHONPATH=/app`.
- Es para verificación: el contenedor sigue sirviendo su imagen. Después de integrar, reconstruir
  igual (ver "Verificar que el contenedor sirve TU código").
- Para prod, el mismo patrón sirve empaquetado en un script operativo que el usuario lanza con
  `nohup` desde la VM (precedente: `/home/support-focal-01/ingesta_prod_terceros_pon.sh`, cinco
  cargas de Cromo encadenadas, ~3 h).

## Rebuild desde un worktree: `env_file`/`secrets` relativos rotos

`deploy/docker-compose.dev.yml` referencia `env_file: [../.env.dev]` y `secrets: file: ../.secrets/...` **relativos al propio archivo compose**, no a lo que apunta el flag `--env-file` (ese flag sólo resuelve interpolación `${VAR}` dentro del yml, nada más). Un worktree de trabajo (`git worktree add`, ej. para `subagent-driven-development`) no tiene `.env.dev`/`.secrets/` propios — son gitignored, sólo existen en el checkout principal. `docker compose build` funciona igual desde el worktree (no los necesita), pero `docker compose up -d` falla con `env file .../worktree/.env.dev not found`.

**Fix**: antes de un `up -d` desde un worktree (no el checkout principal), crear symlinks temporales dentro del worktree apuntando al checkout principal (`ln -s /ruta/checkout/.env.dev .env.dev`, `ln -s /ruta/checkout/.secrets .secrets`) — ambos ya cubiertos por `.gitignore` (`.env.*`, `.secrets/`), confirmar con `git check-ignore` antes de dejarlos. Eliminarlos al terminar el rebuild, no dejarlos residuales en el worktree.

**Efecto colateral a esperar**: un `up -d <servicio1> <servicio2>` puntual puede recrear además `postgres` (u otro contenedor no pedido) por drift de config preexistente en la cadena de `depends_on` — no implica pérdida de datos (el volumen nombrado no se toca salvo `down -v`), pero conviene confirmar conteos reales de filas antes/después si el servicio recreado es la base de datos.

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

## El directorio `scripts/`: incluido en la imagen de `api`, no en la de `web`

**Actualizado 2026-09-29**: desde `a2d055a` (2026-08-26) `api/Dockerfile` hace `COPY scripts /app/scripts`, así que en `lasfocasdev-api` un script commiteado ya está disponible tras el rebuild (`docker exec lasfocasdev-api python scripts/<script>.py`, verificado con `scripts/api_clients.py`). `web/Dockerfile` sigue sin copiarlo: lo que sigue aplica a `lasfocasdev-web`, y a `api` sólo para un script **sin commitear** o si se lo quisiera correr contra una imagen anterior a esa fecha.

Hasta 2026-08-26 ninguna de las dos imágenes copiaba `scripts/`. Esto significaba que **tras cualquier `build` seguido de `up -d`/`up -d --force-recreate`**, el contenedor recreado NO tenía `/app/scripts` — aunque una sesión anterior lo haya copiado ahí a mano con `docker cp`, ese cambio vivía sólo en la capa *writable* del contenedor viejo y se pierde al recrearlo desde la imagen.

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
keyword argument 'modo'` — ese contenedor nunca se había reconstruido durante todo el ciclo (las
tareas previas verificaron contra DB real vía `pytest` desde el host, nunca vía `docker exec` dentro
del worker), así que corría una imagen de antes de que el parámetro `modo` existiera en el código.
Regla ampliada: antes de `docker exec` dentro de CUALQUIER contenedor para una acción real (no un
test), sin importar si "nunca dio problemas antes", chequear su fecha de build contra el último
commit relevante — el mismo comando de arriba, aplicado a ese contenedor puntual.

### Verificación real vía `TestClient` dentro de un contenedor: usar el context manager, no llamadas sueltas

Cuando no hay credenciales de admin disponibles para un `curl` autenticado real, el patrón de este
proyecto es entrar al contenedor ya reconstruido y usar `starlette.testclient.TestClient` contra la
app real, pegando al Postgres real (ver ejemplos en los reportes de las Tareas 5/7/8/9 del submódulo
ODFs). Si se hacen varias llamadas (`login` + varios `GET`) como sentencias sueltas del mismo script
(sin `with`), el motor async de SQLAlchemy puede terminar con
`RuntimeError: ... Future ... attached to a different loop` porque cada invocación de `TestClient`
sin contexto puede levantar su propio loop de `anyio`, mientras el pool de conexiones async queda
atado al loop de la primera. **Usar siempre `with TestClient(app) as client:`** (login y todos los
`GET`/`POST` posteriores dentro del mismo bloque `with`) — mantiene un único loop estable para toda
la sesión de verificación:

```python
import unittest.mock as mock
with mock.patch.object(app_module, "verify_password", return_value=True):  # sólo si no hay credenciales reales
    with TestClient(app_module.app) as client:
        client.post("/api/auth/login", json={"username": "<usuario_real_existente>", "password": "x"})
        r = client.get("/api/algun/endpoint/real")
```

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
10. **`scripts/` está en la imagen de `api` (desde 2026-08-26), no en la de `web`**: en `web`, tras cualquier rebuild/recreate, `docker cp scripts <contenedor>:/app/scripts` antes de correr un script vía `docker exec` (ver sección arriba)


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

## Curl real de verificación E2E contra `lasfocasdev-api`: usar la API key de DEV, no la de prod

El mismo patrón `Dev_`-prefix de arriba aplica a `api_key_v1`, no sólo a la DB: `lasfocasdev-api`
monta el Docker Secret `api_key_v1` con contenido real en `.secrets/Dev_api_key_v1.txt` — **distinto**
de `.secrets/api_key_v1.txt` (ese es el de prod, para `lasfocas-api`). Un curl real con
`Authorization: Bearer $(cat .secrets/api_key_v1.txt)` contra `http://localhost:8011/...` da `403
Credenciales inválidas` **silencioso** (no delata que el secreto es el equivocado, parece una API key
simplemente inválida). Confirmar siempre el secreto real montado antes de asumir cuál archivo host le
corresponde:

```bash
docker exec lasfocasdev-api cat /run/secrets/api_key_v1
# comparar contra:
cat .secrets/Dev_api_key_v1.txt
```

```bash
curl -s http://localhost:8011/servicios/detail?id=123 \
  -H "Authorization: Bearer $(cat .secrets/Dev_api_key_v1.txt)"
```

## Curl real de verificación E2E contra `/api/v1` (OAuth2): cliente de QA temporal

Las rutas `/api/v1/*` de `lasfocasdev-api` **no** aceptan la API key de arriba (401): piden un JWT de
OAuth2 `client_credentials` (ver `docs/api.md`, sección "API v1"). Receta usada el 2026-09-29 para
verificar los 6 endpoints v1. El secret nunca pasa por la terminal ni queda en disco al terminar:

```bash
SP=<scratchpad>; umask 077
docker exec lasfocasdev-api python scripts/api_clients.py crear --area "QA E2E <tarea>" \
  --scopes servicios:read cables:read > $SP/c.txt 2>/dev/null
CID=$(awk '/^client_id:/{print $2}' $SP/c.txt); CS=$(awk '/^client_secret:/{print $2}' $SP/c.txt)
T=$(curl -s -u "$CID:$CS" -d grant_type=client_credentials http://localhost:8011/api/v1/oauth/token \
    | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")
curl -s -H "Authorization: Bearer $T" http://localhost:8011/api/v1/servicios/93154/botellas
curl -s -G -H "Authorization: Bearer $T" --data-urlencode "cable=F-VIN-JDG (a instalar)" \
  http://localhost:8011/api/v1/cables/servicios              # nombres con espacios: --data-urlencode
docker logs lasfocasdev-api 2>&1 | grep -c -F -e "$CS" -e "$T"   # debe dar 0: ni secret ni token en logs
docker exec lasfocasdev-api python scripts/api_clients.py desactivar --client-id $CID
rm -f $SP/c.txt
```

- Probar también la revocación: el mismo `$T` tiene que dar 401 después de `desactivar`.
- Para probar un scope faltante, crear un segundo cliente con un solo scope (`--scopes servicios:read`)
  y confirmar el 403 en `/api/v1/cables/*`.
- Los clientes de QA quedan **inactivos** en `app.api_clients` (no se borran). Listarlos con
  `api_clients.py listar`.

## Ventana de mantenimiento con restore de datos + rebuild de código: reconstruir el código PRIMERO

Hallazgo real (2026-09-07, sincronización main/prod, ver `docs/decisiones.md`): si una ventana de
mantenimiento combina (a) un `pg_restore`/migración que cambia el esquema y (b) un rebuild de las
imágenes con código nuevo, hacer (a) antes que (b) deja una ventana donde el código VIEJO corre contra
el esquema NUEVO — cualquier script de reconciliación/dominio que se ejecute ahí (ej. vía
`docker exec` reusando el código ya desplegado, patrón de `baneo-qa-real`) puede fallar en silencio o
de forma sutil si ese código no conoce columnas/tablas que el restore acaba de traer.

**Orden correcto:** parar la capa de aplicación (dejar sólo `postgres` arriba) → backup → restore del
esquema/datos nuevo → **rebuild + `up` completo del stack con el código nuevo** → recién ahí correr
cualquier script de reconciliación de dominio, ya con código y esquema coherentes entre sí.

## Config operativa dependiente de ambiente no se resetea sola tras un restore

Hallazgo real (2026-09-07, listener de baneos Slack en prod tras la sincronización main/prod): copiar
la base de dev a prod trae también las filas de tablas de configuración operativa (`app.config_servicios`
y similares) con los valores del AMBIENTE DE ORIGEN — canal de Slack de prueba, `workflow_id` de dev —
en vez de los reales de producción. El proceso arranca sano (conexión Socket Mode viva, healthcheck
OK) y el fallo es 100% silencioso: el canal/`workflow_id` real nunca matchea el configurado, así que
ningún evento llega ni siquiera a loguearse a nivel INFO. Sin un smoke test real (un mensaje real a
través del canal real), este tipo de bug pasa desapercibido indefinidamente — esto es exactamente lo
que la sesión anterior había diferido como "smoke test pendiente".

**Antes de dar por cerrada una ventana que copió la base de dev a prod:** auditar toda fila de
configuración operativa con valores dependientes de ambiente (IDs de canal, `workflow_id`, URLs de
webhook, etc. — no sólo `slack_ingreso_listener`) contra los valores reales de producción, y hacer el
smoke test real end-to-end del canal externo (Slack u otro) ANTES de cerrar la ventana — nunca como
pendiente diferido a la próxima sesión.

## Verificar que el contenedor sirve TU código, no uno stale

Hallazgo real repetido (2026-09-08/09, gestor de Servicios sin ODF): un rebuild que "salió bien" no
prueba que el contenedor esté sirviendo el código de la rama actual, y los tests in-process
(`TestClient`) nunca lo detectan porque no pasan por el contenedor. Tres técnicas usadas en esa sesión,
cada una con evidencia concluyente — elegir la que aplique al cambio:

**Rutas nuevas de FastAPI** — probar que la ruta estaba AUSENTE antes del rebuild y PRESENTE después,
no sólo que responde ahora:

```bash
# Pre-rebuild: la ruta no debe existir en el router del contenedor viejo.
# Ojo con la ruta de import: dentro de lasfocasdev-web es `app.main`, no `web.app.main`.
docker exec lasfocasdev-web python -c "
from app.main import app
print([r.path for r in app.router.routes if 'mi-ruta-nueva' in r.path])"

# Post-rebuild: un 401/403 sin cookie ya prueba que la ruta existe y está cableada.
# Un 404/405 significa que quedó mal registrada (ver el bug de orden de rutas de FastAPI).
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:<puerto>/api/<ruta-nueva>
```

**Cambios de frontend** — comparar el hash del bundle servido contra el build local, y grepear el chunk
servido por un literal introducido por el cambio (un string de UI, un nombre de handler):

```bash
curl -s http://localhost:<puerto>/ | grep -o 'index-[a-z0-9]*\.js'   # hash servido
ls web/frontend/dist/assets/index-*.js                               # hash local
curl -s http://localhost:<puerto>/assets/index-<hash>.js | grep -c '<literal-del-cambio>'
```

**Cambios de backend sin ruta nueva** — grepear el símbolo o el fragmento de SQL nuevo dentro del
contenedor:

```bash
docker exec lasfocasdev-web grep -c '<simbolo-o-fragmento-sql-nuevo>' /app/<ruta-del-modulo>
```

Regla: si no podés mostrar evidencia de que el contenedor tiene tu código, cualquier verificación E2E
contra él no prueba nada sobre tu cambio.

## Una capacidad nueva en un contenedor viejo puede necesitar config que ese contenedor nunca tuvo

Hallazgo real (2026-09-28, comando `@bot track` de Slack): el código nuevo pasó 25 tests propios y la
suite completa (2169 passed), se integró a `dev` y el contenedor se reconstruyó correctamente — y la
primera ejecución real adentro murió igual, con
`CromoConfigError: Configuración de Cromo incompleta. Definir CROMO_PASSWORD (o secreto
cromo_password_v1)`. Causa: se le agregó al `slack_baneo_worker` una capacidad que **habla con un
sistema externo nuevo para ese servicio**, y ese servicio nunca había montado
`cromo_password_v1` en `deploy/docker-compose.dev.yml` ni en `deploy/compose.yml` (sí lo montaban
`web` y `cromo_worker`). El resto de la config de Cromo (`CROMO_BASE_URL`, `CROMO_USER`, …) ya le
llegaba por `env_file`: faltaba **sólo** el secreto.

**Ningún test puede detectarlo.** Los del handler mockean la capa que necesita la credencial; los del
servicio corren desde el host con el `.venv`, que tiene otro entorno. Sólo aparece ejecutando dentro
del contenedor real — y el healthcheck sigue en verde, porque el proceso arranca igual: falla recién
en la primera invocación del comando.

**Regla**: cuando una capacidad nueva hace que un servicio hable con un sistema externo (Cromo, PROV,
Slack, SMTP…) que ese servicio **no usaba antes**, comparar su bloque `secrets:`/`environment:` en el
compose contra el de un servicio que sí lo usa, **antes** de dar por cerrado el cambio:

```bash
# ¿Qué secretos monta cada servicio? Compará el que tocaste contra el que ya habla con ese sistema.
python3 - <<'PY'
import re, pathlib
s = pathlib.Path('deploy/docker-compose.dev.yml').read_text()
for m in re.finditer(r"\n  ([a-z_-]+):\n(.*?)(?=\n  [a-z_-]+:\n)", s, re.S):
    secretos = re.findall(r"^\s+- (\w+_v\d+)$", m.group(2), re.M)
    print(f"{m.group(1):28} {secretos}")
PY

# Y confirmalo en el contenedor ya recreado, no en el yml:
docker exec <contenedor> ls /run/secrets/
```

Aplicar el arreglo a **dev y prod en el mismo cambio**: el faltante es idéntico en los dos composes y
diferirlo garantiza el mismo error en el despliegue.
