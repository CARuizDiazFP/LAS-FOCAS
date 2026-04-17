# Nombre de archivo: mantenimiento-disco.prompt.md
# Ubicación de archivo: .github/prompts/mantenimiento-disco.prompt.md
# Descripción: Prompt reutilizable para diagnóstico y limpieza de espacio en disco del entorno LAS-FOCAS

---
name: Mantenimiento de Disco
description: "Diagnostica uso de disco y propone limpieza segura en LAS-FOCAS sin tocar volúmenes persistentes"
argument-hint: "Contexto opcional, por ejemplo: umbral disco 85, logs 500 MB, volumen 2 GB"
agent: "agent"
---

# Mantenimiento de Disco - LAS-FOCAS

Ejecuta un diagnóstico de espacio en disco y, si corresponde, una limpieza segura del entorno de trabajo. Si el usuario no define umbrales, usar como referencia: disco 85%, logs 500 MB y volúmenes 2 GB.

## Objetivo

- medir uso real de disco, Docker, logs y temporales
- identificar espacio recuperable sin afectar datos persistentes
- confirmar con el usuario antes de borrar recursos relevantes
- entregar un resumen pre y post limpieza con espacio recuperado

## Entradas esperadas

- umbral de uso de disco crítico
- umbral de logs en MB
- umbral informativo de volúmenes en GB
- alcance de limpieza si el usuario quiere limitarla

## Flujo de trabajo

### 1. Diagnóstico

Recolectar estado actual con comandos de diagnóstico y resumirlo por categorías.

```bash
df -h /
docker system df
sudo du -h --max-depth=2 /var/lib/docker 2>/dev/null | sort -hr | head -15
du -sh Logs/ 2>/dev/null
find . -type d -name "__pycache__" -exec du -b {} \; 2>/dev/null | awk '{sum+=$1} END {printf "%.2f MB\n", sum/1024/1024}'
```

Opcionalmente complementar con los skills del repo para análisis de disco, Docker, logs y temporales.

### 2. Reporte pre-limpieza

Generar una tabla o lista compacta con tamaño actual, recuperable y nivel de riesgo por categoría.

| Categoría | Tamaño Actual | Recuperable | Estado |
|-----------|---------------|-------------|--------|
| Imágenes Docker | X GB | Y GB | 🔴/🟡/🟢 |
| Build Cache | X GB | Y GB | 🔴/🟡/🟢 |
| Contenedores | X MB | Y MB | 🔴/🟡/🟢 |
| Logs | X MB | - | 🔴/🟡/🟢 |
| __pycache__ | X MB | X MB | 🔴/🟡/🟢 |
| **Volúmenes** | X MB | **NO TOCAR** | ⚠️ Info |

### 3. Confirmación interactiva

Pedir confirmación explícita por cada categoría borrable que requiera acción. Los volúmenes solo se informan.

### 4. Ejecución

Ejecutar solo lo confirmado por el usuario.

```bash
docker image prune -a -f
docker container prune -f
docker builder prune -f
docker network prune -f
```

```bash
rm -f Logs/*.log.[0-9]* 2>/dev/null
```

```bash
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -type f -delete 2>/dev/null
rm -rf .pytest_cache/ .mypy_cache/ .ruff_cache/ 2>/dev/null
```

### 5. Reporte post-limpieza

Volver a medir estado final y resumir espacio liberado, riesgo residual y acciones no ejecutadas.

```bash
df -h /
docker system df
```

## Reglas obligatorias

1. Nunca ejecutar `docker volume prune`.
2. Nunca ejecutar `docker system prune --volumes`.
3. No eliminar volúmenes, bases de datos, uploads ni artefactos persistentes.
4. Confirmar antes de limpiar imágenes, cache, logs o temporales.
5. Si una acción puede afectar al entorno activo, advertirlo antes de ejecutarla.
6. Si no hay riesgo real o no hay espacio recuperable significativo, decirlo y no forzar limpieza.

## Referencias útiles

- `disk-analysis`
- `docker-cleanup`
- `logs-cleanup`
- `temp-cleanup`

## Salida esperada

1. Mostrar diagnóstico inicial.
2. Resumir espacio recuperable por categoría.
3. Pedir confirmación cuando aplique.
4. Ejecutar solo acciones aprobadas.
5. Mostrar reporte final con espacio liberado y riesgos remanentes.
