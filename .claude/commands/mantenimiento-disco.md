---
description: "Diagnosticar uso de disco, Docker y logs, y ejecutar una limpieza segura con confirmación"
argument-hint: "umbrales, p. ej. 'disco 85%, logs 500MB'"
---

# Nombre de archivo: mantenimiento-disco.md
# Ubicación de archivo: .claude/commands/mantenimiento-disco.md
# Descripción: Comando Claude Code para diagnóstico y limpieza segura de espacio en disco

Ejecuta un diagnóstico de espacio en disco y, si corresponde, una limpieza segura. Argumento opcional: $ARGUMENTS (umbrales o alcance, por ejemplo: "disco 85%, logs 500MB").

Si el usuario no define umbrales, usar como referencia: disco 85%, logs 500 MB, volúmenes 2 GB.

Seleccionar perfil operativo (`rapido`, `estandar`, `profundo`) según `docs/maintenance_profiles.md`.

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
docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}' | sort
docker ps -a --format '{{.Image}}' | sort -u   # imágenes en uso
du -sh Logs/ Logs/dev/ 2>/dev/null
find . -path ./.venv -prune -o -type d -name "__pycache__" -print0 2>/dev/null | du -cb --files0-from=- 2>/dev/null | tail -1
# Fuera del repo (misma partición): home, VS Code server, dumps de prod, /tmp — ver disk-analysis §7
du -sh ~/* ~/.[a-z]* 2>/dev/null | sort -hr | head -20
```

`sudo du /var/lib/docker` pide contraseña en este host: no usarlo en sesiones no interactivas.

### 2. Reporte pre-limpieza

Generar tabla compacta con tamaño actual, recuperable y estado por categoría:

| Categoría | Tamaño Actual | Recuperable | Estado |
|-----------|---------------|-------------|--------|
| Imágenes Docker | X GB | Y GB | 🔴/🟡/🟢 |
| Build Cache | X GB | Y GB | 🔴/🟡/🟢 |
| Contenedores detenidos | X MB | Y MB | 🔴/🟡/🟢 |
| Logs | X MB | - | 🔴/🟡/🟢 |
| __pycache__ | X MB | X MB | 🟢 |
| Fuera del repo (`~/.vscode-server`, dumps, `~/.cache`) | X GB | Y GB | 🔴/🟡/🟢 |
| **Volúmenes** | X GB | **NO TOCAR** | ⚠️ Info |
| **Imágenes protegidas** (rollback de prod, `focas-base`) | X GB | **NO TOCAR** | ⚠️ Info |

### 3. Confirmación interactiva

Pedir confirmación explícita por cada categoría borrable que requiera acción. Los volúmenes solo se informan, nunca se tocan.

### 4. Ejecución (solo lo confirmado)

```bash
# Docker
docker image prune -f          # sólo dangling; NUNCA -a (ver regla 7)
docker image rm <repo>:<tag>   # sólo rollbacks superados aprobados, por tag exacto
docker container prune -f
docker builder prune -f
docker network prune -f

# Logs rotativos (nunca truncar activos en uso)
rm -f Logs/*.log.[0-9]* 2>/dev/null

# Cache Python
find . -path ./.venv -prune -o -type d -name "__pycache__" -print0 | xargs -0 rm -rf
find . -path ./.venv -prune -o -name "*.pyc" -type f -print0 | xargs -0 rm -f
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
7. Nunca `docker image prune -a` ni `docker system prune -a`: este host corre prod y dev en el mismo
   daemon, y esos comandos borran los rollback de prod (`:rollback`, `:pre-deploy-*`,
   `:pre-hotfix-*`) y `focas-base:latest` (base de builds). Imágenes: sólo por tag exacto (`docker-cleanup`).
8. Fuera del repo: nunca borrar el servidor de VS Code en ejecución ni a mano una extensión de
   `.obsolete` (puede ser la que corre esta sesión); los dumps de prod del home se confirman con el
   usuario conservando los del último deploy (`disk-analysis` §7).

## Skills de referencia

Ver detalle en: `disk-analysis`, `docker-cleanup`, `logs-cleanup`, `temp-cleanup` en `.github/skills/`.

Perfiles de ejecución: `docs/maintenance_profiles.md`.
