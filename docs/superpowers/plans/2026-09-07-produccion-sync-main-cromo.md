# Sincronización de producción con `dev` + corte de datos Cromo — Plan de Implementación

> **Para ejecutores agénticos:** Este NO es un plan de feature con TDD — es un runbook de despliegue a producción con pasos irreversibles (push a `main`, borrado de rama, reemplazo total de datos en `lasfocas` prod, downtime real). SUB-SKILL recomendada: **`superpowers:executing-plans`** (ejecución en esta sesión con checkpoints), NO `subagent-driven-development` — los pasos con 🛑 requieren confirmación explícita del usuario en el momento, no pueden delegarse a un subagente que no puede parar a preguntar. Cada tarea usa `- [ ]` para tracking.

**Goal:** Llevar `main` al día con `dev` (238 commits), reconstruir y desplegar el stack completo de contenedores de producción (`lasfocas-*`) con ese código, y reemplazar los datos operativos de producción por el dataset de `dev` (ODFs/Botellas/Servicios/Cables/Cromo) preservando únicamente los baneos reales activos de producción.

**Architecture:** (A) Cambios de código sobre rama efímera → `dev` → PR `dev`→`main`. (B) Preparación de secrets/config de prod. (C) Ventana de mantenimiento única: backup → snapshot de baneos reales → `pg_restore` del dump de `dev` sobre `lasfocas` → reconciliación de baneos vía funciones de dominio (nunca `UPDATE` directo) → rebuild+up del stack completo → verificación end-to-end. (D) Documentación y cierre de la rama `fix-baneos-hermanos-prod`, ahora redundante.

**Tech Stack:** Docker Compose v2, PostgreSQL 16 (`pg_dump`/`pg_restore` formato custom `-F c`), Alembic, FastAPI, Vue 3, Redis 7.4, `gh` CLI para el PR.

**Spec:** No hay spec previa — este plan nace de la investigación registrada en `docs/decisiones.md` (entradas 2026-09-03) y de la conversación que originó este documento. Las decisiones de producto ya están tomadas por el usuario (ver "Decisiones ya tomadas" abajo); este plan las ejecuta.

## Decisiones ya tomadas (no volver a preguntar)

1. **Datos Cromo en prod:** copiar el dataset completo de `dev` (`focas_dev`, 941 MB) a prod, **excepto** los baneos: los únicos datos que persisten desde prod son los baneos reales activos; todo lo demás (ODFs, Botellas, Servicios, Cables, Cromo) viene de `dev`.
2. **Credenciales Cromo:** misma cuenta real que ya usa `dev` — se copia el secret, no se gestiona una cuenta nueva.
3. **Rama `fix-baneos-hermanos-prod`:** se cierra/borra una vez confirmado que sus 2 fixes ya están nativos en el `main` post-merge.
4. **PROV en prod:** este despliegue incluye la provisión de credenciales reales de PROV para producción (el usuario las aporta; no se inventan).

## Global Constraints

- Nunca `UPDATE`/`DELETE` SQL directo sobre datos de baneo/estado en prod — siempre vía las funciones de dominio ya desplegadas (`aplicar_estado_a_grupo`, `ProtectionService`), igual que en las remediaciones previas de 2026-08-28 y 2026-09-03.
- Ninguna contraseña/secreto como argumento de shell ni impreso en la salida de un comando.
- `git push origin main` sólo con confirmación explícita del usuario en el momento — no autorizado por adelantado.
- Cualquier archivo de producción (`deploy/compose.yml`, `.env`, `.secrets/`) requiere aprobación explícita antes de aplicarse contra el host real, y debe documentarse en `docs/decisiones.md`.
- Antes de cualquier operación que pueda descartar datos: backup verificado primero, sin excepción.
- Antes de tocar prod: `docker ps` para confirmar el estado real de los contenedores, no asumir.

---

## Parte A — Código: cerrar la brecha `main` vs `dev` vs `deploy/compose.yml`

### Task 1: Agregar `cromo_worker` y los secrets de Cromo/PROV a `deploy/compose.yml` (el compose de PROD)

`deploy/compose.yml` es el archivo versionado que usa producción. Hoy (verificado leyendo el archivo en la rama actual, que parte de `dev`) ya tiene `redis`, `docker-socket-proxy`, `botellas_recalculo_worker` y `pgadmin` — pero **le falta el servicio `cromo_worker` completo** y los secrets `api_prov_user_v1`/`api_prov_pass_v1` (en `api`) y `cromo_password_v1` (en `web`), que sólo están en `deploy/docker-compose.dev.yml`.

**Files:**
- Modify: `deploy/compose.yml`

**Interfaces:**
- Produce: servicio `cromo_worker` (puerto interno 8096, healthcheck `/health`) y 3 secrets nuevos disponibles para `api`/`web` en prod. Task 11 depende de que este servicio exista para poder levantarlo.

- [x] **Paso 1: Crear rama efímera desde `dev`**

```bash
git fetch origin
git checkout -b chore/prod-compose-cromo-prov origin/dev
```

- [x] **Paso 2: Agregar los 2 secrets nuevos a `api.secrets` (después de línea 68, `- slack_app_token_v1`)**

```yaml
    secrets:
      - api_key_v1
      - db_password_v1
      - smtp_password_v1
      - slack_bot_token_v1
      - slack_app_token_v1
      - api_prov_user_v1
      - api_prov_pass_v1
```

- [x] **Paso 3: Agregar `cromo_password_v1` a `web.secrets` (después de línea 151, `- redis_password_v1`)**

```yaml
    secrets:
      - api_key_v1
      - db_password_v1
      - web_secret_key_v1
      - smtp_password_v1
      - slack_bot_token_v1
      - slack_app_token_v1
      - redis_password_v1
      - cromo_password_v1
```

- [x] **Paso 4: Insertar el servicio `cromo_worker` completo** (después del bloque `slack_baneo_worker`, antes de `botellas_recalculo_worker` — mismo lugar relativo que en `docker-compose.dev.yml`), adaptado a nombres de prod (sin sufijo `dev`, red `lasfocas_net`, `env_file: ../.env`, logs en `../Logs` no `../Logs/dev`):

```yaml
  cromo_worker:
    build:
      context: ..
      dockerfile: deploy/docker/cromo_worker.Dockerfile
    container_name: lasfocas-cromo-worker
    user: "1001:1001"
    env_file:
      - ../.env
    environment:
      POSTGRES_HOST: postgres
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      LOGS_DIR: /app/Logs
      TZ: America/Argentina/Buenos_Aires
      APP_TIMEZONE: America/Argentina/Buenos_Aires
    secrets:
      - db_password_v1
      - cromo_password_v1
      - redis_password_v1
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    expose:
      - "8096"
    volumes:
      - ../Logs:/app/Logs
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8096/health"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - lasfocas_net
```

- [x] **Paso 5: Agregar los 3 secrets nuevos al bloque `secrets:` final (después de `redis_password_v1`, línea ~389), sin prefijo `Dev_`**

```yaml
  cromo_password_v1:
    file: ../.secrets/cromo_password_v1.txt
  api_prov_user_v1:
    file: ../.secrets/api_prov_user_v1.txt
  api_prov_pass_v1:
    file: ../.secrets/api_prov_pass_v1.txt
```

- [x] **Paso 6: Validar sintaxis (sin tocar contenedores reales)**

```bash
docker compose -f deploy/compose.yml --env-file .env config --quiet && echo "OK: compose.yml de prod es válido"
```
Expected: `OK: compose.yml de prod es válido` — falla si YAML mal indentado o faltan `${VAR}` no definidas. Nota: fallará por secrets faltantes recién en Task 5, `config` no valida que los archivos de secrets existan.

- [x] **Paso 7: Commit**

```bash
git add deploy/compose.yml
git commit -m "chore(deploy): agrega cromo_worker y secrets Cromo/PROV al compose de producción"
git push -u origin chore/prod-compose-cromo-prov
```

Esta rama se integra a `dev` por el flujo normal (`cierre-sesion` o `superpowers:finishing-a-development-branch`) **antes** de la Task 3 (merge `dev`→`main`), para que el PR a `main` ya incluya este cambio.

---

### Task 2: Registrar la decisión en `docs/decisiones.md`

**Files:**
- Modify: `docs/decisiones.md`

- [x] **Paso 1: Agregar entrada nueva al final del archivo**, siguiendo el formato de las entradas existentes (fecha, contexto, decisión, consecuencias). Contenido mínimo a incluir:
  - Que `main` estaba congelado en `657b239` (2026-07-29) mientras prod corría desde un commit compuesto de `dev` (`dc1a4a4`+`c2c1d70`) nunca mergeado.
  - La decisión de cerrar la brecha con un único PR `dev`→`main`.
  - La decisión de reemplazar los datos operativos de prod por el dataset de `dev`, preservando sólo baneos activos reales.
  - Referencia a este plan: `docs/superpowers/plans/2026-09-07-produccion-sync-main-cromo.md`.

- [x] **Paso 2: Commit en la misma rama de Task 1 o en una rama `docs/` separada si ya se cerró Task 1**

```bash
git add docs/decisiones.md
git commit -m "docs(decisiones): registra el plan de sincronizacion main/prod y corte de datos Cromo"
```

---

### Task 3: Merge `dev` → `main` vía PR

🛑 **PUNTO DE CONTROL — requiere confirmación explícita del usuario antes de mergear.** `git push origin main` está prohibido por defecto (`.agentes-comunes/skills/dev-workflow/SKILL.md`).

**Pre-requisito:** Task 1 ya integrada a `dev` (verificar `git log origin/dev` incluye el commit de `chore/prod-compose-cromo-prov`).

- [ ] **Paso 1: Confirmar que `dev` está verde antes de proponer el PR**

```bash
git fetch origin
git log --oneline main..origin/dev | wc -l   # debe ser > 238 (Task 1 lo suma)
gh run list --branch dev --limit 5           # confirmar CI en verde en el último commit de dev
```

- [ ] **Paso 2: Revisión dirigida (no línea por línea de 468+ archivos)** — el volumen es demasiado grande para revisión exhaustiva; enfocar la revisión en lo que puede romper producción:

```bash
git diff main origin/dev -- deploy/compose.yml deploy/docker/ api/Dockerfile web/Dockerfile office_service/Dockerfile
git diff main origin/dev -- db/alembic/versions/ | grep -E '^\+\+\+|^diff'
git diff main origin/dev -- deploy/env.sample deploy/env.dev.sample
```
Confirmar: no hay downgrade destructivo en las 16 migraciones nuevas, ninguna borra columnas con datos reales sin backfill, los Dockerfiles no reintroducen usuario root.

- [ ] **Paso 3: Crear el PR**

```bash
gh pr create --base main --head dev \
  --title "Sincroniza main con dev (238+ commits): Cromo, Infra, Servicios/PROV, seguridad" \
  --body "$(cat <<'EOF'
## Resumen
main estaba congelado desde 2026-07-29 mientras produccion corria desde un commit de dev nunca mergeado (ver docs/decisiones.md, entrada 2026-09-03 y la nueva entrada de este plan). Este PR cierra la brecha trayendo dev completo a main.

## Contenido principal
- Modulo Cromo completo (ingesta, worker, verificador, jerarquia Camara->Botella, consolidacion de duplicados, ODFs)
- Infra: subred Docker /24, docker-socket-proxy + usuarios no-root, Redis + worker de recalculo
- Servicios: integracion PROV, timeline, historial de IDs, categoria
- 16 migraciones Alembic nuevas
- Fixes de baneos hermanos e ingreso/egreso real desde Slack

## Plan de despliegue
Ver docs/superpowers/plans/2026-09-07-produccion-sync-main-cromo.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Paso 4: 🛑 Esperar aprobación explícita del usuario para mergear.** No ejecutar el merge hasta recibirla en el momento.

- [ ] **Paso 5: Mergear (merge commit, no squash — preservar historia de 238+ commits)**

```bash
gh pr merge --merge --delete-branch=false
```

- [ ] **Paso 6: Verificar**

```bash
git fetch origin
git log -1 origin/main --format='%H %ci'
git log -1 origin/dev --format='%H %ci'
# Ambos hash deben coincidir
```
Expected: mismo commit hash en `origin/main` y `origin/dev`.

---

### Task 4: Cerrar la rama `fix-baneos-hermanos-prod`

🛑 **PUNTO DE CONTROL — confirmar con el usuario antes de borrar** (operación destructiva, protocolo de seguridad de git).

**Pre-requisito:** Task 3 completada.

- [ ] **Paso 1: Confirmar que sus 2 fixes ya son ancestros del nuevo `main`**

```bash
git merge-base --is-ancestor 041f46d origin/main && echo "OK: fix Cromo en get_camaras_for_servicio presente"
git merge-base --is-ancestor 99a2306 origin/main && echo "OK: fix reconciliacion baneos hermanos presente"
```
Expected: ambos imprimen `OK`. Si alguno falla, **NO borrar la rama** — investigar por qué el commit no llegó antes de continuar.

- [ ] **Paso 2: 🛑 Confirmar con el usuario, luego borrar**

```bash
git push origin --delete fix-baneos-hermanos-prod
git branch -D fix-baneos-hermanos-prod 2>/dev/null || true
```

---

## Parte B — Preparación de secrets y config de prod (sin tocar contenedores todavía)

### Task 5: Generar/copiar los secrets de prod faltantes

**Files:**
- Create: `.secrets/redis_password_v1.txt`
- Create: `.secrets/cromo_password_v1.txt`
- Create: `.secrets/api_prov_user_v1.txt`, `.secrets/api_prov_pass_v1.txt`
- (Opcional) Create: `.secrets/pgadmin_password_v1.txt` — sólo si se quiere levantar pgAdmin en prod; no bloquea el `up -d` base porque está bajo `profiles: ["pgadmin"]`.

- [ ] **Paso 1: `redis_password_v1` — generar nuevo (nunca reusar el de dev)**

```bash
cd /home/support-focal-01/LAS-FOCAS
umask 077
openssl rand -base64 32 > .secrets/redis_password_v1.txt
chmod 600 .secrets/redis_password_v1.txt
```

- [ ] **Paso 2: `cromo_password_v1` — copiar el mismo valor real que usa dev (decisión ya tomada: misma cuenta)**

```bash
install -m 600 .secrets/Dev_cromo_password_v1.txt .secrets/cromo_password_v1.txt
```

- [ ] **Paso 3: `api_prov_user_v1` / `api_prov_pass_v1` — credenciales REALES de PROV para producción**

🛑 Estas credenciales no se pueden generar ni copiar de dev (dev usa credenciales de dev/sandbox). **Requiere que el usuario las aporte en el momento** (nunca pedirlas ni pegarlas como argumento de shell):

```bash
umask 077
cat > .secrets/api_prov_user_v1.txt   # pegar el usuario real de PROV prod, luego Ctrl-D
cat > .secrets/api_prov_pass_v1.txt   # pegar la contraseña real de PROV prod, luego Ctrl-D
chmod 600 .secrets/api_prov_user_v1.txt .secrets/api_prov_pass_v1.txt
```

- [ ] **Paso 4: Verificar (sin imprimir valores)**

```bash
ls -la .secrets/redis_password_v1.txt .secrets/cromo_password_v1.txt .secrets/api_prov_user_v1.txt .secrets/api_prov_pass_v1.txt
# Todos deben existir, modo 600, tamaño > 0
```

---

### Task 6: Actualizar `.env` de producción con las variables nuevas

**Files:**
- Modify: `.env` (raíz, gitignored — no se commitea)

Diff de claves confirmado por comparación directa de nombres (no valores) entre `.env` y `.env.dev`. Copiar verbatim el valor de `.env.dev` salvo donde se indica lo contrario.

- [ ] **Paso 1: Backup del `.env` actual**

```bash
cp .env .env.bak-$(date +%Y%m%d-%H%M%S)
```

- [ ] **Paso 2: Agregar a `.env` (copiando el valor real desde `.env.dev`, con las excepciones marcadas)**

```
CHAT_UPLOAD_MAX_BYTES=<mismo valor que .env.dev>
CROMO_BASE_URL=<mismo valor que .env.dev — misma cuenta/host real>
CROMO_CLIENT_ID=<mismo valor que .env.dev>
CROMO_OAUTH_URL=<mismo valor que .env.dev>
CROMO_PSIZE_DEFAULT=<mismo valor que .env.dev>
CROMO_TIMEOUT=<mismo valor que .env.dev>
CROMO_USER=<mismo valor que .env.dev>
INFRA_SHEET_ID=<mismo valor que .env.dev>
INFRA_SHEET_NAME=<mismo valor que .env.dev>
INTENT_ACTION_PROVIDER=<mismo valor que .env.dev>
INTENT_ACTIONS_ENABLED=<mismo valor que .env.dev>
INTENT_CLARIFY_PROVIDER=<mismo valor que .env.dev>
INTENT_DOMAIN_CLASSIFIER=<mismo valor que .env.dev>
INTENT_ENABLE_ANSWERS=<mismo valor que .env.dev>
INTENT_MAX_ANSWER_CHARS=<mismo valor que .env.dev>
LOG_RAW_TEXT=false
MAPS_LIGHTWEIGHT=true
OFFICE_ENABLE_UNO=<mismo valor que .env.dev>
OFFICE_LOG_LEVEL=INFO
OFFICE_SERVICE_BASE=http://office:8090
OFFICE_SOFFICE_CONNECT_HOST=<mismo valor que .env.dev>
OFFICE_SOFFICE_PORT=<mismo valor que .env.dev>
PGADMIN_EMAIL=<mismo valor que .env.dev — sólo se usa si se levanta el profile pgadmin>
PROV_BASE_URL=<mismo valor que .env.dev — es el endpoint real de PROV, no cambia entre entornos>
REPORTS_API_BASE=http://api:8000
REPORTS_API_TIMEOUT=<mismo valor que .env.dev>
REPORTS_DIR=/app/data/reports
REP_TEMPLATE_PATH=<mismo valor que .env.dev>
SLA_TEMPLATE_PATH=<mismo valor que .env.dev>
SOFFICE_BIN=<mismo valor que .env.dev>
TEMPLATES_DIR=/app/Templates
UPLOADS_DIR=/app/data/uploads
WEB_CHAT_ALLOWED_ORIGINS=<mismo valor que .env.dev>
WEB_INFERRED_ORIGIN=http://172.18.208.162:8080
```

Notas explícitas sobre las excepciones (NO copiar literal de `.env.dev` en estas 4 claves — usar el valor de prod):
- `OFFICE_SERVICE_BASE`: apuntar al hostname del servicio en la red de prod (`office`), no al de dev.
- `WEB_INFERRED_ORIGIN`: la IP/puerto público real de prod (`172.18.208.162:8080`), no `localhost`.
- `REPORTS_API_BASE`: hostname del servicio api en prod (`api:8000`).
- `OLLAMA_URL`: **no copiar** — `LLM_PROVIDER` en prod ya está en `heuristic`/lo que corresponda; si prod no corre Ollama, dejar sin definir (el proveedor heurístico no lo usa). Verificar `LLM_PROVIDER` actual en `.env` antes de decidir.

- [ ] **Paso 3: Corregir la anomalía `ENV`/`LOG_LEVEL` detectada** (prod actualmente tiene `ENV=development` y `LOG_LEVEL=DEBUG`, inconsistente con ser producción):

```
ENV=production
LOG_LEVEL=INFO
```

- [ ] **Paso 4: 🛑 Mostrar el diff completo al usuario antes de continuar** (archivo de producción, requiere aprobación explícita):

```bash
diff .env.bak-*(N) .env   # o comparar contra el backup del paso 1
```

---

## Parte C — Ventana de mantenimiento (contra contenedores y datos reales)

🛑 **Ejecutar las Tasks 7 a 12 en una única ventana continua**, sin intercalar otro trabajo, para minimizar drift entre el snapshot de baneos (Task 8) y la restauración (Task 9). Avisar downtime esperado (~10-15 min, más servicios que el precedente de sólo-redis documentado en `docs/mantenimiento_redes_produccion.md`) antes de empezar.

⚠️ **Todo lo que se exporte en esta parte (dumps, snapshots de baneos, nombres crudos de cámaras) va a `$BACKUP_DIR`, FUERA del árbol del repo** — `.gitignore` sólo cubre `*.dump`/`backup_*.dump`, no `.json`/`.txt`/`.tsv`, así que un `./backups/` dentro del repo arriesga que datos operativos reales (nombres de técnicos, ubicaciones) terminen en un `git add -A` sin querer. Definir una sola vez al arrancar la ventana:

```bash
export BACKUP_DIR=~/lasfocas-prod-sync-$(date +%Y%m%d)
mkdir -p "$BACKUP_DIR"
```

### Task 7: Backup completo de la base de prod

**Files:** ninguno versionado — el dump sale a `$BACKUP_DIR`, fuera del repo.

- [ ] **Paso 1: Detener el tráfico de escritura de la capa de aplicación (dejar `postgres` arriba)**

```bash
cd /home/support-focal-01/LAS-FOCAS
docker compose -f deploy/compose.yml --env-file .env stop api web bot nlp_intent office slack_baneo_worker botellas_recalculo_worker 2>&1
docker ps --filter name=lasfocas- --format '{{.Names}}\t{{.Status}}'
```
Expected: sólo `lasfocas-postgres` (y `lasfocas-docker-socket-proxy`, sin efecto) quedan `Up`.

- [ ] **Paso 2: Dump completo de prod ANTES de tocar nada**

```bash
docker exec lasfocas-postgres pg_dump -U lasfocas -d lasfocas -F c --no-owner --no-acl \
  -f /tmp/prod_backup_pre_sync_$(date +%Y%m%d_%H%M%S).dump
# Capturar el nombre exacto generado dentro del contenedor
BACKUP_NAME=$(docker exec lasfocas-postgres sh -c 'ls -t /tmp/prod_backup_pre_sync_*.dump | head -1')
docker cp "lasfocas-postgres:$BACKUP_NAME" "$BACKUP_DIR/"
ls -la "$BACKUP_DIR/"
```

- [ ] **Paso 3: Verificar integridad del dump (listar contenido sin restaurar)**

```bash
docker exec lasfocas-postgres pg_restore -l "$BACKUP_NAME" | head -20
# Debe listar TABLE DATA para app.camaras, app.incidentes_baneo, etc. — si está vacío o falla, DETENERSE aquí.
```

---

### Task 8: Snapshot de los baneos reales activos de prod (antes de reemplazar los datos)

**Files:**
- Create (no versionado, temporal): `/tmp/prod_baneos_snapshot.json` dentro de `lasfocas-web`

- [ ] **Paso 1: Escribir el script de snapshot** (uso único, no se commitea) en el host y copiarlo al contenedor:

```python
# /tmp/snapshot_baneos_prod.py — ejecutar DENTRO de lasfocas-web (PYTHONPATH=/app)
# Exporta los incidentes de baneo activos con claves de negocio estables (no IDs seriales,
# que van a cambiar tras restaurar el dump de dev), para poder reaplicarlos después.
import json
from app.db.session import SessionLocal
from app.db.models.infra import IncidenteBaneo, Camara
from sqlalchemy import select

db = SessionLocal()
incidentes = db.execute(
    select(IncidenteBaneo).where(IncidenteBaneo.estado == "activo")
).scalars().all()

out = []
for inc in incidentes:
    out.append({
        "servicio_protegido": inc.servicio_protegido,
        "ruta": inc.ruta,
        "camaras_nombres": [c.nombre for c in inc.camaras],  # ajustar al nombre real de la relación
        "creado_en": inc.creado_en.isoformat() if inc.creado_en else None,
        "usuario": inc.usuario,
        "motivo": getattr(inc, "motivo", None),
    })

with open("/tmp/prod_baneos_snapshot.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)

print(f"Snapshot: {len(out)} incidentes activos exportados")
db.close()
```

⚠️ Antes de ejecutar: leer `web/app/db/models/infra.py` (o donde viva `IncidenteBaneo`) en el contenedor real para confirmar los nombres exactos de campos/relaciones — el snippet de arriba es la forma, no necesariamente los nombres exactos de atributos actuales del modelo. Ajustar antes de correr.

- [ ] **Paso 2: Copiar y ejecutar dentro del contenedor real**

```bash
docker cp /tmp/snapshot_baneos_prod.py lasfocas-web:/tmp/snapshot_baneos_prod.py
docker exec -e PYTHONPATH=/app -w /app lasfocas-web python3 /tmp/snapshot_baneos_prod.py
docker cp lasfocas-web:/tmp/prod_baneos_snapshot.json "$BACKUP_DIR/"
```

- [ ] **Paso 3: Revisar el conteo con el usuario antes de seguir**

```bash
python3 -c "import json; d=json.load(open('$BACKUP_DIR/prod_baneos_snapshot.json')); print(f'{len(d)} incidentes activos')"
```
🛑 Confirmar que este número coincide con lo que el usuario espera ver como "baneos reales activos hoy" antes de continuar a Task 9.

---

### Task 8b: Exportar las Cámaras `PENDIENTE_REVISION` legado antes de que el restore las borre

Flujo legacy (retirado del código el 2026-08-11, reemplazado por `app.ingresos_sin_match`, pero **prod sigue en `20260810_01` y el listener viejo sigue auto-creándolas**): cuando un técnico anunciaba un ingreso/egreso y el texto no matcheaba ninguna Cámara existente, el sistema creaba una `Camara` placeholder con `estado='PENDIENTE_REVISION'` cuyo campo `nombre` es literalmente el texto crudo tal cual lo escribió el técnico (sin normalizar — conserva incluso el markup de links de Slack). No hay un campo `nombre_original` separado: `camaras.nombre` **es** el crudo mientras la fila está en este estado.

Esto es urgente hacerlo **ya, no en la ventana de mantenimiento**: `dev` tiene **0 filas** en este estado (el flujo ya no existe ahí), así que el Task 9 (`pg_restore --clean` de `dev` sobre `lasfocas`) borra estas 582 filas sin dejar rastro. Además la lista crece todos los días mientras prod siga con el código viejo (565 el 2026-09-03 → 582 hoy, últimas del 2026-09-05), así que conviene re-correr el export inmediatamente antes de ejecutar Task 9 el día real del corte, no confiar sólo en el de hoy.

**Files (en `$BACKUP_DIR`, fuera del repo — ver advertencia al inicio de Parte C):**
- Create: `camaras_pendiente_revision_prod.txt` — un nombre crudo por línea, para el chequeo de formato de anuncios de técnicos.
- Create: `camaras_pendiente_revision_prod_con_trazabilidad.tsv` — mismo contenido + `id`/`last_update`, por si hace falta cruzar después con Slack.

- [ ] **Paso 1: Exportar (sólo lectura, no borra nada todavía)**

```bash
docker exec lasfocas-postgres psql -U lasfocas -d lasfocas -t -A -c \
  "SELECT nombre FROM app.camaras WHERE estado = 'PENDIENTE_REVISION' ORDER BY id;" \
  > "$BACKUP_DIR/camaras_pendiente_revision_prod.txt"

docker exec lasfocas-postgres psql -U lasfocas -d lasfocas -t -A -F $'\t' -c \
  "SELECT id, last_update, nombre FROM app.camaras WHERE estado = 'PENDIENTE_REVISION' ORDER BY id;" \
  > "$BACKUP_DIR/camaras_pendiente_revision_prod_con_trazabilidad.tsv"

wc -l "$BACKUP_DIR/camaras_pendiente_revision_prod.txt"
```
Expected (medido el 2026-09-07 — ver "Ya ejecutado" más abajo): 582 líneas. Puede ser mayor el día real del corte, por eso re-correr este paso en la ventana real, no reusar sólo el de hoy.

**Ya ejecutado hoy (2026-09-07), fuera de la ventana de mantenimiento, porque es de sólo lectura y la lista crece día a día:** los 2 archivos ya están en `/tmp/claude-1001/-home-support-focal-01-LAS-FOCAS/cd7980c2-961c-44c9-8299-60d8f5b61b2b/scratchpad/` (582 líneas). Es un snapshot preliminar para arrancar el chequeo de formato ya mismo; igual hay que re-exportar el día del corte real antes de Task 9.

- [ ] **Paso 2: Chequeo de formato de anuncios de técnicos** (el motivo del export) — comparar estos 582 nombres crudos contra los nombres reales de Cámaras en `dev`/Cromo, para medir qué porcentaje matchea y detectar patrones de formato que el matching actual no contempla. Este análisis queda a criterio de quien lo revise; no es parte de la migración en sí.

- [ ] **Paso 3: Borrado** — no requiere un DELETE manual: estas 582 filas desaparecen como efecto natural del `pg_restore --clean` de Task 9 (dev no las tiene). Si por algún motivo el corte de Task 9 se pospone o se cancela y de todas formas se quiere limpiar esto antes, **no usar `DELETE` directo** — coordinar por separado, ya que hay que confirmar que ninguna de esas 582 filas tiene FKs activas (ingresos, incidentes) antes de borrarlas fuera del contexto del restore completo.

---

### Task 9: 🛑 Restaurar el dataset de `dev` sobre la base de datos de prod

🛑🛑 **PUNTO DE NO RETORNO. Confirmar explícitamente con el usuario, con el backup de Task 7 ya verificado, antes de ejecutar este paso.** Esto reemplaza TODAS las tablas de `app.*` en `lasfocas` (prod) por el contenido de `focas_dev` (dev), incluyendo temporalmente los baneos de dev (que Task 10 corrige inmediatamente después).

- [ ] **Paso 1: Confirmar tamaño y estado de origen/destino una última vez**

```bash
docker exec lasfocasdev-postgres psql -U FOCALBOT -d focas_dev -c "SELECT pg_size_pretty(pg_database_size('focas_dev'));"
docker exec lasfocas-postgres psql -U lasfocas -d lasfocas -c "SELECT pg_size_pretty(pg_database_size('lasfocas'));"
```

- [ ] **Paso 2: 🛑 Ejecutar el restore (pg_dump de dev en pipe directo a pg_restore de prod)**

```bash
docker exec lasfocasdev-postgres pg_dump -U FOCALBOT -d focas_dev -F c --no-owner --no-acl \
| docker exec -i lasfocas-postgres pg_restore -U lasfocas -d lasfocas --clean --if-exists --no-owner --no-acl
```
Este es el mismo patrón (invertido) que ya usa `scripts/start_dev.sh --clone-db` para prod→dev — aquí es dev→prod, mucho más sensible. `--clean --if-exists` dropea y recrea cada objeto antes de restaurarlo, evitando conflictos de esquema.

- [ ] **Paso 3: Verificar el resultado**

```bash
docker exec lasfocas-postgres psql -U lasfocas -d lasfocas -c "SELECT pg_size_pretty(pg_database_size('lasfocas'));"
docker exec lasfocas-postgres psql -U lasfocas -d lasfocas -c "SELECT version_num FROM alembic_version;"
docker exec lasfocas-postgres psql -U lasfocas -d lasfocas -c "SELECT count(*) FROM app.cromo_botellas;"
```
Expected: tamaño ≈ 941 MB, `version_num` = `20260904_01` (o el HEAD real al momento de ejecutar), conteo de `cromo_botellas` > 0 (antes era 0).

---

### Task 10: 🛑 Reconciliar baneos — limpiar los de `dev`, reaplicar los reales de prod

🛑 **Confirmar el dry-run con el usuario antes de aplicar.**

- [ ] **Paso 1: Inspeccionar qué trajo el restore en incidentes de baneo** (dev puede tener sus propios incidentes de prueba/históricos)

```bash
docker exec lasfocas-postgres psql -U lasfocas -d lasfocas -c "SELECT estado, count(*) FROM app.incidentes_baneo GROUP BY estado;"
```

- [ ] **Paso 2: Escribir el script de reconciliación** (uso único, no versionado), ejecutado DENTRO de `lasfocas-web` reusando el código real ya desplegado (mismo patrón que `docs/PR/2026-09-03.md`):
  - Cierra/neutraliza cualquier incidente `activo` que haya venido de `dev` (no está en el snapshot de Task 8).
  - Para cada incidente del snapshot de Task 8, lo recrea/reaplica usando `aplicar_estado_a_grupo` sobre las cámaras encontradas por **nombre** (clave estable) en el dataset ya restaurado — nunca por ID serial viejo.
  - Corre primero en modo dry-run (imprime qué haría, no escribe), se revisa con el usuario, y sólo después se corre con `--apply`.
  - Al terminar, se borra del contenedor (`docker exec lasfocas-web rm -f /tmp/reconciliar_baneos_prod.py`).

⚠️ Este script no se puede escribir en abstracto sin ver el estado real post-restore y las funciones de dominio vigentes en ese momento — escribirlo recién en el momento de ejecución de esta tarea, leyendo `core/services/protection_service.py` (o donde viva `aplicar_estado_a_grupo`) tal como está en el contenedor real, siguiendo el patrón exacto de `docs/PR/2026-09-03.md` (dry-run → revisión → `--apply` → verificación de conteos → borrado del script).

- [ ] **Paso 3: Verificar contra el snapshot**

```bash
docker exec lasfocas-postgres psql -U lasfocas -d lasfocas -c "SELECT count(*) FROM app.incidentes_baneo WHERE estado = 'activo';"
```
Expected: coincide con el conteo de `backups/prod_baneos_snapshot.json` del Task 8.

---

### Task 11: Reconstruir y desplegar el stack completo de prod

⚠️ **No usar `./Start` para este despliegue** — su lista `SERVICES=(postgres nlp_intent api web office slack_baneo_worker)` es anterior a `redis`/`docker-socket-proxy`/`botellas_recalculo_worker`/`cromo_worker` y los dejaría afuera. Usar `docker compose` directo contra el stack completo.

- [ ] **Paso 1: Confirmar pre-requisitos**

```bash
ls -la .secrets/*.txt   # los 13 secrets de deploy/compose.yml deben existir, modo 600
grep -c '^' .env         # .env actualizado (Task 6) presente
```

- [ ] **Paso 2: Decidir explícitamente si se incluye `bot` (Telegram)** — nunca corrió en prod hasta ahora; si no se decide incluirlo, excluirlo del `up` explícitamente.

- [ ] **Paso 3: Down + up completo (con o sin `bot` según el paso 2)**

```bash
cd /home/support-focal-01/LAS-FOCAS
docker compose -f deploy/compose.yml --env-file .env down --remove-orphans
# Sin bot:
docker compose -f deploy/compose.yml --env-file .env up -d --build \
  postgres redis docker-socket-proxy api web nlp_intent office slack_baneo_worker botellas_recalculo_worker cromo_worker
# Con bot, agregar "bot" al final de la lista.
```

- [ ] **Paso 4: Esperar y verificar healthchecks**

```bash
sleep 30
docker ps --filter name=lasfocas- --format '{{.Names}}\t{{.Status}}'
```
Expected: todos `Up ... (healthy)`. Si alguno queda `unhealthy`, revisar `docker logs <contenedor>` antes de seguir — no reintentar a ciegas.

- [ ] **Paso 5: Verificar que Alembic quedó en head** (debe ser no-op, ya lo trajo el restore)

```bash
docker exec lasfocas-api alembic -c /app/db/alembic.ini current 2>&1 || docker exec lasfocas-postgres psql -U lasfocas -d lasfocas -c "SELECT version_num FROM alembic_version;"
```

---

### Task 12: Verificación end-to-end post-despliegue

- [ ] **Paso 1: Health endpoints**

```bash
curl -fsS http://172.18.208.162:8080/health && echo " web OK"
curl -fsS http://172.18.208.162:8001/health && echo " api OK"
```

- [ ] **Paso 2: Datos Cromo presentes**

```bash
docker exec lasfocas-postgres psql -U lasfocas -d lasfocas -c "SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE relname LIKE 'cromo_%' ORDER BY n_live_tup DESC;"
```
Expected: conteos similares a los de dev pre-migración (`cromo_botellas` ≈ 11072, `cromo_odf_conectores` ≈ 204841, etc.).

- [ ] **Paso 3: Smoke test funcional**
  - Cargar `http://172.18.208.162:8080` en el navegador, iniciar sesión, buscar una Cámara real en Infra.
  - Enviar un mensaje benigno al bot de Slack de prod y confirmar respuesta.
  - Verificar en logs que no hay excepciones repetidas en los primeros 5 minutos: `docker compose -f deploy/compose.yml logs --since=5m api web cromo_worker | grep -i error`

- [ ] **Paso 4: Confirmar que el worker de Cromo sigue vivo para sync incremental futuro**

```bash
docker logs lasfocas-cromo-worker --tail 50
```

---

## Parte D — Cierre

### Task 13: Documentar el despliegue

- [ ] **Paso 1: Nueva entrada en `docs/decisiones.md`** cerrando el gap: "main es nuevamente la fuente de verdad de lo desplegado en prod, dataset Cromo cargado desde dev el YYYY-MM-DD, N incidentes de baneo reconciliados."
- [ ] **Paso 2: Nueva entrada en `docs/PR/YYYY-MM-DD.md`** con los comandos ejecutados y el resultado de la verificación.
- [ ] **Paso 3: Commit de la documentación** (rama efímera `docs/...` → `dev` vía cierre-sesion, como cualquier otro cambio).

---

## Self-Review

**Cobertura:** Cubre las 4 decisiones ya tomadas por el usuario (dataset Cromo desde dev sin baneos, credenciales Cromo compartidas, cierre de `fix-baneos-hermanos-prod`, provisión de PROV prod) + los 2 hallazgos bloqueantes de la investigación (`cromo_worker`/secrets faltantes en `deploy/compose.yml`, `ENV=development` en prod) + el gap de gobernanza `main` vs prod real.

**Placeholders reales que quedan a propósito** (no se pueden resolver sin estado en vivo al momento de ejecución, marcados explícitamente con ⚠️ en el texto, no ocultos):
- Task 8: nombres exactos de campos/relaciones de `IncidenteBaneo` — requiere leer el modelo real en el momento.
- Task 10: contenido exacto del script de reconciliación — depende del resultado real de Task 9 y del código de dominio vigente en ese momento.
- Task 6: valores concretos de las variables de entorno — son datos de config real, no secretos, pero deben copiarse leyendo `.env.dev` en el momento, no adivinarse.

Estos tres puntos son irreducibles: dependen de estado que sólo existe en el momento de la ejecución real contra los contenedores vivos, no se pueden fijar de antemano sin arriesgar un script incorrecto contra producción.
