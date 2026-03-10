# Nombre de archivo: SKILL.md
# Ubicación de archivo: .github/skills/temp-cleanup/SKILL.md
# Descripción: Skill para limpieza de archivos temporales, caché Python y archivos de desarrollo

---
name: Limpieza de Temporales
description: Gestión de archivos temporales, caché Python (__pycache__), y archivos de desarrollo
---

# Habilidad: Limpieza de Temporales

Este skill maneja la limpieza de archivos temporales y caché que no afectan el funcionamiento del sistema.

## 📊 Categorías de Archivos Temporales

| Categoría | Ubicación | Riesgo de Eliminar |
|-----------|-----------|-------------------|
| `__pycache__/` | Recursivo en proyecto | 🟢 Seguro (se regenera) |
| Archivos `.pyc` | Recursivo en proyecto | 🟢 Seguro (se regenera) |
| `devs/output/` | Desarrollo local | 🟡 Revisar antes |
| `/tmp/` | Sistema | 🟡 Con precaución |
| `.pytest_cache/` | Raíz del proyecto | 🟢 Seguro |
| `.mypy_cache/` | Raíz del proyecto | 🟢 Seguro |

## 🔍 Comandos de Análisis

### Caché Python (__pycache__)

```bash
# Listar todos los directorios __pycache__
find /home/focal/proyectos/LAS-FOCAS -type d -name "__pycache__" 2>/dev/null

# Tamaño de cada __pycache__
find /home/focal/proyectos/LAS-FOCAS -type d -name "__pycache__" -exec du -sh {} \; 2>/dev/null

# Tamaño total de __pycache__
find /home/focal/proyectos/LAS-FOCAS -type d -name "__pycache__" -exec du -b {} \; 2>/dev/null | \
    awk '{sum+=$1} END {printf "Total __pycache__: %.2f MB\n", sum/1024/1024}'

# Contar archivos .pyc
find /home/focal/proyectos/LAS-FOCAS -name "*.pyc" -type f 2>/dev/null | wc -l

# Contar archivos .pyo
find /home/focal/proyectos/LAS-FOCAS -name "*.pyo" -type f 2>/dev/null | wc -l
```

### Directorios de Desarrollo

```bash
# Archivos en devs/output/
du -sh /home/focal/proyectos/LAS-FOCAS/devs/output/ 2>/dev/null

# Listar contenido de devs/output/
ls -lah /home/focal/proyectos/LAS-FOCAS/devs/output/ 2>/dev/null

# Archivos más antiguos de 7 días en devs/output/
find /home/focal/proyectos/LAS-FOCAS/devs/output/ -type f -mtime +7 2>/dev/null
```

### Caché de Herramientas

```bash
# Caché de pytest
du -sh /home/focal/proyectos/LAS-FOCAS/.pytest_cache/ 2>/dev/null

# Caché de mypy
du -sh /home/focal/proyectos/LAS-FOCAS/.mypy_cache/ 2>/dev/null

# Caché de ruff
du -sh /home/focal/proyectos/LAS-FOCAS/.ruff_cache/ 2>/dev/null

# Resumen de cachés de herramientas
echo "📊 CACHÉS DE HERRAMIENTAS"
for cache in .pytest_cache .mypy_cache .ruff_cache .coverage; do
    SIZE=$(du -sh "/home/focal/proyectos/LAS-FOCAS/$cache" 2>/dev/null | cut -f1)
    [ -n "$SIZE" ] && echo "  $cache: $SIZE"
done
```

### Temporales del Sistema

```bash
# Tamaño de /tmp
du -sh /tmp/ 2>/dev/null

# Archivos en /tmp más grandes de 10MB
find /tmp -type f -size +10M -exec ls -lh {} \; 2>/dev/null

# Archivos de LibreOffice en /tmp
find /tmp -name "lu*" -o -name "*.tmp" 2>/dev/null | head -20

# Archivos temporales del usuario actual
find /tmp -user $(whoami) -type f 2>/dev/null | wc -l
```

## 🧹 Comandos de Limpieza

### Limpiar __pycache__ (Recomendado)

```bash
# Eliminar todos los __pycache__ del proyecto
find /home/focal/proyectos/LAS-FOCAS -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
echo "✅ Directorios __pycache__ eliminados"

# Eliminar archivos .pyc individuales
find /home/focal/proyectos/LAS-FOCAS -name "*.pyc" -type f -delete 2>/dev/null
echo "✅ Archivos .pyc eliminados"

# Eliminar archivos .pyo
find /home/focal/proyectos/LAS-FOCAS -name "*.pyo" -type f -delete 2>/dev/null
echo "✅ Archivos .pyo eliminados"
```

### Limpiar Caché de Herramientas

```bash
# Limpiar caché de pytest
rm -rf /home/focal/proyectos/LAS-FOCAS/.pytest_cache/ 2>/dev/null

# Limpiar caché de mypy
rm -rf /home/focal/proyectos/LAS-FOCAS/.mypy_cache/ 2>/dev/null

# Limpiar caché de ruff
rm -rf /home/focal/proyectos/LAS-FOCAS/.ruff_cache/ 2>/dev/null

# Limpiar archivos de cobertura
rm -f /home/focal/proyectos/LAS-FOCAS/.coverage 2>/dev/null
rm -rf /home/focal/proyectos/LAS-FOCAS/htmlcov/ 2>/dev/null

echo "✅ Cachés de herramientas eliminados"
```

### Limpiar devs/output/ (Con Advertencia)

```bash
# Mostrar contenido antes de eliminar
echo "⚠️  Contenido de devs/output/:"
ls -lah /home/focal/proyectos/LAS-FOCAS/devs/output/ 2>/dev/null

# Eliminar solo archivos más antiguos de 7 días
find /home/focal/proyectos/LAS-FOCAS/devs/output/ -type f -mtime +7 -delete 2>/dev/null
echo "✅ Archivos antiguos (>7 días) eliminados de devs/output/"

# O eliminar todo (con confirmación)
read -p "¿Eliminar TODO el contenido de devs/output/? (s/N): " CONFIRM
if [[ "$CONFIRM" =~ ^[sS]$ ]]; then
    rm -rf /home/focal/proyectos/LAS-FOCAS/devs/output/* 2>/dev/null
    echo "✅ devs/output/ limpiado"
fi
```

### Limpiar Temporales de LibreOffice

```bash
# Archivos temporales de LibreOffice en /tmp
find /tmp -name "lu*" -user $(whoami) -delete 2>/dev/null

# Archivos .tmp del usuario
find /tmp -name "*.tmp" -user $(whoami) -mtime +1 -delete 2>/dev/null

echo "✅ Temporales de LibreOffice limpiados"
```

## 📋 Script de Limpieza Completo

```bash
#!/bin/bash
# Limpieza de temporales para LAS-FOCAS

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          LIMPIEZA DE TEMPORALES - LAS-FOCAS                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"

PROJECT="/home/focal/proyectos/LAS-FOCAS"

# Análisis
echo -e "\n📊 ANÁLISIS DE TEMPORALES"
echo "─────────────────────────────"

# __pycache__
PYCACHE_SIZE=$(find "$PROJECT" -type d -name "__pycache__" -exec du -b {} \; 2>/dev/null | awk '{sum+=$1} END {printf "%.2f", sum/1024/1024}')
PYCACHE_COUNT=$(find "$PROJECT" -type d -name "__pycache__" 2>/dev/null | wc -l)
echo "  __pycache__: ${PYCACHE_SIZE}MB ($PYCACHE_COUNT directorios)"

# Archivos .pyc
PYC_COUNT=$(find "$PROJECT" -name "*.pyc" -type f 2>/dev/null | wc -l)
echo "  Archivos .pyc: $PYC_COUNT"

# Cachés de herramientas
TOOLS_SIZE=0
for cache in .pytest_cache .mypy_cache .ruff_cache; do
    if [ -d "$PROJECT/$cache" ]; then
        SIZE=$(du -sm "$PROJECT/$cache" 2>/dev/null | cut -f1)
        TOOLS_SIZE=$((TOOLS_SIZE + SIZE))
    fi
done
echo "  Cachés de herramientas: ${TOOLS_SIZE}MB"

# devs/output
DEVS_SIZE=$(du -sm "$PROJECT/devs/output" 2>/dev/null | cut -f1)
echo "  devs/output/: ${DEVS_SIZE:-0}MB"

# Total estimado
TOTAL=$(echo "$PYCACHE_SIZE + $TOOLS_SIZE + ${DEVS_SIZE:-0}" | bc)
echo -e "\n💾 Total estimado a liberar: ${TOTAL}MB"

# Opciones
echo -e "\n🧹 OPCIONES DE LIMPIEZA"
echo "─────────────────────────────"
echo "1. Limpiar __pycache__ y .pyc (seguro)"
echo "2. Limpiar cachés de herramientas (seguro)"
echo "3. Limpiar devs/output/ (revisar antes)"
echo "4. Todo lo anterior"
echo "0. Cancelar"
echo ""
read -p "Seleccione opción: " OPCION

case $OPCION in
    1)
        find "$PROJECT" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
        find "$PROJECT" -name "*.pyc" -type f -delete 2>/dev/null
        find "$PROJECT" -name "*.pyo" -type f -delete 2>/dev/null
        echo "✅ __pycache__ y bytecode eliminados"
        ;;
    2)
        rm -rf "$PROJECT"/.pytest_cache/ 2>/dev/null
        rm -rf "$PROJECT"/.mypy_cache/ 2>/dev/null
        rm -rf "$PROJECT"/.ruff_cache/ 2>/dev/null
        rm -f "$PROJECT"/.coverage 2>/dev/null
        echo "✅ Cachés de herramientas eliminados"
        ;;
    3)
        echo "Contenido de devs/output/:"
        ls -lah "$PROJECT/devs/output/" 2>/dev/null
        read -p "¿Confirmar eliminación? (s/N): " CONFIRM
        if [[ "$CONFIRM" =~ ^[sS]$ ]]; then
            rm -rf "$PROJECT/devs/output/"* 2>/dev/null
            echo "✅ devs/output/ limpiado"
        else
            echo "❌ Cancelado"
        fi
        ;;
    4)
        find "$PROJECT" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
        find "$PROJECT" -name "*.pyc" -type f -delete 2>/dev/null
        find "$PROJECT" -name "*.pyo" -type f -delete 2>/dev/null
        rm -rf "$PROJECT"/.pytest_cache/ 2>/dev/null
        rm -rf "$PROJECT"/.mypy_cache/ 2>/dev/null
        rm -rf "$PROJECT"/.ruff_cache/ 2>/dev/null
        rm -f "$PROJECT"/.coverage 2>/dev/null
        echo "✅ Limpieza completa ejecutada (devs/output/ no incluido)"
        ;;
    *)
        echo "❌ Operación cancelada"
        ;;
esac

# Verificación
echo -e "\n📊 VERIFICACIÓN POST-LIMPIEZA"
echo "─────────────────────────────"
NEW_PYCACHE=$(find "$PROJECT" -type d -name "__pycache__" 2>/dev/null | wc -l)
echo "  __pycache__ restantes: $NEW_PYCACHE"
```

## ⚙️ Configuración .gitignore

Asegurar que estos archivos estén en `.gitignore`:

```gitignore
# Bytecode Python
__pycache__/
*.py[cod]
*$py.class
*.pyo

# Cachés de herramientas
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/

# Desarrollo
devs/output/*
!devs/output/.gitkeep
```

## 🔗 Skills Relacionados

- [disk-analysis](../disk-analysis/SKILL.md) - Diagnóstico de uso de disco
- [docker-cleanup](../docker-cleanup/SKILL.md) - Limpieza de recursos Docker
- [logs-cleanup](../logs-cleanup/SKILL.md) - Gestión de archivos de log
