# Nombre de archivo: skill-docker-rebuild.md
# Ubicación de archivo: .gemini/rules/skill-docker-rebuild.md
# Descripción: Regla Gemini portable migrada desde .github/skills/docker-rebuild/SKILL.md
---
name: "skill-docker-rebuild"
description: "Usar cuando haya que reconstruir servicios Docker, refrescar imágenes o verificar un rebuild selectivo de LAS-FOCAS"
source: ".github/skills/docker-rebuild/SKILL.md"
triggers:
  - "docker-rebuild"
  - "habilidad"
  - "docker"
  - "rebuild"
  - "reconstruir"
  - "servicios"
  - "refrescar"
  - "im-genes"
  - "verificar"
  - "selectivo"
  - "las-focas"
globs:
  - "deploy/**"
  - "**/Dockerfile"
  - "scripts/**"
commands:
  - |
    # Desde la raíz del proyecto:
    docker compose -f deploy/compose.yml build <servicio>

    # Servicios disponibles:
    # - api
    # - web
    # - bot
    # - nlp_intent
    # - office
    # - postgres
    # - repetitividad_worker (profile: reports-worker)
    # - pgadmin (profile: pgadmin)
  - |
    docker compose -f deploy/compose.yml build --no-cache <servicio>
  - |
    docker compose -f deploy/compose.yml build <servicio>
    docker compose -f deploy/compose.yml up -d <servicio>
  - |
    docker compose -f deploy/compose.yml build
    docker compose -f deploy/compose.yml up -d
  - |
    docker compose -f deploy/compose.yml ps
  - |
    # Todos los servicios
    docker compose -f deploy/compose.yml logs -f

    # Servicio específico
    docker compose -f deploy/compose.yml logs -f <servicio>

    # Últimas N líneas
    docker compose -f deploy/compose.yml logs --tail=100 <servicio>
  - |
    # Un servicio
    docker compose -f deploy/compose.yml restart <servicio>

    # Todos
    docker compose -f deploy/compose.yml restart
  - |
    # Detener sin eliminar
    docker compose -f deploy/compose.yml stop

    # Eliminar contenedores
    docker compose -f deploy/compose.yml down

    # Eliminar incluyendo volúmenes (CUIDADO: borra datos)
    docker compose -f deploy/compose.yml down -v
  - |
    docker compose -f deploy/compose.yml --profile reports-worker up -d
  - |
    docker compose -f deploy/compose.yml --profile pgadmin up -d
  - |
    docker compose -f deploy/compose.yml build --progress=plain <servicio>
  - |
    docker compose -f deploy/compose.yml exec <servicio> bash
    # o sh si no tiene bash
    docker compose -f deploy/compose.yml exec <servicio> sh
  - |
    docker stats
  - |
    docker image prune -f
  - |
    ./Start
---

# Regla Skill: docker-rebuild

> Fuente original: `.github/skills/docker-rebuild/SKILL.md`. Usar esta regla cuando Gemini/Codex IDE detecte los triggers o globs declarados.

# Habilidad: Docker Rebuild

Comandos y procedimientos para reconstruir contenedores Docker en LAS-FOCAS.

## Ubicación del Compose

> **IMPORTANTE**: El archivo de Compose está en `deploy/compose.yml`, NO en la raíz.

## Comandos Básicos

### Reconstruir un servicio específico

```bash
# Desde la raíz del proyecto:
docker compose -f deploy/compose.yml build <servicio>

# Servicios disponibles:
# - api
# - web
# - bot
# - nlp_intent
# - office
# - postgres
# - repetitividad_worker (profile: reports-worker)
# - pgadmin (profile: pgadmin)
```

### Reconstruir sin cache

```bash
docker compose -f deploy/compose.yml build --no-cache <servicio>
```

### Reconstruir y reiniciar

```bash
docker compose -f deploy/compose.yml build <servicio>
docker compose -f deploy/compose.yml up -d <servicio>
```

### Reconstruir todos los servicios

```bash
docker compose -f deploy/compose.yml build
docker compose -f deploy/compose.yml up -d
```

## Gestión de Servicios

### Ver estado

```bash
docker compose -f deploy/compose.yml ps
```

### Ver logs

```bash
# Todos los servicios
docker compose -f deploy/compose.yml logs -f

# Servicio específico
docker compose -f deploy/compose.yml logs -f <servicio>

# Últimas N líneas
docker compose -f deploy/compose.yml logs --tail=100 <servicio>
```

### Reiniciar servicios

```bash
# Un servicio
docker compose -f deploy/compose.yml restart <servicio>

# Todos
docker compose -f deploy/compose.yml restart
```

### Detener servicios

```bash
# Detener sin eliminar
docker compose -f deploy/compose.yml stop

# Eliminar contenedores
docker compose -f deploy/compose.yml down

# Eliminar incluyendo volúmenes (CUIDADO: borra datos)
docker compose -f deploy/compose.yml down -v
```

## Perfiles

### Activar worker de reportes

```bash
docker compose -f deploy/compose.yml --profile reports-worker up -d
```

### Activar pgAdmin

```bash
docker compose -f deploy/compose.yml --profile pgadmin up -d
```

## Troubleshooting

### Ver logs de build

```bash
docker compose -f deploy/compose.yml build --progress=plain <servicio>
```

### Entrar a un contenedor

```bash
docker compose -f deploy/compose.yml exec <servicio> bash
# o sh si no tiene bash
docker compose -f deploy/compose.yml exec <servicio> sh
```

### Ver uso de recursos

```bash
docker stats
```

### Limpiar imágenes no usadas

```bash
docker image prune -f
```

## Script de Inicio Rápido

El proyecto incluye `./Start` para arranque rápido:

```bash
./Start
```

## Consideraciones

1. **PostgreSQL**: no reconstruir postgres si hay datos importantes (usa volumen `postgres_data`)
2. **Orden de inicio**: respetar dependencias definidas en compose
3. **Red**: todos los servicios comparten `lasfocas_net`
4. **Versiones**: nunca cambiar a `latest`, mantener versiones fijas
