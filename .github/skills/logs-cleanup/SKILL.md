# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/logs-cleanup/SKILL.md
# Descripción: Skill para gestión y limpieza de archivos de log del proyecto y contenedores Docker

---
name: Limpieza de Logs
description: Gestión de archivos de log del proyecto LAS-FOCAS y logs de contenedores Docker
---

# Habilidad: Limpieza de Logs

Este skill maneja la gestión de logs del proyecto, con umbral de advertencia en **500MB**.

## 📊 Umbrales

| Categoría | 🟢 Normal | 🟡 Advertencia | 🔴 Acción Requerida |
|-----------|-----------|----------------|---------------------|
| Logs totales del proyecto | <300MB | 300-500MB | >500MB |
| Log individual | <50MB | 50-100MB | >100MB |
| Logs de contenedor | <100MB | 100-500MB | >500MB |

## 📍 Ubicaciones de Logs

| Ubicación | Descripción |
|-----------|-------------|
| `Logs/` | Logs del proyecto (web.log, etc.) |
| `/var/lib/docker/containers/*/` | Logs de contenedores Docker |
| Volumen `bot_data` | Logs del bot Telegram |

## 🔍 Comandos de Análisis

### Logs del Proyecto

```bash
# Tamaño total de logs
du -sh /home/focal/proyectos/LAS-FOCAS/Logs/

# Listar todos los archivos de log con tamaño
ls -lah /home/focal/proyectos/LAS-FOCAS/Logs/*.log* 2>/dev/null

# Verificar si supera umbral (500MB)
LOGS_SIZE=$(du -sm /home/focal/proyectos/LAS-FOCAS/Logs/ 2>/dev/null | cut -f1)
if [ "${LOGS_SIZE:-0}" -gt 500 ]; then
    echo "🔴 CRÍTICO: Logs en ${LOGS_SIZE}MB (umbral: 500MB)"
elif [ "${LOGS_SIZE:-0}" -gt 300 ]; then
    echo "🟡 ADVERTENCIA: Logs en ${LOGS_SIZE}MB"
else
    echo "🟢 OK: Logs en ${LOGS_SIZE:-0}MB"
fi

# Archivos de log ordenados por tamaño
ls -lahS /home/focal/proyectos/LAS-FOCAS/Logs/*.log* 2>/dev/null

# Logs rotativos (backups .log.1, .log.2, .log.3)
ls -lah /home/focal/proyectos/LAS-FOCAS/Logs/*.log.[0-9]* 2>/dev/null
```

### Logs de Contenedores Docker

```bash
# Tamaño de logs por contenedor
docker ps -q | while read cid; do
    NAME=$(docker inspect --format '{{.Name}}' "$cid" | sed 's/^\///')
    LOG_PATH=$(docker inspect --format '{{.LogPath}}' "$cid")
    if [ -f "$LOG_PATH" ]; then
        SIZE=$(sudo du -sh "$LOG_PATH" 2>/dev/null | cut -f1)
        echo "$NAME: $SIZE"
    fi
done

# Ver últimas líneas de log de un servicio
docker logs --tail 50 lasfocas-web-1

# Tamaño de log de un contenedor específico
docker inspect --format '{{.LogPath}}' lasfocas-web-1 | xargs sudo du -sh 2>/dev/null
```

### Análisis de Contenido

```bash
# Contar líneas de log por archivo
wc -l /home/focal/proyectos/LAS-FOCAS/Logs/*.log 2>/dev/null

# Buscar errores recientes en logs
grep -i "error\|exception\|critical" /home/focal/proyectos/LAS-FOCAS/Logs/*.log 2>/dev/null | tail -20

# Distribución de niveles de log
grep -ohE "level=(INFO|WARNING|ERROR|DEBUG|CRITICAL)" /home/focal/proyectos/LAS-FOCAS/Logs/*.log 2>/dev/null | sort | uniq -c
```

## 🧹 Comandos de Limpieza

### Limpiar Logs Rotativos del Proyecto

```bash
# Eliminar backups de logs (.log.1, .log.2, .log.3)
rm -f /home/focal/proyectos/LAS-FOCAS/Logs/*.log.[0-9]* 2>/dev/null
echo "✅ Logs rotativos eliminados"

# Verificar espacio liberado
du -sh /home/focal/proyectos/LAS-FOCAS/Logs/
```

### Truncar Logs Activos (Mantener Archivo)

```bash
# Truncar un log específico a 0 bytes (mantiene el archivo)
truncate -s 0 /home/focal/proyectos/LAS-FOCAS/Logs/web.log

# Truncar todos los logs activos
for log in /home/focal/proyectos/LAS-FOCAS/Logs/*.log; do
    if [ -f "$log" ]; then
        truncate -s 0 "$log"
        echo "Truncado: $log"
    fi
done
```

### Limpiar Logs de Contenedores Docker

```bash
# Truncar logs de un contenedor específico (requiere sudo)
CONTAINER="lasfocas-web-1"
LOG_PATH=$(docker inspect --format '{{.LogPath}}' "$CONTAINER")
sudo truncate -s 0 "$LOG_PATH"
echo "✅ Log de $CONTAINER truncado"

# Truncar logs de TODOS los contenedores
docker ps -q | while read cid; do
    LOG_PATH=$(docker inspect --format '{{.LogPath}}' "$cid")
    if [ -f "$LOG_PATH" ]; then
        sudo truncate -s 0 "$LOG_PATH"
        NAME=$(docker inspect --format '{{.Name}}' "$cid" | sed 's/^\///')
        echo "✅ Log truncado: $NAME"
    fi
done
```

## 📋 Script de Limpieza de Logs

```bash
#!/bin/bash
# Limpieza de logs para LAS-FOCAS

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          LIMPIEZA DE LOGS - LAS-FOCAS                        ║"
echo "╚══════════════════════════════════════════════════════════════╝"

PROJECT_LOGS="/home/focal/proyectos/LAS-FOCAS/Logs"
UMBRAL_MB=500

# Análisis de logs del proyecto
echo -e "\n📊 LOGS DEL PROYECTO"
echo "─────────────────────────────"
LOGS_SIZE=$(du -sm "$PROJECT_LOGS" 2>/dev/null | cut -f1)
echo "Tamaño total: ${LOGS_SIZE:-0}MB (umbral: ${UMBRAL_MB}MB)"

if [ "${LOGS_SIZE:-0}" -gt "$UMBRAL_MB" ]; then
    echo "🔴 Estado: SUPERA UMBRAL"
else
    echo "🟢 Estado: OK"
fi

echo -e "\nArchivos de log:"
ls -lah "$PROJECT_LOGS"/*.log* 2>/dev/null | awk '{print "  " $9 ": " $5}'

# Contar backups
BACKUPS=$(ls "$PROJECT_LOGS"/*.log.[0-9]* 2>/dev/null | wc -l)
if [ "$BACKUPS" -gt 0 ]; then
    echo -e "\n⚠️  Logs rotativos encontrados: $BACKUPS archivos"
fi

# Análisis de logs Docker
echo -e "\n📊 LOGS DE CONTENEDORES DOCKER"
echo "─────────────────────────────"
docker ps --format "{{.Names}}" | while read name; do
    LOG_PATH=$(docker inspect --format '{{.LogPath}}' "$name" 2>/dev/null)
    if [ -f "$LOG_PATH" ]; then
        SIZE=$(sudo du -sh "$LOG_PATH" 2>/dev/null | cut -f1)
        echo "  $name: $SIZE"
    fi
done

# Opciones de limpieza
echo -e "\n🧹 OPCIONES DE LIMPIEZA"
echo "─────────────────────────────"
echo "1. Eliminar logs rotativos del proyecto (.log.1, .log.2, etc.)"
echo "2. Truncar logs activos del proyecto"
echo "3. Truncar logs de contenedores Docker"
echo "4. Todo lo anterior"
echo "0. Cancelar"
echo ""
read -p "Seleccione opción: " OPCION

case $OPCION in
    1)
        rm -f "$PROJECT_LOGS"/*.log.[0-9]* 2>/dev/null
        echo "✅ Logs rotativos eliminados"
        ;;
    2)
        for log in "$PROJECT_LOGS"/*.log; do
            [ -f "$log" ] && truncate -s 0 "$log"
        done
        echo "✅ Logs del proyecto truncados"
        ;;
    3)
        docker ps -q | while read cid; do
            LOG_PATH=$(docker inspect --format '{{.LogPath}}' "$cid")
            [ -f "$LOG_PATH" ] && sudo truncate -s 0 "$LOG_PATH"
        done
        echo "✅ Logs de contenedores truncados"
        ;;
    4)
        rm -f "$PROJECT_LOGS"/*.log.[0-9]* 2>/dev/null
        for log in "$PROJECT_LOGS"/*.log; do
            [ -f "$log" ] && truncate -s 0 "$log"
        done
        docker ps -q | while read cid; do
            LOG_PATH=$(docker inspect --format '{{.LogPath}}' "$cid")
            [ -f "$LOG_PATH" ] && sudo truncate -s 0 "$LOG_PATH"
        done
        echo "✅ Limpieza completa ejecutada"
        ;;
    *)
        echo "❌ Operación cancelada"
        ;;
esac

# Estado final
echo -e "\n📊 ESTADO FINAL"
echo "─────────────────────────────"
du -sh "$PROJECT_LOGS" 2>/dev/null
```

## ⚙️ Configuración de Rotación

El proyecto ya tiene configurada rotación automática en `core/logging.py`:

```python
# Configuración actual
max_bytes = 5_000_000  # 5MB por archivo
backup_count = 3       # Máximo 3 backups (.log.1, .log.2, .log.3)
```

### Configurar Rotación en Docker (compose.yml)

```yaml
# Agregar a cada servicio en deploy/compose.yml
services:
  web:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

## 🔗 Skills Relacionados

- [disk-analysis](../disk-analysis/SKILL.md) - Diagnóstico de uso de disco
- [docker-cleanup](../docker-cleanup/SKILL.md) - Limpieza de recursos Docker
- [temp-cleanup](../temp-cleanup/SKILL.md) - Limpieza de temporales
