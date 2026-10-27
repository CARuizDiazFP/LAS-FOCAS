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
  El mismo clasificador **también puede bloquear lecturas** de prod (un `SELECT` de relevamiento,
  real el 2026-09-28), de forma no uniforme: ese día un `pg_dump` de backup pasó y un `SELECT` de
  textos no. Si una lectura necesaria se bloquea, pedir la salida de Auto Mode en ese momento, no
  rodearla.
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
  api web nlp_intent office slack_baneo_worker botellas_recalculo_worker cromo_worker fo_monitor_worker
```

Si un test falla, no se publica: el fix va por un worktree propio, se integra a `dev`, se vuelve a
buildear y se verifica dentro de la imagen (`docker run --rm --entrypoint sh <img> -c 'grep ...'`).
Real el 2026-10-20: `test_eliminar_grupo_cromo_exitoso_encola_recalculo_duplicados` atrapó un 500
del árbitro en "Eliminar grupo Cromo" que no había llegado a prod (`bba1863`). Correr la suite sin
`-x`: con `-x` las demás fallas quedan ocultas hasta la segunda corrida.

`fo_monitor_worker` existe en prod desde el 2026-10-18. Queda **inactivo** (fila `fo_monitor` de
`app.config_servicios` con `activo=false`) hasta que el usuario decida habilitarlo.

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

**Chequeo directo (real 2026-10-20, `main` con el hotfix `11573c8` propio):** si el merge real de
`main` dentro de `dev` da exactamente el árbol de `dev`, todo el contenido propio de `main` ya está en
`dev` y el `commit-tree` es seguro. Cubre a la vez los merges de despliegues previos y los hotfixes:

```bash
[ "$(git merge-tree --write-tree origin/dev origin/main)" = "$(git rev-parse 'origin/dev^{tree}')" ] \
  && echo "commit-tree seguro"
```

**Excepción verificada (2026-09-28)**: si el único commit propio de `main` es el merge del
despliegue anterior (`git log origin/dev..origin/main` = 1 commit de merge) y su árbol es idéntico al
de su segundo padre, que es ancestro de `dev`, `main` no tiene contenido propio y el `commit-tree` de
arriba sigue siendo seguro — aunque `--is-ancestor` dé falso:

```bash
P2=$(git log -1 --format=%P origin/main | awk '{print $2}')
git merge-base --is-ancestor $P2 origin/dev && git diff --quiet origin/main $P2 && echo "main sin contenido propio"
```

Con cada despliegue se acumula un merge más en `main`: el 2026-09-29 eran **2** (`7055452` y
`1144e9b`) y, en el segundo despliegue de ese día, **4** (más `40ab75c` y `03bafb6`). La condición es la misma para cada uno: el árbol del merge es idéntico al de su segundo
padre, y ese padre es ancestro de `dev`. Chequearla para **todos** los commits de
`git log origin/dev..origin/main`, no sólo el último:

```bash
for c in $(git rev-list origin/dev..origin/main); do
  P2=$(git log -1 --format=%P $c | awk '{print $2}')
  { [ -n "$P2" ] && git merge-base --is-ancestor $P2 origin/dev && git diff --quiet $c $P2; } \
    && echo "$c ok" || echo "$c TIENE CONTENIDO PROPIO: no usar commit-tree"
done
```

## 5. Ventana

Antes de detener: que no haya una corrida de Cromo en curso. Detener `cromo_worker` la corta (una
SOLO_ODF tarda ~3,5 h).

```bash
docker exec lasfocas-postgres psql -U lasfocas -d lasfocas -tAc \
  "select id, estado from app.cromo_ingesta_corridas where estado='EN_CURSO'"   # debe salir vacío
docker compose -f deploy/compose.yml --env-file .env stop \
  api web nlp_intent office slack_baneo_worker botellas_recalculo_worker cromo_worker fo_monitor_worker
# backup final (mismo comando del paso 3, otro nombre)
source .venv/bin/activate
export ALEMBIC_URL="postgresql+psycopg://lasfocas:$(python -c 'import urllib.parse;print(urllib.parse.quote(open(".secrets/db_password_v1.txt").read().strip(),safe=""))')@127.0.0.1:5432/lasfocas"
unset DATABASE_URL
alembic -c db/alembic.ini upgrade head && alembic -c db/alembic.ini current
# cromo_worker PRIMERO: un worker viejo trata un tipo de corrida sintético que no conoce (p. ej.
# la detección de inconsistencias, 2026-10-17) como una ingesta COMPLETA.
docker compose -f deploy/compose.yml --env-file .env up -d --force-recreate \
  postgres redis docker-socket-proxy cromo_worker
docker compose -f deploy/compose.yml --env-file .env up -d --force-recreate \
  api web nlp_intent office slack_baneo_worker botellas_recalculo_worker fo_monitor_worker
```

`bot` (Telegram) no corre en prod: decisión explícita del usuario, no es un olvido.

## 6. Verificación

- Todos `healthy` y sin stale: para cada contenedor de app, `docker inspect -f '{{.Image}}'` igual
  a `docker image inspect -f '{{.Id}}' <imagen>`.
- `/health` de `lasfocas-web` y `lasfocas-api` (incluye `db`). Puertos publicados reales (verificados
  el 2026-09-28 con `docker port`): web en `172.18.208.162:8080` (no escucha en `127.0.0.1`), api en
  `:8001` del host (`8000` es el puerto interno del contenedor).
- `docker logs --since 5m` de cada servicio sin `error|traceback|exception`.
- Conteos de datos reales iguales a los de antes del deploy.
- `slack_baneo_worker`: log `IngresoListener iniciado en modo Socket`. Los logs del worker están en
  hora local (UTC-3): un `--since 5m` puede no mostrar la línea de arranque; buscarla con `--since 15m`.
  El warning `missing_scope ... users:read` es conocido (falta el scope en la Slack App de prod, ver
  `docs/cierres/2026-09-07.md`): el técnico queda con el ID crudo de Slack.
- Redis: los tres checks de `docs/mantenimiento_redes_produccion.md` ("Verificación post-despliegue").
  El `/health` de `botellas_recalculo_worker` escucha en el puerto **8097** dentro del contenedor, no
  en 8000: `docker exec lasfocas-botellas-recalculo-worker curl -fsS http://localhost:8097/health`
  (el mismo que usa su `healthcheck`; real el 2026-09-29, un intento a 8000 dio `Connection refused`).
- Queda para el usuario: navegador sobre el panel y un mensaje real en Slack prod.

## 7. Pasos de datos pendientes del lote (post-verificación)

Se corren **después** del paso 6, con el código nuevo ya sirviendo, dentro del contenedor de prod.

Patrón para cualquier script de datos de este paso (usado por el reproceso, 2026-09-28):

- Lo que sigue aplica a los contenedores que no tienen `scripts/`. `lasfocas-api` sí lo tiene desde
  `a2d055a` (2026-08-26): un script commiteado se corre directo, por ejemplo
  `docker exec -it lasfocas-api python scripts/api_clients.py listar`.
- **Por stdin**: los demás contenedores de app no tienen `scripts/` ni `/tmp` escribible
  (`docker exec -i -w /app -e PYTHONPATH=/app <contenedor> python - [args] < scripts/x.py`); la salida
  va por stdout y se redirige a un archivo del host.
- **Dry-run exacto, no estimado**: correr todo dentro de una transacción externa que se revierte
  (`Session(bind=connection, join_transaction_mode="create_savepoint")` sobre `connection.begin()`):
  los `commit()` de los servicios existentes sólo liberan savepoints. El reporte del dry-run es lo que
  hará `--apply`. Ver `scripts/ingresos_reprocesar_sin_match.py::ejecutar`.
  **Ojo con el apply**: ese patrón persiste sólo porque los servicios llamados hacen `commit()`. Si las
  funciones de dominio no commitean (convención "lo hace el llamador", p. ej.
  `core/services/clientes_categoria_service.py`), el script tiene que llamar `session.commit()` antes
  de `close()` en el camino de apply. Si no, `close()` revierte el savepoint y el apply reporta éxito
  sin escribir nada (real 2026-10-14, `scripts/clientes_categoria_regularizar.py`, lo atrapó la review).
  **Sólo el dry-run**: con `--apply` no hay transacción externa y se commitea por tanda. Si no, una
  corrida larga queda en una sola transacción que se pierde entera ante un corte y no se puede
  reanudar (real 2026-10-01: `cromo_barrido_pelos_inner.py`, corrida 2149 de ~16 h en una transacción).
- **Corridas de más de ~25 min, desacopladas**: `setsid nohup sh -c 'docker exec ... > ~/x.json 2> ~/x.log' &`.
  Si se corta el cliente `docker exec` (por ejemplo, el límite de una tarea en segundo plano del
  agente), el proceso **sigue vivo dentro del contenedor**: relanzarlo deja dos corridas en paralelo
  (real 2026-10-01: alta desde PROV, 796 `UniqueViolation`). Antes de relanzar, confirmar en la base
  que dejó de escribir (conteo quieto ~30 s y sin sesiones activas en `pg_stat_activity`). Los
  contenedores de app no tienen `ps`, y en prod los scripts no escriben `Logs/` (`ENV=production`).
- **Ensayar antes en dev con una copia de los datos de prod** dentro de la misma transacción
  revertida: el ensayo del 2026-09-28 encontró un bug real del listener antes de tocar prod.

- **Reproceso de ingresos sin match** (desde el despliegue que incluya la mejora de búsqueda del
  2026-09-28, `cc58658`, y `scripts/ingresos_reprocesar_sin_match.py`). Dry-run exacto primero
  (corre todo y revierte), revisar el reporte, recién entonces `--apply`:

  ```bash
  docker exec -i -w /app -e PYTHONPATH=/app lasfocas-slack-baneo-worker \
      python - --slack --reporte - < scripts/ingresos_reprocesar_sin_match.py > reproceso_dry.json
  # revisar reproceso_dry.json (estados REGISTRADO/NODO y cada movimiento); si está bien:
  docker exec -i -w /app -e PYTHONPATH=/app lasfocas-slack-baneo-worker \
      python - --slack --apply --reporte - < scripts/ingresos_reprocesar_sin_match.py > reproceso_apply.json
  ```

  Con `--ids <a>,<b>` se reprocesan sólo esos casos (uso real 2026-09-29: #206/#208 tras fusionar un
  duplicado, #204/#205 tras el deploy). Los `ingreso_id` del dry-run **no** son los del `--apply`: la
  transacción revertida igual consume valores de la secuencia (dry-run 211, apply 212). Comparar por
  caso, cámara y acción, no por id.

  Ensayo contra una copia de los 169 casos de Slack de prod en dev (2026-09-28, revertido): 33
  registran movimiento (18 ingresos, 13 egresos que cierran, 4 egresos huérfanos), 25 Nodos marcados
  revisados, 111 sin tocar. En prod los egresos que cierran pueden ser más (ingresos abiertos reales
  que dev no tiene). Idempotente: una segunda corrida no agrega filas. Detalle:
  `docs/relevamiento_ingresos_sin_match_2026-09-28.md`, sección "Reproceso por lote".

## Copiar tablas espejo de Cromo desde dev en vez de re-ingestar

Uso real: 2026-10-18 (`docs/PR/2026-10-18.md`). Evitó una SOLO_ODF de ~3,5 h en prod. Sirve sólo
para tablas que son **espejo de Cromo** (claves = ids de Cromo, iguales en dev y prod) y que la
ingesta acotada escribe enteras, como `app.cromo_odfs` y `app.cromo_odf_conectores`. **No** sirve
para tablas con escrituras propias de prod (ingresos, baneos, incidentes, casos de inconsistencias).

Condiciones, todas medidas antes de aplicar:
- Las dos bases en la misma revisión de Alembic (columnas idénticas por `information_schema`).
- Prod es subconjunto de dev: 0 filas sólo en prod y 0 filas de prod con `ultima_ingesta` más nueva.
- Las columnas que dependen de datos locales se recalculan en prod después (en conectores:
  `servicio_resuelto`/`servicio_id_historico`, que salen del atributo de Cromo y de
  `cromo_pelos.servicio_numero` local; el 2026-10-18 cambiaron 31 de 100.733).

Pasos:
1. Esquema de paso en prod (`CREATE SCHEMA copia_dev`, tablas `LIKE app.<tabla> INCLUDING DEFAULTS`).
2. Copia binaria por pipe, sin archivos intermedios:
   `docker exec lasfocasdev-postgres psql ... -c "\copy app.<t> TO STDOUT WITH (FORMAT binary)" |
   docker exec -i lasfocas-postgres psql ... -c "\copy copia_dev.<t> FROM STDIN WITH (FORMAT binary)"`.
3. Ensayo: el mismo SQL de conteos (nuevas / a actualizar / sólo en prod / más nuevas en prod) y
   `INSERT ... ON CONFLICT (n_id) DO UPDATE` (sin tocar `primera_ingesta`) dentro de
   `BEGIN ... ROLLBACK`. Revisar los conteos post.
4. El mismo archivo con `COMMIT`.
5. Recalcular las columnas locales con la función de la ingesta (por stdin en `lasfocas-cromo-worker`,
   ensayo y `--apply`), y repetir el ensayo hasta que dé 0 cambios.
6. `DROP SCHEMA copia_dev CASCADE`.

## Secretos nuevos del lote

Si `git diff origin/main origin/dev -- deploy/compose.yml` agrega un secreto (bloque `secrets:` raíz),
el archivo `.secrets/<nombre>.txt` tiene que existir **antes** del paso 5. Si falta, el `up` de ese
servicio falla. Generarlo sin imprimirlo, distinto del `Dev_` y con permisos `600`. Ejemplo real del
2026-09-29 (`oauth_jwt_secret_v1`):

```bash
test -e .secrets/oauth_jwt_secret_v1.txt || (umask 077; python3 -c "import secrets;print(secrets.token_urlsafe(48))" > .secrets/oauth_jwt_secret_v1.txt)
cmp -s .secrets/oauth_jwt_secret_v1.txt .secrets/Dev_oauth_jwt_secret_v1.txt && echo "IGUAL A DEV: regenerar"
```

Después del `up`, confirmar que el secreto está montado (`docker exec <contenedor> ls /run/secrets/`).

## Hotfix puntual a prod (sin pasar `dev` entero)

Real el 2026-10-19 (`docs/PR/2026-10-19.md`, hotfix de Repetitividad, `main` `11573c8`). Úsese cuando
el pedido es "pasar a prod **este** fix" y `dev` tiene más trabajo que no debe salir todavía
(en esa fecha, el árbitro de Cromo con migración propia).

1. **Integrar el fix a `main` sin traer el resto de `dev`.**
   - Crear un worktree de `main`:
     `git worktree add -b fix/<agente>-hotfix-<slug> ../LAS-FOCAS-agentes/<agente>-hotfix-main origin/main`.
   - El hook de pre-commit exige el prefijo `fix/`: `hotfix/` lo bloquea.
   - Traer el commit con `git cherry-pick -n <sha>`. Excluir `docs/PR/<fecha>.md` si sólo existe en
     `dev`: `git rm --cached` + `rm`. Si no, `main` queda con un add/add que choca en el próximo
     merge `dev`→`main`.
2. **Tests focales** en ese worktree, con un symlink temporal a `.venv`.
3. **Build desde el worktree de `main`, nunca desde el checkout de control.** El control está en
   `dev` y es el contexto de build (`context: ..`), así que metería todo `dev` en la imagen.
   - Antes de buildear, etiquetar las imágenes vigentes para rollback:
     `docker tag lasfocas-web:latest lasfocas-web:pre-hotfix-<fecha>`.
   - Buildear sólo los servicios afectados:
     `docker compose -f <wt>/deploy/compose.yml --env-file <control>/.env build web api`.
   - Verificar el contenido de la imagen con
     `docker run --rm --entrypoint sh <img> -c 'grep ...'`: el fix presente y nada de `dev` que no
     debía ir.
4. **Publicar en `main`** por fast-forward: `git merge-base --is-ancestor origin/main HEAD` y después
   `git push origin HEAD:refs/heads/main`.
5. **Recrear sólo los servicios afectados, DESDE EL CHECKOUT DE CONTROL y sin rebuild.** Todos los
   bind mounts del compose son relativos al propio archivo: `../.secrets/*`, `../Logs`,
   `../Templates` y `../data/fo_monitor`.
   - **Error real del 2026-10-19**: hacer `up` desde el worktree, con symlinks a `.env`/`.secrets`,
     dejó a `web`/`api` de prod montando el worktree.
     - Los secretos quedaron montados a través de un symlink efímero.
     - Los logs de prod se escribían en el worktree.
     - `data/fo_monitor` lo creó Docker vacío y como root. Eso bloqueó `git worktree remove`, y el
       borrado parcial se llevó los logs de esa ventana.
   - Primero comparar el compose: `git diff origin/main origin/dev -- deploy/compose.yml`. Los
     servicios a recrear no deben cambiar.
   - Después recrear desde el checkout de control:
     ```bash
     cd <control>   # en dev; sólo se usa su compose y sus rutas, la imagen es la del hotfix
     docker compose -f deploy/compose.yml --env-file .env up -d --no-deps --no-build --force-recreate web api
     docker inspect -f '{{range .Mounts}}{{if eq .Type "bind"}}{{.Source}}{{"\n"}}{{end}}{{end}}' lasfocas-web   # ninguna ruta del worktree
     ```
   - Si el compose de esos servicios sí difiere entre `main` y `dev`, no usar este atajo: hacer el
     merge `dev`→`main` normal.
6. **Verificar**: healthy y la imagen nueva en el contenedor. El `/tmp` de los contenedores de prod es
   tmpfs y `docker cp` no lo ve: sacar los artefactos de prueba por stdout
   (`docker exec ... sh -c '...; cat /tmp/x.png' > local.png`) y borrarlos adentro.
7. **Después**: integrar la rama original del fix a `dev`, como siempre. `main` queda con un commit
   propio cuyo contenido ya está en `dev`, así que en el próximo despliegue `--is-ancestor` da falso.
   Verificar con `git diff <commit-hotfix> origin/dev` que sólo aparezca lo que trae `dev` (ninguna
   reversión del fix) antes de usar el `commit-tree` del paso 4.

Rollback del hotfix:
`docker tag lasfocas-web:pre-hotfix-<fecha> lasfocas-web:latest` (ídem `api`) y
`up -d --no-deps --force-recreate` de esos servicios. El `:pre-hotfix-*` pasa a ser el juego vigente
de esos servicios; la retención sigue la sección "Rollback".

## Rollback

- Imágenes: se conserva **sólo el último juego** (regla única en la skill `docker-cleanup` →
  "Rollback de prod"). **Antes del build del paso 2** (que mueve `:latest` a la imagen nueva aunque
  prod siga corriendo la vieja), etiquetar cada servicio que se va a reconstruir:
  `docker tag lasfocas-<svc>:latest lasfocas-<svc>:pre-deploy-$(date +%Y%m%d)`. Volver
  atrás: `docker tag lasfocas-<svc>:pre-deploy-<fecha> lasfocas-<svc>:latest` y
  `up -d --no-deps --force-recreate` de esos servicios, desde el checkout de control.
- Tras verificar el deploy (sección 6 y prueba del usuario), el juego anterior queda superado: los
  `:pre-deploy-*`/`:pre-hotfix-*` de cada servicio que tenga uno más nuevo y las `focas-base` más
  viejas que la anterior. Se borran por tag exacto (`docker image rm <repo>:<tag>`, nunca `prune -a`),
  con confirmación del usuario en esa sesión. Cada juego ocupa ~0,9 GB reales en un disco de 40 GB
  compartido con dev.
- Código: `docker compose ... up -d` desde el commit anterior de `main`.
- Esquema: `alembic downgrade <revisión previa>` (todas las migraciones tienen `downgrade()`) o
  `pg_restore --clean --if-exists` del backup de ventana.
- Reproceso de ingresos sin match: cada movimiento queda enlazado desde su caso
  (`ingresos_sin_match.ingreso_id`, `resuelto_via_revalidacion=true`) y el reporte `--apply` lista
  cada `ingreso_id` creado o cerrado — revertir es borrar/reabrir esas filas puntuales vía un script
  que use `core/services/ingreso_service.py`, nunca un `UPDATE` masivo a mano.

