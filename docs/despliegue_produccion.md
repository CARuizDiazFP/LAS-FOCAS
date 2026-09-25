# Nombre de archivo: despliegue_produccion.md
# Ubicación de archivo: docs/despliegue_produccion.md
# Descripción: Runbook para desplegar código y esquema de dev a producción (stack lasfocas) y mergear dev→main, sin reemplazar datos

# Despliegue de `dev` a producción (código + esquema)

Runbook sacado de dos despliegues reales: el 2026-09-07 (`docs/PR/2026-09-07.md`, que además
reemplazó los datos) y el 2026-09-25 (`docs/PR/2026-09-25.md`, sólo código y esquema, ~5 min de
corte). Sirve para el caso normal: **prod conserva sus datos** y recibe el código y las
migraciones de `dev`.

> **No hacer restore de `focas_dev` sobre `lasfocas`** salvo pedido explícito. Prod tiene
> escrituras reales propias (ingresos de Slack, baneos, incidentes) que dev no tiene. Antes de
> decidir, comparar conteos (`app.ingresos`, Cámaras `BANEADA`, `app.incidentes_baneo`) en las dos bases.

## 0. Antes de empezar

- **Auto Mode**: su clasificador bloquea el push a `main` ("Merge Without Review") y la escritura
  sobre la DB de prod, aunque el usuario lo haya aprobado en el chat (real el 2026-09-07 y el
  2026-09-25). Hacer todo el relevamiento y las etapas sin riesgo primero (pasos 1 a 3) y pedirle
  al usuario que salga de Auto Mode **antes** del paso 4, no a mitad de la ventana.
- `ListAgents` + `python scripts/agent_worktree.py list`: que no haya sesiones activas integrando a `dev`.
- El checkout de control debe estar en `dev`, limpio y en `origin/dev`: es el contexto de build
  del compose (`context: ..`).

## 1. Relevamiento

```bash
git fetch origin
git rev-list --count origin/main..origin/dev ; git rev-list --count origin/dev..origin/main   # el 2º debe ser 0
docker exec lasfocas-postgres    psql -U lasfocas -d lasfocas  -tAc "select * from alembic_version"   # schema public, no app
docker exec lasfocasdev-postgres psql -U FOCALBOT -d focas_dev -tAc "select * from alembic_version"
git diff --stat origin/main origin/dev -- db/alembic/versions/     # revisar upgrade() de cada migración nueva
git diff origin/main origin/dev -- deploy/compose.yml              # secrets/servicios nuevos → verificar .secrets/
comm -23 <(grep -oE '^[A-Z_][A-Z0-9_]*' .env.dev | sort -u) <(grep -oE '^[A-Z_][A-Z0-9_]*' .env | sort -u)
```

`OLLAMA_URL` falta en `.env` de prod a propósito; no es un gap.

## 2. Etapas sin riesgo, en paralelo (no tocan lo que corre)

```bash
source .venv/bin/activate && LLM_PROVIDER=heuristic python -m pytest -q
docker compose -f deploy/compose.yml --env-file .env build \
  api web nlp_intent office slack_baneo_worker botellas_recalculo_worker cromo_worker
```

## 3. Backup en caliente (~2 min para ~800 MB de base, dump de ~135 MB)

```bash
D=~/lasfocas-prod-sync-$(date +%Y%m%d); mkdir -p $D
docker exec lasfocas-postgres pg_dump -U lasfocas -d lasfocas -F c --no-owner --no-acl > $D/prod_backup_pre_deploy_$(date +%Y%m%d_%H%M%S).dump
docker run --rm -v $D:/b postgres:16-alpine pg_restore -l /b/<archivo>.dump | grep -c 'TABLE DATA'
```

## 4. Merge `dev`→`main` sin sacar el checkout de control de `dev`

Si `main` es ancestro de `dev`, el merge `--no-ff` no puede tener conflictos y su árbol es el de `dev`:

```bash
git merge-base --is-ancestor origin/main origin/dev
C=$(git commit-tree "origin/dev^{tree}" -p origin/main -p origin/dev -m "Merge branch 'dev' into main")
git diff --quiet $C origin/dev && git push origin $C:refs/heads/main
```

Si `main` tiene commits propios, **no** usar esto: hacer el merge real en un worktree de `main`.

## 5. Ventana

```bash
docker compose -f deploy/compose.yml --env-file .env stop \
  api web nlp_intent office slack_baneo_worker botellas_recalculo_worker cromo_worker
# backup final (mismo comando del paso 3, otro nombre)
source .venv/bin/activate
export ALEMBIC_URL="postgresql+psycopg://lasfocas:$(python -c 'import urllib.parse;print(urllib.parse.quote(open(".secrets/db_password_v1.txt").read().strip(),safe=""))')@127.0.0.1:5432/lasfocas"
unset DATABASE_URL
alembic -c db/alembic.ini upgrade head && alembic -c db/alembic.ini current
docker compose -f deploy/compose.yml --env-file .env up -d --force-recreate \
  postgres redis docker-socket-proxy api web nlp_intent office slack_baneo_worker botellas_recalculo_worker cromo_worker
```

`bot` (Telegram) no corre en prod: decisión explícita del usuario, no es un olvido.

## 6. Verificación

- Todos `healthy` y sin stale: para cada contenedor de app, `docker inspect -f '{{.Image}}'` igual
  a `docker image inspect -f '{{.Id}}' <imagen>`.
- `/health` de `lasfocas-web` (`:8080`) y `lasfocas-api` (`:8000`, incluye `db`).
- `docker logs --since 5m` de cada servicio sin `error|traceback|exception`.
- Conteos de datos reales iguales a los de antes del deploy.
- `slack_baneo_worker`: log `IngresoListener iniciado en modo Socket`.
- Redis: los tres checks de `docs/mantenimiento_redes_produccion.md` ("Verificación post-despliegue").
- Queda para el usuario: navegador sobre el panel y un mensaje real en Slack prod.

## Rollback

- Código: `docker compose ... up -d` desde el commit anterior de `main`.
- Esquema: `alembic downgrade <revisión previa>` (todas las migraciones tienen `downgrade()`) o
  `pg_restore --clean --if-exists` del backup de ventana.
