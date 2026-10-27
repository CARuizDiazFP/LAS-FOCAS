# Nombre de archivo: prompt-mantenimiento-disco-prompt.md
# Ubicación de archivo: .gemini/rules/prompt-mantenimiento-disco-prompt.md
# Descripción: Regla Gemini portable migrada desde .github/prompts/mantenimiento-disco.prompt.md
---
name: "prompt-mantenimiento-disco-prompt"
description: "Prompt migrado desde /home/support-focal-01/LAS-FOCAS/.github/prompts/mantenimiento-disco.prompt.md"
source: ".github/prompts/mantenimiento-disco.prompt.md"
triggers:
  - "mantenimiento-de-disco-las-focas"
  - "mantenimiento-disco-prompt"
  - "mantenimiento-disco"
  - "migrado"
  - "home"
  - "support-focal-01"
  - "las-focas"
  - "github"
  - "prompts"
globs:
  - "deploy/**"
  - "**/Dockerfile"
  - "scripts/**"
  - "tests/**"
  - "pytest.ini"
  - "modules/**"
  - "core/sla/**"
  - "Templates/**"
  - "docs/informes/**"
  - "Logs/**"
  - "logs/**"
  - ".cache/**"
  - "**/__pycache__/**"
  - ".pytest_cache/**"
  - ".mypy_cache/**"
  - ".ruff_cache/**"
  - "tmp/**"
  - "docs/**"
commands:
  - |
    df -h /
    docker system df
    docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}' | sort
    docker ps -a --format '{{.Image}}' | sort -u   # imágenes en uso
    du -sh Logs/ Logs/dev/ 2>/dev/null
    find . -path ./.venv -prune -o -type d -name "__pycache__" -print0 2>/dev/null | du -cb --files0-from=- 2>/dev/null | tail -1
    # Fuera del repo (misma partición): home, VS Code server, dumps de prod, /tmp — ver disk-analysis §7
    du -sh ~/* ~/.[a-z]* 2>/dev/null | sort -hr | head -20
  - |
    docker image prune -f          # sólo dangling; NUNCA -a (ver regla 7)
    docker image rm <repo>:<tag>   # sólo el juego de rollback superado y aprobado, por tag exacto (regla 9)
    docker container prune -f
    docker builder prune -f
    docker network prune -f
  - |
    rm -f Logs/*.log.[0-9]* 2>/dev/null
  - |
    find . -path ./.venv -prune -o -type d -name "__pycache__" -print0 | xargs -0 rm -rf
    find . -path ./.venv -prune -o -name "*.pyc" -type f -print0 | xargs -0 rm -f
    rm -rf .pytest_cache/ .mypy_cache/ .ruff_cache/ 2>/dev/null
  - |
    df -h /
    docker system df
---

# Regla Prompt: mantenimiento-disco.prompt

> Fuente original: `.github/prompts/mantenimiento-disco.prompt.md`. Usar como contrato reutilizable cuando el pedido coincida con esta automatización.

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

Antes de ejecutar, elegir perfil `rapido`, `estandar` o `profundo` según `docs/maintenance_profiles.md`.

### 1. Diagnóstico

Recolectar estado actual con comandos de diagnóstico y resumirlo por categorías.

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
| Fuera del repo (`~/.vscode-server`, dumps, `~/.cache`) | X GB | Y GB | 🔴/🟡/🟢 |
| **Volúmenes** | X MB | **NO TOCAR** | ⚠️ Info |
| **Imágenes protegidas** (último juego de rollback, `focas-base` + base anterior) | X GB | **NO TOCAR** | ⚠️ Info |
| Juego de rollback superado (regla 9) | X GB | Y GB, con OK | 🔴/🟡/🟢 |

### 3. Confirmación interactiva

Pedir confirmación explícita por cada categoría borrable que requiera acción. Los volúmenes solo se informan.

### 4. Ejecución

Ejecutar solo lo confirmado por el usuario.

```bash
docker image prune -f          # sólo dangling; NUNCA -a (ver regla 7)
docker image rm <repo>:<tag>   # sólo el juego de rollback superado y aprobado, por tag exacto (regla 9)
docker container prune -f
docker builder prune -f
docker network prune -f
```

```bash
rm -f Logs/*.log.[0-9]* 2>/dev/null
```

```bash
find . -path ./.venv -prune -o -type d -name "__pycache__" -print0 | xargs -0 rm -rf
find . -path ./.venv -prune -o -name "*.pyc" -type f -print0 | xargs -0 rm -f
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
7. Nunca `docker image prune -a` ni `docker system prune -a`: este host corre prod y dev en el mismo
   daemon, y esos comandos borran los rollback de prod (`:pre-deploy-*`, `:pre-hotfix-*`) y `focas-base:latest` (base de builds). Imágenes: sólo por tag exacto (`docker-cleanup`).
8. Fuera del repo: nunca borrar el servidor de VS Code en ejecución ni a mano una extensión de
   `.obsolete` (puede ser la que corre esta sesión); los dumps de prod del home se confirman con el
   usuario conservando los del último deploy (`disk-analysis` §7).
9. Rollback de prod: se conserva sólo el último juego (`:pre-deploy-*` o el `:pre-hotfix-*` posterior)
   más `focas-base:latest` y la base anterior; el resto se borra por tag exacto, tras verificar el
   deploy y con confirmación. Regla única: `docker-cleanup` → "Rollback de prod".

## Referencias útiles

- `disk-analysis`
- `docker-cleanup`
- `logs-cleanup`
- `temp-cleanup`
- `docs/maintenance_profiles.md`

## Salida esperada

1. Mostrar diagnóstico inicial.
2. Resumir espacio recuperable por categoría.
3. Pedir confirmación cuando aplique.
4. Ejecutar solo acciones aprobadas.
5. Mostrar reporte final con espacio liberado y riesgos remanentes.
