# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agentes-comunes/skills/docker-cleanup/SKILL.md
# Descripción: Skill para limpieza segura de recursos Docker (imágenes, contenedores, cache) sin afectar volúmenes

---
name: docker-cleanup
description: "Usar cuando haya que limpiar imágenes, contenedores o build cache de Docker sin tocar volúmenes persistentes"
argument-hint: "Describe alcance, por ejemplo: limpiar imágenes colgantes y builder cache"
---

# Habilidad: Limpieza Docker

Este skill proporciona comandos seguros para liberar espacio de Docker **sin eliminar volúmenes de datos**.

## ⚠️ Regla Fundamental

> **NUNCA ejecutar `docker volume prune`** - Los volúmenes contienen datos persistentes (PostgreSQL, uploads, etc.)

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

### Nivel 2: Limpieza Agresiva de Imágenes

```bash
# Eliminar TODAS las imágenes no usadas por contenedores activos
# ⚠️ Esto forzará pulls/rebuilds en próximo deploy
docker image prune -a -f

# Verificar espacio liberado
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

> **No usar en el host productivo**: `docker system prune -a` borra toda imagen sin contenedor,
> incluida la imagen `rollback` que exige la política de retención (sección siguiente). En prod,
> retirar imágenes sólo por ID exacto según esa política.

```bash
# ⚠️ IMPORTANTE: Este comando NO incluye volúmenes
# El flag --volumes está OMITIDO intencionalmente

docker system prune -a -f

# Verificar que los volúmenes siguen intactos
docker volume ls
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

Todo contenedor, red o volumen **temporal** que un agente cree para probar algo (un Postgres
descartable, un `docker run` de diagnóstico, una red de prueba) se crea etiquetado con la sesión:

```bash
docker run -d --label lasfocas.lifecycle=ephemeral --label lasfocas.session=<agent-id> ...
docker network create --label lasfocas.lifecycle=ephemeral --label lasfocas.session=<agent-id> <red>
docker volume create --label lasfocas.lifecycle=ephemeral --label lasfocas.session=<agent-id> <vol>
```

Al cierre (`cierre-sesion`) se eliminan **por ID exacto**, nunca por prune ni por patrón de nombre:

```bash
# 1. Inventario de la sesión (sólo lectura)
docker ps -a        --filter label=lasfocas.session=<agent-id> --format '{{.ID}} {{.Names}} {{.Status}}'
docker network ls   --filter label=lasfocas.session=<agent-id> --format '{{.ID}} {{.Name}}'
docker volume ls    --filter label=lasfocas.session=<agent-id> --format '{{.Name}}'

# 2. Antes de borrar: mounts del contenedor y consumidores de la red/volumen
docker inspect -f '{{json .Mounts}}' <container-id>
docker ps -a --filter volume=<vol> --format '{{.ID}} {{.Names}}'
docker network inspect -f '{{json .Containers}}' <network-id>

# 3. Borrado por ID exacto (-v sólo quita los volúmenes ANÓNIMOS de ese contenedor)
docker container rm -v <container-id>
docker network rm <network-id>
docker volume rm <vol>
```

Un recurso sin `lasfocas.session=<agent-id>` **no es de la sesión** y no se toca, aunque parezca
huérfano. Nunca etiquetar como efímero un recurso del stack (`lasfocas*`, `postgres_data`, etc.).

## ♻️ Retención de imágenes en producción: `current` + 1 `rollback`

En el host productivo se conservan, por servicio, sólo dos imágenes: la activa (`current`, el tag
`lasfocas-<servicio>:latest` que usa compose) y **un único** `rollback` inmediato y validado
(`lasfocas-<servicio>:rollback`). Rotación en cada despliegue:

```bash
SVC=api   # repetir por servicio reconstruido
# 1. Recordar el rollback que va a quedar desplazado (puede no existir)
OLD_RB="$(docker image inspect -f '{{.Id}}' lasfocas-$SVC:rollback 2>/dev/null || true)"
# 2. current -> rollback (la imagen validada que está corriendo hoy)
docker tag lasfocas-$SVC:latest lasfocas-$SVC:rollback
# 3. Build + up del nuevo current (ver docker-rebuild) y validar healthchecks/smoke
# 4. Recién con el current nuevo validado, retirar el rollback desplazado por ID exacto
NEW_RB="$(docker image inspect -f '{{.Id}}' lasfocas-$SVC:rollback)"
if [ -n "$OLD_RB" ] && [ "$OLD_RB" != "$NEW_RB" ]; then
  docker ps -a --filter ancestor="$OLD_RB" --format '{{.ID}} {{.Names}}'   # debe salir vacío
  docker image rm "$OLD_RB"   # falla solo si algún contenedor todavía la usa: no forzar
fi
```

Nunca `docker system prune`, `docker image prune -a` ni `docker volume prune` en prod para esta
rotación. Si el current nuevo no valida, volver al rollback (`docker tag lasfocas-$SVC:rollback
lasfocas-$SVC:latest` + `up -d`) **antes** de retirar nada.

## 🛡️ Comandos Prohibidos

```bash
# ❌ NUNCA EJECUTAR - Eliminaría datos de PostgreSQL, uploads, etc.
docker volume prune
docker system prune --volumes

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
| Mensual | `docker image prune -a -f` (en horario de mantenimiento) |
| Emergencia (disco >90%) | Script completo de limpieza |

## 🔗 Skills Relacionados

- [disk-analysis](../disk-analysis/SKILL.md) - Diagnóstico de uso de disco
- [logs-cleanup](../logs-cleanup/SKILL.md) - Gestión de archivos de log
- [temp-cleanup](../temp-cleanup/SKILL.md) - Limpieza de temporales
