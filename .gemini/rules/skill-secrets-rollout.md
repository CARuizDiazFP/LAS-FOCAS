# Nombre de archivo: skill-secrets-rollout.md
# Ubicación de archivo: .gemini/rules/skill-secrets-rollout.md
# Descripción: Regla Gemini portable migrada desde .github/skills/secrets-rollout/SKILL.md
---
name: "skill-secrets-rollout"
description: "Usar cuando haya que migrar variables sensibles a Docker Secrets, agregar un secret nuevo a un servicio de Compose, o rotar un secret ya en uso (dev o prod) en LAS-FOCAS"
source: ".agentes-comunes/skills/secrets-rollout/SKILL.md"
triggers:
  - "secrets-rollout"
  - "habilidad"
  - "docker secrets"
  - "rotar"
  - "rotación"
  - "db_password_v1"
  - "postgres_password_file"
  - "database_url"
  - "las-focas"
globs:
  - "deploy/**"
  - ".secrets/**"
  - ".env*"
  - "core/config.py"
  - "db/session.py"
commands:
  - |
    python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')"
  - |
    printf 'ALTER ROLE "%s" WITH PASSWORD %s;\n' "$PG_USER" "$(python3 -c "import sys; print(chr(39)+sys.argv[1].replace(chr(39),chr(39)*2)+chr(39))" "$NEWPASS")" \
      | docker exec -i <container_postgres> psql -U "$PG_USER" -d "$PG_DB"
  - |
    docker compose -f <compose_file> --env-file <env_file> up -d --force-recreate --no-build <servicio>
  - |
    ./scripts/check_no_plaintext_secrets.sh
---

# Regla Skill: secrets-rollout

> Fuente original: `.github/skills/secrets-rollout/SKILL.md`. Usar esta regla cuando Gemini/Codex IDE detecte los triggers o globs declarados.

# Habilidad: Secrets Rollout

Procedimiento para migrar y rotar Docker Secrets basados en archivo (sin Swarm) en `deploy/compose.yml` (prod) y `deploy/docker-compose.dev.yml` (dev). Todo lo de abajo surge de incidentes reales detectados y corregidos en sesión (ver `docs/decisiones.md` — "2026-07-28 — Docker Secrets basados en archivo para dev y prod" — y `docs/PR/2026-07-28.md`).

## Convención de naming (no romper)

- Dev: `.secrets/Dev_<nombre>.txt` (ej. `Dev_db_password_v1.txt`), referenciado desde `deploy/docker-compose.dev.yml`.
- Prod: `.secrets/<nombre>.txt` **sin prefijo** (ej. `db_password_v1.txt`), referenciado desde `deploy/compose.yml`.
- Nunca renombrar ni reutilizar los archivos sin prefijo (reservados a prod) para trabajo de dev, ni viceversa.
- El nombre del secret top-level en el `secrets:` de Compose (y el que usan los `get_secret(...)` en Python) NO lleva prefijo en ningún entorno — solo cambia el `file:` que apunta a `.secrets/`. Esto evita tener que tocar código Python al migrar/rotar.

## Checklist obligatorio ANTES de editar un servicio de Compose

1. **Releer el bloque COMPLETO del servicio** en el archivo actual (no solo el fragmento a tocar). Un `env_file` ya declarado más arriba puede inyectar en texto plano la misma variable que se va a reemplazar por secret — este cruce hay que hacerlo antes de editar, no después de que falle en runtime.
2. Si el servicio va a recibir una variable `<VAR>_FILE` (ej. `POSTGRES_PASSWORD_FILE`), confirmar que ese mismo servicio **no** tenga `env_file`/`environment` inyectando también `<VAR>` en texto plano. Postgres aborta con:
   ```
   error: both POSTGRES_PASSWORD and POSTGRES_PASSWORD_FILE are set (but are exclusive)
   ```
   Solución: quitar `env_file` de ese servicio si solo lo necesitaba para esa variable (el `postgres` de ambos composes de LAS-FOCAS no necesita `env_file`; `POSTGRES_DB`/`POSTGRES_USER` llegan por interpolación `${VAR}` vía `--env-file` en el comando `docker compose`, no por `env_file:`).
3. Grepear el código consumidor (`get_secret(...)` en `core/config.py`, `db/session.py`, `core/services/repetitividad.py`, etc.) para confirmar la cadena de precedencia completa. **`DATABASE_URL`/`ALEMBIC_URL`, si están seteadas, ganan siempre sobre el secret armado** (`_engine_url()` las chequea primero) y lo anulan por completo sin error visible.

## Regla: neutralizar una variable ≠ vaciarla

Para que un secret reemplace efectivamente a una variable de `.env`/`.env.dev` (ej. `DATABASE_URL`), hay que **comentar la línea completa**, nunca dejarla vacía (`VAR=`):

```bash
# mal — sigue rompiendo el fallback:
DATABASE_URL=

# bien:
# DATABASE_URL=postgresql+psycopg://...
```

Motivo técnico: `get_secret()`/`_env()` (`core/config.py`) caen a `os.getenv(env_var, default)`, y `os.getenv` solo devuelve el `default` cuando la clave está **ausente** — si está presente pero vacía, devuelve `""`. Con `DATABASE_URL=""` inyectada vía `env_file`, `create_engine("")` revienta con `ArgumentError: Could not parse SQLAlchemy URL from string ''`. Este gotcha aplica a cualquier variable consumida con ese patrón, no solo `DATABASE_URL`.

## Regla: el contenido del secret debe ser el valor REAL vigente

Al migrar una credencial ya en uso (ej. `db_password_v1.txt`) a un archivo nuevo, el contenido debe ser una copia **exacta** del valor que el servicio ya acepta — nunca uno regenerado — salvo rotación explícita (ver abajo). Verificar la copia por hash sin imprimir el secreto:

```bash
python3 - <<'PY'
import hashlib
def read(p):
    with open(p) as f: return f.read().strip()
a, b = read(".env"), read(".secrets/db_password_v1.txt")  # ajustar paths
print("match:", a == b)
PY
```

No asumir por instrucción de terceros (ni por placeholders con nombre engañoso tipo `cambiar_por_password_dev_seguro`) cuál es el valor real vigente sin verificar contra el sistema en ejecución (health check tras recrear, o consultando al usuario si hay ambigüedad genuina).

## Procedimiento de ROTACIÓN de un secret ya en uso

1. **Backup con timestamp** de `.env`/`.env.dev` y del `.secrets/<nombre>.txt` afectado (`cp archivo archivo.bak-$(date +%Y%m%d-%H%M%S)`, `chmod 600`).
2. **Generar valor nuevo** con `python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')"` (alfabeto URL-safe, sin caracteres que compliquen shell/URL/SQL).
3. Escribir el valor nuevo en el `.secrets/<nombre>.txt` **y** en la variable de fallback correspondiente en `.env`/`.env.dev` (mantenerlas en sync mientras el fallback siga vigente).
4. Para roles de PostgreSQL, aplicar el cambio real con `ALTER ROLE` vía socket local, pasando el SQL por **stdin** (nunca como argumento de shell, para no exponer la password en `argv`/`docker logs`/historial):
   ```bash
   printf 'ALTER ROLE "%s" WITH PASSWORD %s;\n' "$PG_USER" "$(python3 -c "import sys; print(chr(39)+sys.argv[1].replace(chr(39),chr(39)*2)+chr(39))" "$NEWPASS")" \
     | docker exec -i <container_postgres> psql -U "$PG_USER" -d "$PG_DB"
   ```
   **Citar el nombre del rol entre comillas dobles** (`ALTER ROLE "NombreConMayusculas" ...`). Sin comillas, Postgres pliega el identificador a minúsculas y falla con `role "nombreconminusculas" does not exist` si el rol se creó con mayúsculas (vía `POSTGRES_USER` con mayúsculas en el entorno).
5. **Recrear los contenedores que consumen ese secret DE A UNO** (nunca todos a la vez):
   ```bash
   docker compose -f <compose_file> --env-file <env_file> up -d --force-recreate --no-build <servicio>
   ```
   Verificar entre cada paso: `curl -fsS http://localhost:<puerto>/health` (confirmar `"db":"ok"` si aplica), `docker inspect -f '{{.State.Health.Status}}' <contenedor>` → `healthy`, y `docker logs <contenedor> --tail 20` sin `FATAL`. No continuar con el siguiente servicio hasta confirmar el anterior.
6. `postgres` normalmente **no** necesita recrearse para una rotación de rol: `ALTER ROLE` aplica en caliente; `POSTGRES_PASSWORD_FILE` solo se usa en el `initdb` inicial del volumen.
7. Si el mecanismo no está probado todavía en este entorno, **ensayar primero en dev** el mismo procedimiento antes de aplicar en prod (rehearsal de bajo riesgo).
8. Documentar la rotación en `docs/decisiones.md`/`docs/PR/YYYY-MM-DD.md` (fecha, secret rotado, procedimiento, verificación) — nunca el valor en texto plano.

## Secrets consumidos por una imagen de terceros que NO corre como root (ej. `pgAdmin`)

Compose **sin Swarm** (el modo de este host) ignora los campos `uid`/`gid`/`mode` de la sintaxis larga de `secrets:` a nivel de servicio — lo advierte explícitamente: `secrets 'uid', 'gid' and 'mode' are not supported, they will be ignored`. El archivo se monta en `/run/secrets/<nombre>` como bind mount **preservando el ownership y los permisos reales del archivo del host**, sin importar qué se declare en el compose.

Los servicios propios de LAS-FOCAS no lo notan porque corren como `root` (leen cualquier permiso) o como `uid 1001` (mismo dueño que `.secrets/*.txt`, ver `write_secret()` abajo). Una imagen de terceros con su propio UID fijo (`dpage/pgadmin4` corre como `uid=5050 gid=0`) no puede leer un secret en `600` propiedad de otro UID — falla con `Permission denied` recién visible en `docker logs` del contenedor (no en `docker compose config`, que valida sintaxis, no permisos). Ver `docs/decisiones.md`, entrada 2026-08-11 (`pgadmin_password_v1`).

**Solución**:
1. Generar ese secret puntual con permisos `640` en vez de `600`: `write_secret()` en `scripts/setup_local_secrets.sh` acepta un modo opcional como segundo argumento (`write_secret Dev_pgadmin_password_v1.txt 640`).
2. Agregar `group_add: ["<gid del dueño del archivo>"]` al servicio en el compose (ej. `group_add: ["1001"]`, GID de `support-focal-01`), para que el proceso del contenedor gane ese grupo como suplementario y lea el archivo por permiso de grupo, sin tocar el UID/GID principal de la imagen (que puede ser necesario para los permisos internos propios de esa imagen).

**No usar `chgrp`** para mover el archivo a un grupo que el usuario que corre el script no integra — falla con `Operation not permitted` (un usuario no-root no puede asignar un archivo a un grupo ajeno). Por eso la vía es `group_add` en el contenedor consumidor, no cambiar el grupo del archivo del lado del host.

## Guardrails

1. Nunca imprimir un secreto en texto plano en la salida (usar hash SHA-256 para verificar coincidencias).
2. Nunca pasar una password como argumento de shell (`argv` queda en `ps`/logs) — usar stdin.
3. Recrear contenedores de a uno con verificación entre pasos; nunca `docker compose up -d --force-recreate` sobre todo el stack para este tipo de cambio.
4. `.secrets/` y `.env*` ya están en `.gitignore` — no versionar backups (`*.bak-*`) tampoco.
5. Antes de dar por resuelta una migración/rotación, correr `scripts/check_no_plaintext_secrets.sh` (cubre `deploy/compose.yml` y `deploy/docker-compose.dev.yml`).
6. Si el secret lo consume una imagen de terceros (no las propias de LAS-FOCAS), verificar que su usuario/UID pueda leer el archivo montado **antes** de dar por resuelta la migración — ver sección "Secrets consumidos por una imagen de terceros" arriba.

## Referencias

- `docker-rebuild` — comandos de rebuild/gestión de contenedores.
- `secret-detection` — detección de secretos expuestos (auditoría, no rollout).
- `docs/Seguridad.md` — estrategia de secretos vigente (sección "Estrategia de secretos en producción").
- `docs/db.md` — precedencia `ALEMBIC_URL`/`DATABASE_URL` y su interacción con `db_password_v1`.
