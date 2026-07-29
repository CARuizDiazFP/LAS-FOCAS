# Nombre de archivo: mantenimiento-disco.md
# Ubicación de archivo: .claude/commands/mantenimiento-disco.md
# Descripción: Comando Claude Code para diagnóstico y limpieza segura de espacio en disco

Ejecuta un diagnóstico de espacio en disco y, si corresponde, una limpieza segura. Argumento opcional: $ARGUMENTS (umbrales o alcance, por ejemplo: "disco 85%, logs 500MB").

Si el usuario no define umbrales, usar como referencia: disco 85%, logs 500 MB, volúmenes 2 GB.

## Objetivo

- medir uso real de disco, Docker, logs y temporales
- identificar espacio recuperable sin afectar datos persistentes
- confirmar con el usuario antes de borrar recursos relevantes
- entregar resumen pre y post limpieza con espacio recuperado

## Flujo de trabajo

### 1. Diagnóstico

```bash
df -h /
docker system df
sudo du -h --max-depth=2 /var/lib/docker 2>/dev/null | sort -hr | head -15
du -sh Logs/ 2>/dev/null
find . -type d -name "__pycache__" -exec du -b {} \; 2>/dev/null | awk '{sum+=$1} END {printf "%.2f MB\n", sum/1024/1024}'
```

### 2. Reporte pre-limpieza

Generar tabla compacta con tamaño actual, recuperable y estado por categoría:

| Categoría | Tamaño Actual | Recuperable | Estado |
|-----------|---------------|-------------|--------|
| Imágenes Docker | X GB | Y GB | 🔴/🟡/🟢 |
| Build Cache | X GB | Y GB | 🔴/🟡/🟢 |
| Contenedores detenidos | X MB | Y MB | 🔴/🟡/🟢 |
| Logs | X MB | - | 🔴/🟡/🟢 |
| __pycache__ | X MB | X MB | 🟢 |
| **Volúmenes** | X GB | **NO TOCAR** | ⚠️ Info |

### 3. Confirmación interactiva

Pedir confirmación explícita por cada categoría borrable que requiera acción. Los volúmenes solo se informan, nunca se tocan.

### 4. Ejecución (solo lo confirmado)

```bash
# Docker
docker image prune -a -f
docker container prune -f
docker builder prune -f
docker network prune -f

# Logs rotativos (nunca truncar activos en uso)
rm -f Logs/*.log.[0-9]* 2>/dev/null

# Cache Python
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -type f -delete 2>/dev/null
rm -rf .pytest_cache/ .mypy_cache/ .ruff_cache/ 2>/dev/null
```

### 5. Reporte post-limpieza

```bash
df -h /
docker system df
```

Resumir espacio liberado, riesgo residual y acciones no ejecutadas.

## Reglas obligatorias

1. Nunca ejecutar `docker volume prune`.
2. Nunca ejecutar `docker system prune --volumes`.
3. No eliminar volúmenes, bases de datos, uploads ni artefactos persistentes.
4. Confirmar antes de limpiar imágenes, cache, logs o temporales.
5. Si una acción puede afectar al entorno activo, advertirlo antes de ejecutarla.
6. Si no hay espacio recuperable significativo, decirlo y no forzar limpieza.

## Skills de referencia

Ver detalle en: `disk-analysis`, `docker-cleanup`, `logs-cleanup`, `temp-cleanup` en `.github/skills/`.
