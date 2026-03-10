# Nombre de archivo: mantenimiento-disco.prompt.md
# Ubicación de archivo: .github/prompts/mantenimiento-disco.prompt.md
# Descripción: Prompt reutilizable para diagnóstico y limpieza de espacio en disco del entorno LAS-FOCAS

---
mode: agent
description: Diagnóstico y limpieza de espacio en disco para el entorno Docker de LAS-FOCAS
variables:
  - name: umbral_disco
    default: "85"
    description: Porcentaje de uso de disco para alerta crítica
  - name: umbral_logs_mb
    default: "500"
    description: Tamaño máximo de logs en MB antes de advertir
  - name: umbral_volumen_gb
    default: "2"
    description: Tamaño de volumen en GB para mostrar advertencia
---

# Mantenimiento de Disco - LAS-FOCAS

Ejecutar diagnóstico y limpieza de espacio en disco siguiendo el flujo estructurado de 5 fases.

## 📋 Configuración

- **Umbral crítico de disco**: {{umbral_disco}}%
- **Umbral de logs**: {{umbral_logs_mb}}MB
- **Advertencia de volúmenes**: {{umbral_volumen_gb}}GB

## 🔄 Flujo de Ejecución

### FASE 1: DIAGNÓSTICO

Ejecutar análisis completo usando el skill `disk-analysis`:

```bash
# 1. Estado general del disco
df -h /

# 2. Resumen Docker
docker system df

# 3. Top directorios Docker (si tienes acceso sudo)
sudo du -h --max-depth=2 /var/lib/docker 2>/dev/null | sort -hr | head -15

# 4. Logs del proyecto
du -sh Logs/ 2>/dev/null

# 5. Caché Python
find . -type d -name "__pycache__" -exec du -b {} \; 2>/dev/null | awk '{sum+=$1} END {printf "%.2f MB\n", sum/1024/1024}'
```

Generar reporte con semáforos:
- 🟢 Normal (sin acción)
- 🟡 Advertencia (monitorear)
- 🔴 Crítico (acción requerida)

### FASE 2: REPORTE PRE-LIMPIEZA

Generar tabla resumen con espacio recuperable por categoría:

| Categoría | Tamaño Actual | Recuperable | Estado |
|-----------|---------------|-------------|--------|
| Imágenes Docker | X GB | Y GB | 🔴/🟡/🟢 |
| Build Cache | X GB | Y GB | 🔴/🟡/🟢 |
| Contenedores | X MB | Y MB | 🔴/🟡/🟢 |
| Logs | X MB | - | 🔴/🟡/🟢 |
| __pycache__ | X MB | X MB | 🔴/🟡/🟢 |
| **Volúmenes** | X MB | **NO TOCAR** | ⚠️ Info |

### FASE 3: CONFIRMACIÓN INTERACTIVA

Preguntar al usuario por cada categoría que requiera acción:

1. **Docker (imágenes + cache)**: "Se pueden liberar X GB. ¿Proceder?"
2. **Logs** (solo si >{{umbral_logs_mb}}MB): "Logs en X MB. ¿Limpiar backups?"
3. **Temporales**: "__pycache__ ocupa X MB. ¿Limpiar?"
4. **Volúmenes**: Solo informar si alguno supera {{umbral_volumen_gb}}GB (NUNCA ofrecer eliminar)

### FASE 4: EJECUCIÓN

Según las confirmaciones, ejecutar limpieza usando los skills correspondientes:

#### Si se confirmó Docker:
```bash
# Limpiar imágenes no usadas
docker image prune -a -f

# Limpiar contenedores detenidos
docker container prune -f

# Limpiar build cache
docker builder prune -f

# Limpiar redes no usadas
docker network prune -f
```

#### Si se confirmó Logs:
```bash
# Eliminar logs rotativos
rm -f Logs/*.log.[0-9]* 2>/dev/null

# Truncar logs activos si es necesario
# for log in Logs/*.log; do truncate -s 0 "$log"; done
```

#### Si se confirmó Temporales:
```bash
# Limpiar __pycache__
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# Limpiar bytecode
find . -name "*.pyc" -type f -delete 2>/dev/null

# Limpiar cachés de herramientas
rm -rf .pytest_cache/ .mypy_cache/ .ruff_cache/ 2>/dev/null
```

### FASE 5: REPORTE POST-LIMPIEZA

Generar reporte final:

```bash
# Nuevo estado del disco
df -h /

# Nuevo estado de Docker
docker system df

# Resumen de limpieza
echo "═══════════════════════════════════════"
echo "RESUMEN DE LIMPIEZA"
echo "═══════════════════════════════════════"
echo "Espacio liberado: X GB"
echo "Nuevo uso de disco: Y%"
echo "═══════════════════════════════════════"
```

## ⚠️ Reglas Inquebrantables

1. **NUNCA ejecutar `docker volume prune`** - Los volúmenes contienen datos de PostgreSQL, uploads, etc.
2. **NUNCA ejecutar `docker system prune --volumes`** - Eliminaría datos persistentes
3. **Volúmenes solo informativos** - Mostrar peso y advertir si >{{umbral_volumen_gb}}GB, pero NUNCA ofrecer eliminar
4. **Confirmar antes de eliminar** - Especialmente en categorías marcadas con 🟡

## 📚 Skills Utilizados

Este prompt utiliza los siguientes skills de mantenimiento:

- [disk-analysis](../skills/disk-analysis/SKILL.md) - Comandos de diagnóstico
- [docker-cleanup](../skills/docker-cleanup/SKILL.md) - Limpieza Docker segura
- [logs-cleanup](../skills/logs-cleanup/SKILL.md) - Gestión de logs
- [temp-cleanup](../skills/temp-cleanup/SKILL.md) - Limpieza de temporales

## 🔄 Frecuencia Recomendada

| Situación | Acción |
|-----------|--------|
| Disco <70% | Sin acción, monitoreo mensual |
| Disco 70-85% | Ejecutar limpieza preventiva semanal |
| Disco >85% | Ejecutar limpieza inmediata |
| Post-deploy | Limpiar build cache antiguo |
| Post-desarrollo | Limpiar __pycache__ y devs/output/ |

## 📊 Ejemplo de Ejecución

```
╔══════════════════════════════════════════════════════════════╗
║          DIAGNÓSTICO DE DISCO - LAS-FOCAS                    ║
╚══════════════════════════════════════════════════════════════╝

📊 ESTADO GENERAL
─────────────────────────────
Uso de disco: 88% 🔴 CRÍTICO (umbral: 85%)
Disponible: 7.4 GB

🐳 DOCKER
─────────────────────────────
Imágenes:     31.74 GB (11.49 GB recuperables) 🔴
Build Cache:  25.96 GB (recuperable)           🔴
Contenedores: 47.39 MB (31.94 MB recuperables) 🟢
Volúmenes:    253.4 MB                         🟢 (no tocar)

📁 PROYECTO
─────────────────────────────
Logs:         36 KB    🟢
Reports:      6.8 MB   🟢
__pycache__:  102 MB   🟡

💾 ESPACIO TOTAL RECUPERABLE: ~37 GB

═══════════════════════════════════════════════════════════════

¿Proceder con la limpieza de Docker? (11.49 GB imágenes + 25.96 GB cache)
> Opciones: [Sí] [No] [Solo imágenes] [Solo cache]
```
