# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/disk-analysis/SKILL.md
# Descripción: Skill para análisis y diagnóstico de uso de disco en el entorno LAS-FOCAS

---
name: disk-analysis
description: "Usar cuando haya que diagnosticar uso de disco, espacio consumido por Docker, logs, volúmenes o artefactos del proyecto"
argument-hint: "Describe foco del análisis, por ejemplo: revisar consumo de disco de Docker y Logs"
---

# Habilidad: Análisis de Disco

Este skill proporciona comandos y procedimientos para diagnosticar el uso de disco en el entorno LAS-FOCAS.

## 📊 Umbrales de Alerta

| Recurso | 🟢 Normal | 🟡 Advertencia | 🔴 Crítico |
|---------|-----------|----------------|------------|
| Disco general | <70% | 70-85% | >85% |
| Volúmenes Docker | <1GB | 1-2GB | >2GB |
| Logs del proyecto | <300MB | 300-500MB | >500MB |
| Build cache Docker | <5GB | 5-15GB | >15GB |

## 🔍 Comandos de Diagnóstico

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
# Top 20 directorios en /var/lib/docker (requiere sudo)
sudo du -h --max-depth=2 /var/lib/docker 2>/dev/null | sort -hr | head -20

# Top 10 directorios en el proyecto
du -h --max-depth=2 /home/focal/proyectos/LAS-FOCAS 2>/dev/null | sort -hr | head -10

# Archivos más grandes en el proyecto (>10MB)
find /home/focal/proyectos/LAS-FOCAS -type f -size +10M -exec ls -lh {} \; 2>/dev/null | awk '{print $5, $9}'
```

### 5. Análisis de Logs y Reports

```bash
# Tamaño total de logs del proyecto
du -sh /home/focal/proyectos/LAS-FOCAS/Logs/ 2>/dev/null

# Detalle de archivos de log
ls -lah /home/focal/proyectos/LAS-FOCAS/Logs/*.log* 2>/dev/null

# Tamaño de informes generados
du -sh /home/focal/proyectos/LAS-FOCAS/Reports/ 2>/dev/null

# Desglose de Reports por subcarpeta
du -h --max-depth=1 /home/focal/proyectos/LAS-FOCAS/Reports/ 2>/dev/null

# Archivos en devs/output (desarrollo)
du -sh /home/focal/proyectos/LAS-FOCAS/devs/output/ 2>/dev/null
```

### 6. Caché Python (__pycache__)

```bash
# Total de __pycache__ en el proyecto
find /home/focal/proyectos/LAS-FOCAS -type d -name "__pycache__" -exec du -sh {} \; 2>/dev/null

# Suma total
find /home/focal/proyectos/LAS-FOCAS -type d -name "__pycache__" -exec du -b {} \; 2>/dev/null | awk '{sum+=$1} END {printf "Total __pycache__: %.2f MB\n", sum/1024/1024}'

# Archivos .pyc individuales
find /home/focal/proyectos/LAS-FOCAS -name "*.pyc" -type f | wc -l
```

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
echo "  Logs:    $(du -sh /home/focal/proyectos/LAS-FOCAS/Logs/ 2>/dev/null | cut -f1)"
echo "  Reports: $(du -sh /home/focal/proyectos/LAS-FOCAS/Reports/ 2>/dev/null | cut -f1)"
echo "  Cache:   $(find /home/focal/proyectos/LAS-FOCAS -type d -name '__pycache__' -exec du -b {} \; 2>/dev/null | awk '{sum+=$1} END {printf "%.1f MB", sum/1024/1024}')"

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
