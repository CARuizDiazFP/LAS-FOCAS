# Nombre de archivo: mantenimiento_redes_produccion.md
# Ubicación de archivo: docs/mantenimiento_redes_produccion.md
# Descripción: Procedimiento para aplicar en ventana de mantenimiento el cambio de subred Docker de producción (/16 → /24)

# Cambio de subred Docker en producción (/16 → /24)

## Estado

- **Preparado en código, pendiente de aplicar.** El cambio descrito acá ya está en `deploy/compose.yml` (rama `dev`, no desplegado) pero **no tiene efecto sobre los contenedores en ejecución** hasta que se corra `docker compose down` + `up` sobre ese archivo. Ver [docs/decisiones.md](decisiones.md), entrada 2026-08-05.
- Fecha de redacción: 2026-08-05.
- Alcance: stack `lasfocas` (producción), archivo `deploy/compose.yml`, red `lasfocas_net`.

## Por qué

Igual que se detectó y corrigió en el entorno dev (ver entrada 2026-08-05 en `docs/decisiones.md`), ninguna red Docker de este repo declaraba `ipam.config.subnet` explícito. Docker asigna por default bloques `/16` de su pool interno, y la red de producción quedó en **`172.20.0.0/16`**. Un bloque `/16` completo agrega una ruta conectada en el kernel del host que tiene prioridad sobre cualquier ruta hacia un destino real de la intranet que caiga dentro de ese mismo `/16` — si algún día existe un host de intranet en `172.20.x.x`, quedaría inalcanzable desde la VM exactamente como pasó con `172.19.217.20` en dev. Achicar a `/24` reduce el bloque secuestrado de 65 536 direcciones a 256, minimizando drásticamente la superficie de colisión.

## Estado actual vs. estado deseado

| | Actual (en ejecución) | Deseado (en `deploy/compose.yml`, código) |
|---|---|---|
| Subred `lasfocas_net` | `172.20.0.0/16` (asignada por default de Docker) | `172.20.0.0/24` (explícita vía `ipam.config`) |
| Gateway | `172.20.0.1` | `172.20.0.1` (sin cambio) |
| IPs de contenedores | `.2`–`.7` (dinámicas, sin `ipv4_address`) | Mismas, siguen dinámicas dentro de `.1`–`.254` |
| Contenedores en la red | `lasfocas-postgres`, `lasfocas-api`, `lasfocas-web`, `lasfocas-nlp_intent-1`, `lasfocas-office`, `lasfocas-slack-baneo-worker` | Sin cambios |

**Auditoría de IPs estáticas:** se revisó `deploy/compose.yml` completo — ningún servicio usa `ipv4_address`. Todas las IPs las asigna Docker dinámicamente al arrancar cada contenedor, así que no hay ninguna IP fuera de rango que reasignar. Si en el futuro se agrega una IP estática a algún servicio, debe quedar entre `172.20.0.2` y `172.20.0.254` (`.1` es el gateway).

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
