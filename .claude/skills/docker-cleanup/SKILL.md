---
name: docker-cleanup
description: "Usar cuando haya que limpiar imágenes, contenedores o build cache de Docker sin tocar volúmenes persistentes"
argument-hint: "Describe alcance, por ejemplo: limpiar imágenes colgantes y builder cache"
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .claude/skills/docker-cleanup/SKILL.md
# Descripción: Skill para limpieza segura de recursos Docker (imágenes, contenedores, cache) sin afectar volúmenes (mirror de .agentes-comunes/skills/docker-cleanup/SKILL.md — fuente de verdad)

# Habilidad: Limpieza Docker

Este skill proporciona comandos seguros para liberar espacio de Docker **sin eliminar volúmenes de datos**.

## ⚠️ Regla Fundamental

> **NUNCA ejecutar `docker volume prune`** - Los volúmenes contienen datos persistentes (PostgreSQL, uploads, etc.)

## 🔒 Host compartido dev + prod: imágenes protegidas

El servidor (`srv-xdc-apps-focal-01`) corre **en el mismo daemon Docker** el stack de prod
(`lasfocas-*`) y el de dev (`lasfocasdev-*`). Por eso acá **no existe un "host de dev" donde un
prune agresivo sea inofensivo**: `docker image prune -a` y `docker system prune -a` borran toda
imagen sin contenedor, y en este host eso incluye (real, 2026-10-23, ver `docs/cierres/2026-10-23.md`):

| Imagen | Por qué no tiene contenedor | Qué rompe si se borra |
|---|---|---|
| `lasfocas-<svc>:pre-deploy-YYYYMMDD`, `:pre-hotfix-YYYYMMDD` | Son el rollback de prod | Se pierde la vuelta atrás del último deploy/hotfix |
| `focas-base:latest` | Es imagen base, no se ejecuta | Falla el build de `nlp_intent` y `fo_monitor_worker` (`FROM focas-base:latest`) |

Regla: las imágenes **sólo se retiran por tag exacto** (`docker image rm <repo>:<tag>`), con OK del
usuario, y nunca lo que conserva la convención de "Rollback de prod" (abajo): el último juego
`:pre-deploy-*`, `focas-base:latest` y la base anterior. `docker image prune -f` sin `-a` (sólo
dangling) sigue siendo seguro.

```bash
# Inventario: imágenes sin contenedor, marcando las protegidas
docker images --format '{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}' | sort
docker ps -a --format '{{.Image}}' | sort -u     # las que SÍ están en uso
```

## 📊 Categorías de Limpieza

| Categoría | Riesgo | Recuperable |
|-----------|--------|-------------|
| Imágenes dangling | 🟢 Bajo | Sí (rebuild) |
| Imágenes sin uso | 🟡 Medio | Sí (pull/rebuild) |
| Contenedores detenidos | 🟢 Bajo | No aplica |
| Build cache | 🟢 Bajo | Sí (rebuild más lento) |
| Volúmenes | 🔴 PROHIBIDO | ❌ NO TOCAR |

## 🔍 Comandos de Análisis (Solo Lectura)

### Listar Imágenes Sin Uso

```bash
# Imágenes huérfanas (dangling) - seguro eliminar
docker images -f "dangling=true" --format "table {{.ID}}\t{{.Size}}\t{{.CreatedSince}}"

# Contar imágenes dangling
docker images -f "dangling=true" -q | wc -l

# Calcular espacio de imágenes dangling
docker images -f "dangling=true" --format "{{.Size}}" | \
    awk '{
        if ($1 ~ /GB/) sum += $1*1024
        else if ($1 ~ /MB/) sum += $1
        else if ($1 ~ /KB/) sum += $1/1024
    } END {printf "%.2f MB\n", sum}'

# Imágenes no usadas por ningún contenedor
docker images --format "{{.Repository}}:{{.Tag}}" | while read img; do
    if [ "$(docker ps -a -q --filter ancestor="$img" | wc -l)" -eq 0 ]; then
        SIZE=$(docker images "$img" --format "{{.Size}}")
        echo "$img: $SIZE"
    fi
done
```

### Listar Contenedores Detenidos

```bash
# Contenedores con status=exited
docker ps -a -f "status=exited" --format "table {{.Names}}\t{{.Image}}\t{{.Size}}\t{{.Status}}"

# Contar contenedores detenidos
docker ps -a -f "status=exited" -q | wc -l

# Contenedores creados pero nunca iniciados
docker ps -a -f "status=created" --format "table {{.Names}}\t{{.Image}}\t{{.CreatedAt}}"
```

### Analizar Build Cache

```bash
# Resumen de build cache
docker builder du

# Detalle de cache (si está disponible)
docker builder du --verbose 2>/dev/null | head -50

# Tamaño total de build cache
docker system df --format "{{.Type}}\t{{.Size}}" | grep "Build Cache"
```

### Verificar Volúmenes (Solo Informativo)

```bash
# ⚠️ SOLO MOSTRAR, NUNCA ELIMINAR
echo "📦 VOLÚMENES DOCKER (solo informativo)"
docker system df -v 2>/dev/null | grep -A 100 "Local Volumes space usage:" | head -20

# Volúmenes del proyecto
docker volume ls --format "{{.Name}}" | grep -iE "focas|postgres|bot|web|uploads|reports"
```

## 🧹 Comandos de Limpieza

### Nivel 1: Limpieza Segura (Recomendado)

```bash
# 1. Eliminar imágenes dangling (huérfanas)
docker image prune -f

# 2. Eliminar contenedores detenidos
docker container prune -f

# 3. Limpiar redes no utilizadas
docker network prune -f
```

### Nivel 2: Retiro de Imágenes Sin Uso (por tag exacto)

> `docker image prune -a -f` está **prohibido en este host** (ver "Host compartido dev + prod"):
> borra los rollback de prod y `focas-base`. Retirar por tag exacto lo que el usuario aprobó.

```bash
# Rollbacks superados según "Rollback de prod" (abajo) — confirmar con el usuario
docker image rm lasfocas-api:pre-hotfix-20261019 lasfocas-web:pre-hotfix-20261019

# Verificar espacio liberado (las imágenes comparten capas: lo liberado suele ser menor
# que la suma de los SIZE de `docker images`)
docker system df
```

### Nivel 3: Limpieza de Build Cache

```bash
# Limpiar todo el build cache
docker builder prune -f

# Limpiar cache de más de 24 horas
docker builder prune --filter "until=24h" -f

# Limpiar cache de más de 7 días
docker builder prune --filter "until=168h" -f
```

### Limpieza Combinada (Todo Excepto Volúmenes)

> **Prohibida en este host**: el servidor de dev **es** el host productivo (mismo daemon Docker).
> `docker system prune -a` borra toda imagen sin contenedor, incluidos los rollback de prod y
> `focas-base`. Usar los niveles 1 y 3 y el nivel 2 por tag exacto.

```bash
# Equivalente seguro: todo lo no persistente, sin imágenes con tag
docker image prune -f        # sólo dangling
docker container prune -f
docker builder prune -f
docker network prune -f
```

## 📋 Script de Limpieza Interactivo

```bash
#!/bin/bash
# Limpieza Docker segura para LAS-FOCAS

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          LIMPIEZA DOCKER - LAS-FOCAS                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"

# Análisis previo
echo -e "\n📊 ESTADO ACTUAL"
docker system df

# Calcular espacio recuperable
IMAGES_RECLAIM=$(docker system df --format "{{.Type}}\t{{.Reclaimable}}" | grep Images | awk '{print $2}')
CONTAINERS_RECLAIM=$(docker system df --format "{{.Type}}\t{{.Reclaimable}}" | grep Containers | awk '{print $2}')
CACHE_RECLAIM=$(docker system df --format "{{.Type}}\t{{.Reclaimable}}" | grep "Build Cache" | awk '{print $2}')

echo -e "\n💾 ESPACIO RECUPERABLE"
echo "─────────────────────────────"
echo "  Imágenes:     $IMAGES_RECLAIM"
echo "  Contenedores: $CONTAINERS_RECLAIM"
echo "  Build Cache:  $CACHE_RECLAIM"

# Confirmar limpieza
echo -e "\n⚠️  Los volúmenes NO serán eliminados (datos seguros)"
read -p "¿Proceder con la limpieza? (s/N): " CONFIRM

if [[ "$CONFIRM" =~ ^[sS]$ ]]; then
    echo -e "\n🧹 Ejecutando limpieza..."

    echo "  → Limpiando imágenes dangling..."
    docker image prune -f

    echo "  → Limpiando contenedores detenidos..."
    docker container prune -f

    echo "  → Limpiando build cache..."
    docker builder prune -f

    echo "  → Limpiando redes no utilizadas..."
    docker network prune -f

    echo -e "\n✅ LIMPIEZA COMPLETADA"
    echo "─────────────────────────────"
    docker system df
else
    echo "❌ Limpieza cancelada"
fi
```

## 🏷️ Recursos efímeros de sesión (agentes)

Todo contenedor, red, volumen o imagen **temporal** que un agente cree para probar algo (un
Postgres descartable, un `docker run` de diagnóstico, una red de prueba, una imagen `:smoke`) se crea
etiquetado con la sesión. Estos son los recursos que se limpian primero cuando el disco queda por
debajo del piso de `disk-analysis` ("Piso de disco para agentes").

```bash
docker run -d --label lasfocas.lifecycle=ephemeral --label lasfocas.session=<agent-id> ...
docker buildx build --load --label lasfocas.lifecycle=ephemeral --label lasfocas.session=<agent-id> -t <repo>:<agent-id> ...
docker network create --label lasfocas.lifecycle=ephemeral --label lasfocas.session=<agent-id> <red>
docker volume create --label lasfocas.lifecycle=ephemeral --label lasfocas.session=<agent-id> <vol>
```

Al cierre (`cierre-sesion`) se eliminan **por ID exacto**, nunca por prune ni por patrón de nombre:

```bash
# 1. Inventario de la sesión (sólo lectura)
docker ps -a        --filter label=lasfocas.session=<agent-id> --format '{{.ID}} {{.Names}} {{.Status}}'
docker network ls   --filter label=lasfocas.session=<agent-id> --format '{{.ID}} {{.Name}}'
docker volume ls    --filter label=lasfocas.session=<agent-id> --format '{{.Name}}'
docker images       --filter label=lasfocas.session=<agent-id> --format '{{.Repository}}:{{.Tag}} {{.ID}}'
docker images --format '{{.Repository}}:{{.Tag}}' | grep -E ':(<agent-id>|smoke)$'   # tags propios sin etiqueta

# 2. Antes de borrar: mounts del contenedor y consumidores de la red/volumen
docker inspect -f '{{json .Mounts}}' <container-id>
docker ps -a --filter volume=<vol> --format '{{.ID}} {{.Names}}'
docker network inspect -f '{{json .Containers}}' <network-id>

# 3. Borrado por ID exacto (-v sólo quita los volúmenes ANÓNIMOS de ese contenedor)
docker container rm -v <container-id>
docker network rm <network-id>
docker volume rm <vol>
docker image rm <repo>:<tag>      # por tag exacto; nunca rmi por ID si otro tag apunta a la misma imagen
```

Un recurso sin `lasfocas.session=<agent-id>` (o, en imágenes, sin tag propio) **no es de la sesión** y no se toca, aunque parezca
huérfano. Nunca etiquetar como efímero un recurso del stack (`lasfocas*`, `postgres_data`, etc.).

## ♻️ Rollback de prod: se conserva sólo el último juego (regla única)

Esta es la **única** definición de la convención de rollback (decisión del usuario del 2026-10-27).
`AGENTS.md`, `disk-analysis`, `/mantenimiento-disco`, `docs/maintenance_profiles.md` y
`docs/despliegue_produccion.md` la citan; si cambia, se cambia acá. Motivo: el disco (40 GB
compartidos por prod y dev); cada juego de rollback ocupa ~0,9 GB reales.

**Qué se conserva**

| Imagen | Qué es |
|---|---|
| `lasfocas-<svc>:latest` | La imagen que corre prod (la usa compose) |
| El tag de rollback **más reciente por servicio**: `:pre-deploy-YYYYMMDD` o `:pre-hotfix-YYYYMMDD` | Un solo juego: lo que corría antes del último deploy (todos los servicios, misma fecha). Si después hubo un hotfix, sus `:pre-hotfix-*` reemplazan al `:pre-deploy-*` sólo en los servicios que tocó |
| `focas-base:latest` + la base anterior | La base actual y la previa. La previa se reconoce por el label `focas.requirements.hash`, no por el nombre del tag (`req-<hash>` o `pre-<algo>`): es la base de lo que corre prod mientras prod no tenga las dependencias nuevas |

No hay tag `:rollback` rotativo: la convención vieja (`current -> :rollback`) queda retirada. Los
deploys y hotfix reales etiquetan con fecha, y en el host no hay ningún `:rollback` (verificado
2026-10-27).

**Cuándo y cómo se borra el resto**

1. Antes del deploy (o hotfix), etiquetar lo que corre:
   `docker tag lasfocas-<svc>:latest lasfocas-<svc>:pre-deploy-$(date +%Y%m%d)` por cada servicio que
   se va a reconstruir. Ver `docs/despliegue_produccion.md`.
2. Recién **después de verificar el deploy** (healthy, smoke, prueba del usuario si corresponde), el juego
   anterior queda superado: todo tag `:pre-deploy-*`/`:pre-hotfix-*` de un servicio que tenga otro más
   nuevo. Lo mismo para las bases `focas-base` más viejas que la anterior.
3. Se borran **por tag exacto**, listando los tags y **con confirmación del usuario en esa sesión**:
   ```bash
   docker images --format '{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.CreatedSince}}' | grep -E ':(pre-deploy|pre-hotfix)-' | sort
   docker ps -a --filter ancestor=<repo>:<tag> --format '{{.Names}}'   # debe salir vacío
   docker image rm <repo>:<tag-superado> ...                           # nunca -f
   ```
4. Si el deploy no valida, volver al juego vigente **antes** de borrar nada:
   `docker tag lasfocas-<svc>:pre-deploy-<fecha> lasfocas-<svc>:latest` + `up -d --no-deps
   --force-recreate` de esos servicios.

Nunca `docker system prune`, `docker image prune -a` ni `docker volume prune` para esta rotación.

## 🛡️ Comandos Prohibidos

```bash
# ❌ NUNCA EJECUTAR - Eliminaría datos de PostgreSQL, uploads, etc.
docker volume prune
docker system prune --volumes

# ❌ NUNCA EJECUTAR EN ESTE HOST - Borraría rollbacks de prod y focas-base (host compartido)
docker image prune -a
docker system prune -a

# ❌ NUNCA EJECUTAR - Eliminaría contenedores activos
docker rm -f $(docker ps -aq)
```

## 📌 Verificación Post-Limpieza

```bash
# Verificar que los volúmenes siguen intactos
docker volume ls

# Verificar servicios activos
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Verificar espacio liberado
df -h /

# Nuevo estado de Docker
docker system df
```

## 🔄 Recomendaciones de Mantenimiento

| Frecuencia | Acción |
|------------|--------|
| Semanal | `docker image prune -f` + `docker container prune -f` |
| Después de deploys | `docker builder prune --filter "until=24h" -f` |
| Tras un deploy verificado | Retirar el juego de rollback superado por tag exacto, con OK ("Rollback de prod") |
| Emergencia (disco >85%) | Script de limpieza + consumidores fuera del repo (`disk-analysis` §7) |

## 🔗 Skills Relacionados

- [disk-analysis](../disk-analysis/SKILL.md) - Diagnóstico de uso de disco
- [logs-cleanup](../logs-cleanup/SKILL.md) - Gestión de archivos de log
- [temp-cleanup](../temp-cleanup/SKILL.md) - Limpieza de temporales
