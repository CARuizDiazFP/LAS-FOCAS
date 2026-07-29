# Nombre de archivo: operacion.md
# Ubicación de archivo: .github/skills/temp-cleanup/references/operacion.md
# Descripción: Comandos y procedimientos detallados para análisis y limpieza de temporales en LAS-FOCAS

# Operación de Limpieza de Temporales

## Categorías

| Categoría | Ubicación | Riesgo de eliminar |
|-----------|-----------|-------------------|
| `__pycache__/` | Recursivo en proyecto | Bajo |
| `.pyc` y `.pyo` | Recursivo en proyecto | Bajo |
| `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/` | Raíz del proyecto | Bajo |
| `devs/output/` | Desarrollo local | Medio |
| `/tmp/` del usuario | Sistema | Medio |

## Análisis

```bash
find /home/focal/proyectos/LAS-FOCAS -type d -name "__pycache__" 2>/dev/null
find /home/focal/proyectos/LAS-FOCAS -type d -name "__pycache__" -exec du -sh {} \; 2>/dev/null
find /home/focal/proyectos/LAS-FOCAS -type d -name "__pycache__" -exec du -b {} \; 2>/dev/null | awk '{sum+=$1} END {printf "Total __pycache__: %.2f MB\n", sum/1024/1024}'
find /home/focal/proyectos/LAS-FOCAS -name "*.pyc" -type f 2>/dev/null | wc -l
du -sh /home/focal/proyectos/LAS-FOCAS/.pytest_cache/ 2>/dev/null
du -sh /home/focal/proyectos/LAS-FOCAS/.mypy_cache/ 2>/dev/null
du -sh /home/focal/proyectos/LAS-FOCAS/.ruff_cache/ 2>/dev/null
du -sh /home/focal/proyectos/LAS-FOCAS/devs/output/ 2>/dev/null
find /tmp -user $(whoami) -type f 2>/dev/null | wc -l
```

## Limpieza segura

```bash
find /home/focal/proyectos/LAS-FOCAS -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find /home/focal/proyectos/LAS-FOCAS -name "*.pyc" -type f -delete 2>/dev/null
find /home/focal/proyectos/LAS-FOCAS -name "*.pyo" -type f -delete 2>/dev/null
rm -rf /home/focal/proyectos/LAS-FOCAS/.pytest_cache/ 2>/dev/null
rm -rf /home/focal/proyectos/LAS-FOCAS/.mypy_cache/ 2>/dev/null
rm -rf /home/focal/proyectos/LAS-FOCAS/.ruff_cache/ 2>/dev/null
rm -f /home/focal/proyectos/LAS-FOCAS/.coverage 2>/dev/null
rm -rf /home/focal/proyectos/LAS-FOCAS/htmlcov/ 2>/dev/null
```

## Limpieza con confirmación

```bash
ls -lah /home/focal/proyectos/LAS-FOCAS/devs/output/ 2>/dev/null
find /home/focal/proyectos/LAS-FOCAS/devs/output/ -type f -mtime +7 -delete 2>/dev/null
find /tmp -name "lu*" -user $(whoami) -delete 2>/dev/null
find /tmp -name "*.tmp" -user $(whoami) -mtime +1 -delete 2>/dev/null
```

## Guardrails

- No borrar directorios persistentes fuera de cachés y temporales claros.
- `devs/output/` requiere revisión o confirmación antes de vaciarse.
- Evitar limpiar `/tmp` globalmente; limitar a archivos del usuario actual.