# Nombre de archivo: SKILL.md
# Ubicación de archivo: .agentes-comunes/skills/disk-analysis/SKILL.md
# Descripción: Skill para análisis y diagnóstico de uso de disco en el entorno LAS-FOCAS

---
name: disk-analysis
description: "Usar cuando haya que diagnosticar uso de disco, espacio consumido por Docker, logs, volúmenes o artefactos del proyecto"
argument-hint: "Describe foco del análisis, por ejemplo: revisar consumo de disco de Docker y Logs"
---

# Habilidad: Análisis de Disco

Este skill proporciona comandos y procedimientos para diagnosticar el uso de disco en el entorno LAS-FOCAS.

## 📊 Umbrales de Alerta

Perfiles operativos recomendados: `docs/maintenance_profiles.md`.

| Recurso | 🟢 Normal | 🟡 Advertencia | 🔴 Crítico |
|---------|-----------|----------------|------------|
| Disco general | <70% | 70-85% | >85% |
| Volúmenes Docker | <1GB | 1-2GB | >2GB |
| Logs del proyecto | <300MB | 300-500MB | >500MB |
| Build cache Docker | <5GB | 5-15GB | >15GB |

## 🔍 Comandos de Diagnóstico

> Las rutas relativas (`./Logs/`, `.`) asumen que se corre desde la raíz del checkout de control
> (`/home/support-focal-01/LAS-FOCAS`). En este host `sudo` pide contraseña, así que `sudo du` falla
> en sesiones no interactivas: usar `docker system df -v` para el desglose de Docker. El disco del
> repo y el de Docker son la **misma** partición (`/dev/sda1`, 40 G): el home del usuario compite
> por el mismo espacio (ver §7).

### 1. Uso General de Disco

```bash
# Vista general de todas las particiones
df -h

# Solo partición raíz y Docker
df -h / /var/lib/docker 2>/dev/null

# Espacio disponible en formato script
DISK_USAGE=$(df / --output=pcent | tail -1 | tr -d ' %')
if [ "$DISK_USAGE" -gt 85 ]; then
    echo "🔴 CRÍTICO: Disco al ${DISK_USAGE}%"
elif [ "$DISK_USAGE" -gt 70 ]; then
    echo "🟡 ADVERTENCIA: Disco al ${DISK_USAGE}%"
else
    echo "🟢 OK: Disco al ${DISK_USAGE}%"
fi
```

### 2. Diagnóstico Docker Completo

```bash
# Resumen de uso Docker (imágenes, contenedores, volúmenes, cache)
docker system df

# Vista detallada con desglose
docker system df -v

# Solo imágenes ordenadas por tamaño
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | sort -k3 -hr

# Imágenes huérfanas (dangling)
docker images -f "dangling=true" --format "{{.ID}}: {{.Size}}"

# Contenedores detenidos
docker ps -a -f "status=exited" --format "table {{.Names}}\t{{.Size}}\t{{.Status}}"

# Build cache detallado
docker builder du --verbose 2>/dev/null || docker builder du
```

### 3. Análisis de Volúmenes Docker

```bash
# Listar volúmenes con tamaño
docker system df -v 2>/dev/null | grep -A 100 "Local Volumes space usage:"

# Volúmenes del proyecto LAS-FOCAS
docker volume ls --format "{{.Name}}" | grep -E "lasfocas|focas" | while read vol; do
    SIZE=$(docker system df -v 2>/dev/null | grep "$vol" | awk '{print $NF}')
    echo "$vol: $SIZE"
done

# Verificar volúmenes que superan 2GB (advertencia)
docker system df -v 2>/dev/null | grep -E "^[a-z]" | awk '$NF ~ /GB/ && $NF+0 > 2 {print "⚠️ ADVERTENCIA: " $1 " = " $NF}'
```

### 4. Top Directorios Más Pesados

```bash
# Top 20 directorios en /var/lib/docker (requiere sudo con contraseña; si no, docker system df -v)
sudo du -h --max-depth=2 /var/lib/docker 2>/dev/null | sort -hr | head -20

# Top 10 directorios en el proyecto
du -h --max-depth=2 . 2>/dev/null | sort -hr | head -10

# Archivos más grandes en el proyecto (>10MB)
find . -type f -size +10M -exec ls -lh {} \; 2>/dev/null | awk '{print $5, $9}'
```

### 5. Análisis de Logs y Reports

```bash
# Tamaño total de logs del proyecto (Logs/ = prod, Logs/dev/ = dev; ver logs-cleanup)
du -sh ./Logs/ ./Logs/dev/ 2>/dev/null

# Detalle de archivos de log
ls -lah ./Logs/*.log* 2>/dev/null

# Tamaño de informes generados
du -sh ./Reports/ 2>/dev/null

# Desglose de Reports por subcarpeta
du -h --max-depth=1 ./Reports/ 2>/dev/null

# Archivos en devs/output (desarrollo)
du -sh ./devs/output/ 2>/dev/null
```

### 6. Caché Python (__pycache__)

```bash
# Total de __pycache__ en el proyecto
find . -type d -name "__pycache__" -exec du -sh {} \; 2>/dev/null

# Suma total
find . -type d -name "__pycache__" -exec du -b {} \; 2>/dev/null | awk '{sum+=$1} END {printf "Total __pycache__: %.2f MB\n", sum/1024/1024}'

# Archivos .pyc individuales
find . -name "*.pyc" -type f | wc -l
```

### 7. Consumidores fuera del repo (home del usuario)

Con el disco crítico, lo grande suele estar **fuera** del repo y de Docker. Real, 2026-10-23
(89 % → 74 %): de ~6,5 GB recuperados, 2,6 GB eran servidores viejos de VS Code y ~0,9 GB dumps
de prod en el home.

```bash
du -sh ~/* ~/.[a-z]* 2>/dev/null | sort -hr | head -20
du -sh ~/.vscode-server/cli/servers/* ~/.vscode-server/extensions/* 2>/dev/null | sort -hr | head -15
du -sh /tmp/* 2>/dev/null | sort -hr | head -5
```

| Consumidor | Qué es | Cómo limpiarlo sin romper nada |
|---|---|---|
| `~/.vscode-server/cli/servers/Stable-*` | Una copia del server (~650 MB) por cada versión de VS Code que se conectó | Conservar la que **está corriendo** (`ps -eo args \| grep -o 'servers/Stable-[0-9a-f]*' \| sort \| uniq -c`) y la primera de `lru.json`. Ojo: la que corre puede **no** estar en `lru.json` (real: corría una de septiembre ausente de la lista) |
| `~/.vscode-server/extensions/` versiones viejas | Listadas en `extensions/.obsolete` | **No borrarlas a mano**: la sesión abierta puede estar ejecutando justo la versión obsoleta (real: `anthropic.claude-code-2.1.308`, la de esta misma sesión de Claude). VS Code las borra solo al recargar la ventana (*Developer: Reload Window*) |
| `~/lasfocas-prod-sync-YYYYMMDD/*.dump` | Respaldos de la DB de prod (~180 MB c/u) tomados antes de cada deploy | Datos de prod: confirmar con el usuario. Conservar al menos los del último deploy; los `pre_deploy` y `ventana` del mismo día suelen pesar igual |
| `~/.cache/puccinialin` | Toolchain Rust que baja pip al compilar paquetes con maturin | Borrable; se vuelve a bajar si hace falta |
| `/tmp/pytest-of-$USER`, `~/.cache/pip`, `~/.npm` | Cachés de herramientas | Borrables (`temp-cleanup`) |

## 📋 Script de Diagnóstico Completo

```bash
#!/bin/bash
# Diagnóstico completo de disco para LAS-FOCAS

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          DIAGNÓSTICO DE DISCO - LAS-FOCAS                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"

# 1. Estado general
echo -e "\n📊 ESTADO GENERAL DEL DISCO"
echo "─────────────────────────────"
df -h / | tail -1 | awk '{
    usage = $5+0
    if (usage > 85) status = "🔴 CRÍTICO"
    else if (usage > 70) status = "🟡 ADVERTENCIA"
    else status = "🟢 OK"
    printf "Uso: %s (%s) | Disponible: %s | Total: %s\n", $5, status, $4, $2
}'

# 2. Docker
echo -e "\n🐳 RESUMEN DOCKER"
echo "─────────────────────────────"
docker system df --format "table {{.Type}}\t{{.TotalCount}}\t{{.Size}}\t{{.Reclaimable}}"

# 3. Imágenes sin uso
DANGLING=$(docker images -f "dangling=true" -q | wc -l)
if [ "$DANGLING" -gt 0 ]; then
    echo -e "\n⚠️  Imágenes huérfanas (dangling): $DANGLING"
fi

# 4. Contenedores detenidos
EXITED=$(docker ps -a -f "status=exited" -q | wc -l)
if [ "$EXITED" -gt 0 ]; then
    echo "⚠️  Contenedores detenidos: $EXITED"
fi

# 5. Volúmenes (solo informativo)
echo -e "\n📦 VOLÚMENES (solo informativo, no eliminar)"
echo "─────────────────────────────"
docker volume ls --format "{{.Name}}" | while read vol; do
    echo "  • $vol"
done

# 6. Logs y Reports
echo -e "\n📁 ARCHIVOS DEL PROYECTO"
echo "─────────────────────────────"
echo "  Logs:    $(du -sh ./Logs/ 2>/dev/null | cut -f1)"
echo "  Reports: $(du -sh ./Reports/ 2>/dev/null | cut -f1)"
echo "  Cache:   $(find . -type d -name '__pycache__' -exec du -b {} \; 2>/dev/null | awk '{sum+=$1} END {printf "%.1f MB", sum/1024/1024}')"

echo -e "\n═══════════════════════════════════════════════════════════════"
```

## 📌 Interpretación de Resultados

### Docker System DF

| Columna | Significado |
|---------|-------------|
| TYPE | Tipo de recurso (Images, Containers, Volumes, Build Cache) |
| TOTAL | Cantidad total de elementos |
| ACTIVE | Elementos en uso activo |
| SIZE | Tamaño total en disco |
| RECLAIMABLE | Espacio que puede liberarse sin afectar servicios activos |

### Acciones Recomendadas por Estado

| Estado | Acción |
|--------|--------|
| 🟢 OK (<70%) | Monitoreo regular, sin acción requerida |
| 🟡 Advertencia (70-85%) | Planificar limpieza preventiva |
| 🔴 Crítico (>85%) | Ejecutar limpieza inmediata |

## 🔗 Skills Relacionados

- [docker-cleanup](../docker-cleanup/SKILL.md) - Limpieza de recursos Docker
- [logs-cleanup](../logs-cleanup/SKILL.md) - Gestión de archivos de log
- [temp-cleanup](../temp-cleanup/SKILL.md) - Limpieza de temporales y caché
