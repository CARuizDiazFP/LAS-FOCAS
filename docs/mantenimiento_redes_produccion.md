# Nombre de archivo: mantenimiento_redes_produccion.md
# Ubicación de archivo: docs/mantenimiento_redes_produccion.md
# Descripción: Cambio de subred Docker de producción (/16 → /24, ya aplicado) y el pre-requisito de prod aún pendiente (`redis_password_v1`)

> **Antes de cualquier `docker compose -f deploy/compose.yml up` en producción**, revisar el
> [secret `redis_password_v1`](#pre-requisito-obligatorio-secret-redis_password_v1-2026-08-21) —
> **bloquea la creación del contenedor `web`** si falta, no degrada: falla duro. El cambio de
> subred de abajo **ya está aplicado**, no requiere acción.

# Cambio de subred Docker en producción (/16 → /24)

## Estado

- **Aplicado.** Confirmado 2026-08-22 vía auditoría de seguridad contra el sistema real:
  `docker network inspect lasfocas_lasfocas_net` muestra `Subnet: 172.20.0.0/24`, con la red y
  `lasfocas-postgres` creados el 2026-08-11 — la ventana de mantenimiento ya se ejecutó. El
  procedimiento de abajo queda como referencia histórica de cómo se aplicó (y como guía de
  rollback si hiciera falta revertir), **no como un paso pendiente**: no volver a correr
  `down`/`up` por este motivo. Ver [docs/decisiones.md](decisiones.md), entrada 2026-08-05.
- Fecha de redacción original: 2026-08-05. Fecha de verificación de estado aplicado: 2026-08-22.
- Alcance: stack `lasfocas` (producción), archivo `deploy/compose.yml`, red `lasfocas_net`.

## Por qué

Igual que se detectó y corrigió en el entorno dev (ver entrada 2026-08-05 en `docs/decisiones.md`), ninguna red Docker de este repo declaraba `ipam.config.subnet` explícito. Docker asigna por default bloques `/16` de su pool interno, y la red de producción quedó en **`172.20.0.0/16`**. Un bloque `/16` completo agrega una ruta conectada en el kernel del host que tiene prioridad sobre cualquier ruta hacia un destino real de la intranet que caiga dentro de ese mismo `/16` — si algún día existe un host de intranet en `172.20.x.x`, quedaría inalcanzable desde la VM exactamente como pasó con `172.19.217.20` en dev. Achicar a `/24` reduce el bloque secuestrado de 65 536 direcciones a 256, minimizando drásticamente la superficie de colisión.

## Estado actual vs. estado deseado (histórico — ambas columnas ya coinciden)

| | Antes del cambio | Actual desde 2026-08-11 (verificado 2026-08-22) |
|---|---|---|
| Subred `lasfocas_net` | `172.20.0.0/16` (asignada por default de Docker) | `172.20.0.0/24` (explícita vía `ipam.config`) |
| Gateway | `172.20.0.1` | `172.20.0.1` (sin cambio) |
| IPs de contenedores | `.2`–`.7` (dinámicas, sin `ipv4_address`) | Mismas, siguen dinámicas dentro de `.1`–`.254` |
| Contenedores en la red | `lasfocas-postgres`, `lasfocas-api`, `lasfocas-web`, `lasfocas-nlp_intent-1`, `lasfocas-office`, `lasfocas-slack-baneo-worker` | Sin cambios |

**Auditoría de IPs estáticas:** se revisó `deploy/compose.yml` completo — ningún servicio usa `ipv4_address`. Todas las IPs las asigna Docker dinámicamente al arrancar cada contenedor, así que no hay ninguna IP fuera de rango que reasignar. Si en el futuro se agrega una IP estática a algún servicio, debe quedar entre `172.20.0.2` y `172.20.0.254` (`.1` es el gateway).

> **Las secciones siguientes (pre-requisitos, procedimiento, verificación, downtime) describen la
> ventana ya ejecutada el 2026-08-11.** Se conservan como registro y como guía de **rollback** si
> alguna vez hiciera falta revertir a `/16` — no son un TODO.

## Pre-requisitos antes de la ventana

1. Confirmar que `deploy/compose.yml` en la rama que se va a desplegar en `main`/producción ya tiene el bloque `ipam` (ver diff abajo). Si el cambio todavía vive en `dev`, mergear a `main` mediante PR revisado antes de la ventana — no aplicar el compose directamente desde `dev` en el host de producción.
2. Avisar a los usuarios del panel web (`http://172.18.208.162:8080`) de una ventana de mantenimiento corta (~2–5 min de downtime esperado, ver estimación abajo).
3. Verificar que no haya un incidente activo o trabajo en curso que dependa de los contenedores de producción en ese momento.
4. Tener a mano el commit/tag actual de `deploy/compose.yml` por si hace falta rollback (`git log -- deploy/compose.yml`).

### Diff aplicado en código (ya presente en el repo)

```yaml
networks:
  lasfocas_net:
    driver: bridge
    ipam:
      driver: default
      config:
        - subnet: 172.20.0.0/24
          gateway: 172.20.0.1
```

## Procedimiento (a ejecutar en la ventana de mantenimiento)

Todos los comandos se ejecutan desde la raíz del repo en el host de producción, con la rama/commit ya actualizado a la versión que incluye el cambio de red.

> **Recordatorio operativo (ver `docs/decisiones.md`, entrada 2026-07-29):** cualquier `docker compose` manual sobre `deploy/compose.yml` debe llevar siempre `--env-file .env` explícito, o Compose puede recrear `postgres` con variables vacías.

### Opción recomendada: usar el wrapper `./Start`

`./Start` (sin flags) ya encapsula correctamente el flujo `down --remove-orphans` → `up -d --build` → espera de Postgres healthy → migraciones Alembic → healthchecks de todos los servicios, con `--env-file .env` incluido:

```bash
./Start
```

Esto es equivalente a los pasos manuales de abajo, pero con las validaciones y esperas ya probadas en este repo. Es la vía preferida salvo que se necesite control granular paso a paso.

### Opción manual (paso a paso, para control granular o troubleshooting)

**1) Apagar los servicios afectados** (sin `-v`: no toca `postgres_data` ni el resto de los volúmenes):

```bash
docker compose -f deploy/compose.yml --env-file .env down --remove-orphans
```

Esto detiene y elimina los 6 contenedores `lasfocas-*` y, al no haber ningún contenedor externo (`external: true`) apuntando a la red, también elimina la red `lasfocas_lasfocas_net` — condición necesaria porque **Docker no permite cambiar la subred de una red existente sin recrearla**.

**2) Verificar que la red vieja quedó eliminada** (puede quedar trabada si algún contenedor ajeno al stack sigue conectado a ella):

```bash
docker network ls | grep lasfocas_lasfocas_net
```

Si el comando anterior sigue mostrando la red, identificar qué la retiene y forzar su eliminación:

```bash
docker network inspect lasfocas_lasfocas_net --format '{{range .Containers}}{{.Name}} {{end}}'
docker network rm lasfocas_lasfocas_net
```

**3) Levantar el stack con la nueva configuración** (ya trae `ipam.config` con `/24` desde `deploy/compose.yml`):

```bash
docker compose -f deploy/compose.yml --env-file .env up -d --build
```

**4) Migraciones Alembic** (si `./Start` no se usó, aplicarlas manualmente igual que hace el script):

```bash
docker compose -f deploy/compose.yml --env-file .env exec -T api \
  sh -lc "alembic -c /app/db/alembic.ini upgrade head"
```

## Verificación post-despliegue

```bash
# Subred efectivamente aplicada
docker network inspect lasfocas_lasfocas_net --format '{{json .IPAM.Config}}'
# Esperado: [{"Subnet":"172.20.0.0/24","Gateway":"172.20.0.1"}]

# Ruta conectada del host ya no ocupa el /16 completo
ip route | grep 172.20
# Esperado: "172.20.0.0/24 dev br-<id> proto kernel scope link src 172.20.0.1"
# (antes decía "172.20.0.0/16")

# Los 6 contenedores arriba y healthy
docker ps --filter "name=lasfocas-" --format "table {{.Names}}\t{{.Status}}"

# Conectividad interna (DNS de servicio) sigue funcionando
docker compose -f deploy/compose.yml --env-file .env exec -T web \
  curl -fsS -o /dev/null -w '%{http_code}\n' http://api:8000/health

# Panel accesible externamente
curl -fsS -o /dev/null -w '%{http_code}\n' http://172.18.208.162:8080/health
```

Si alguno de estos falla, ver **Rollback** abajo antes de cerrar la ventana.

## Rollback

Como ningún servicio usa `ipv4_address`, no hay IPs estáticas que revertir — el rollback es puramente el compose:

```bash
git log --oneline -- deploy/compose.yml   # ubicar el commit anterior al cambio de subred
git show <commit_anterior>:deploy/compose.yml > /tmp/compose.yml.rollback
cp /tmp/compose.yml.rollback deploy/compose.yml
docker compose -f deploy/compose.yml --env-file .env down --remove-orphans
docker compose -f deploy/compose.yml --env-file .env up -d --build
```

Volumen de datos intacto en todo momento (nunca se usa `-v`).

## Downtime estimado

2–5 minutos: `down` (~10–20s) + `up -d --build` con imágenes ya cacheadas (~30–60s) + espera de Postgres healthy y migraciones Alembic (~30–90s, según el mismo comportamiento observado al aplicar este cambio en dev) + healthchecks del resto de servicios (~30s).

## Hallazgo relacionado, no aplicado en este cambio

`scripts/firewall_hardening.sh` define `DOCKER_NET_CIDR=${DOCKER_NET_CIDR:-172.18.0.0/16}` como default para una regla NAT `MASQUERADE` sobre `MGMT_IFACE` (`ens224`, interfaz que no existe en este host — solo hay `ens192`). Ese default no coincide con ninguna red Docker real del stack (`172.17.0.0/16` bridge default, `172.19.0.0/24` dev, `172.20.0.0/24` prod tras este cambio), lo que sugiere que el script está pensado para otro host/entorno o quedó desactualizado. No se modificó porque toca reglas de firewall/NAT de producción y excede el alcance de este cambio (subredes de red Docker) — requiere revisión y confirmación explícita aparte.

---

# Pre-requisito obligatorio: secret `redis_password_v1` (2026-08-21)

## Estado

- **Preparado en código, pendiente de aplicar.** Misma política que el cambio de subred de arriba: `deploy/compose.yml` ya define los servicios `redis` y `botellas_recalculo_worker` y agrega el secret `redis_password_v1` al servicio `web`, pero **no se recreó ningún contenedor de producción**. Ver [docs/decisiones.md](decisiones.md), entrada 2026-08-21 (cont.), y [docs/infra.md](infra.md), sección "Caché Redis + worker dedicado + WebSocket para el visor de duplicados".
- Fecha de redacción: 2026-08-21 (pre-requisito documentado acá el 2026-08-22).
- Alcance: stack `lasfocas` (producción), archivo `deploy/compose.yml`, servicios `web`, `redis` y `botellas_recalculo_worker`.

## Por qué bloquea

`deploy/compose.yml` declara el secret file-based:

```yaml
secrets:
  redis_password_v1:
    file: ../.secrets/redis_password_v1.txt
```

y lo consume desde `web`, `redis` y `botellas_recalculo_worker`. Ese archivo **no existe todavía en el host de producción** — a propósito: nunca se generó un valor de prod desde el entorno de desarrollo. Docker Compose **no** degrada cuando el archivo de un secret declarado no existe: falla la creación del contenedor que lo referencia. Es decir, el próximo `up` que toque `web` (o los dos servicios nuevos) **rompe el arranque de `web`**, no sólo el de Redis. Verificado empíricamente durante la revisión final de la rama, no asumido.

## Qué hacer antes del `up` (en el host de producción, con acceso a `.secrets/`)

```bash
cd /ruta/al/repo
openssl rand -base64 32 > .secrets/redis_password_v1.txt
chmod 600 .secrets/redis_password_v1.txt
ls -l .secrets/redis_password_v1.txt   # esperado: -rw------- , tamaño ~45 bytes
```

Mismo procedimiento con el que se generó el de dev (`.secrets/Dev_redis_password_v1.txt`). `.secrets/` está en `.gitignore` (línea 8), así que el archivo nunca se commitea. No copiar el valor de dev: es otro entorno, otra credencial.

## Verificación post-despliegue

```bash
# Los dos servicios nuevos arriba y healthy
docker ps --filter "name=lasfocas-redis" --filter "name=lasfocas-botellas-recalculo-worker" \
  --format "table {{.Names}}\t{{.Status}}"

# Redis responde con la credencial del secret (desde adentro del contenedor, sin exponer el valor)
docker exec lasfocas-redis sh -c 'redis-cli -a "$(cat /run/secrets/redis_password_v1)" --no-auth-warning ping'
# Esperado: PONG

# El worker ve su loop vivo (el healthcheck ya valida que la respuesta no diga loop_muerto)
docker exec lasfocas-botellas-recalculo-worker curl -fsS http://localhost:8097/health

# El subscriber de `web` quedó suscripto al canal y NO cicla (debe mantenerse en 1 indefinidamente)
docker exec lasfocas-redis sh -c 'redis-cli -a "$(cat /run/secrets/redis_password_v1)" --no-auth-warning PUBSUB NUMSUB admin-notifications'
# Esperado: admin-notifications 1 — repetir varias veces en 60s; nunca debe caer a 0
```

## Rollback

Si algo falla, Redis **no es una dependencia dura** del sistema: todo el circuito de Botellas duplicadas degrada al cómputo síncrono de siempre (ver `docs/infra.md`). El rollback es volver `deploy/compose.yml` al commit anterior y recrear, igual que en la sección de subred; el archivo `.secrets/redis_password_v1.txt` puede quedar (no molesta) o borrarse.
