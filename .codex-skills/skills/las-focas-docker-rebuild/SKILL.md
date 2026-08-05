---
name: "las-focas-docker-rebuild"
description: "Usar cuando haya que reconstruir servicios Docker, refrescar imágenes o verificar un rebuild selectivo de LAS-FOCAS"
metadata:
  short-description: "Usar cuando haya que reconstruir servicios Docker, refrescar imágenes o verificar un rebuild selectivo de LAS-FOCAS"
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
      docker compose -f deploy/compose.yml --env-file .env build <servicio>

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
      docker compose -f deploy/compose.yml --env-file .env build --no-cache <servicio>
    - |
      docker compose -f deploy/compose.yml --env-file .env build <servicio>
      docker compose -f deploy/compose.yml --env-file .env up -d <servicio>
    - |
      docker compose -f deploy/compose.yml --env-file .env build
      docker compose -f deploy/compose.yml --env-file .env up -d
    - |
      docker compose -f deploy/compose.yml --env-file .env ps
    - |
      # Todos los servicios
      docker compose -f deploy/compose.yml --env-file .env logs -f

      # Servicio específico
      docker compose -f deploy/compose.yml --env-file .env logs -f <servicio>

      # Últimas N líneas
      docker compose -f deploy/compose.yml --env-file .env logs --tail=100 <servicio>
    - |
      # Un servicio
      docker compose -f deploy/compose.yml --env-file .env restart <servicio>

      # Todos
      docker compose -f deploy/compose.yml --env-file .env restart
    - |
      # Detener sin eliminar
      docker compose -f deploy/compose.yml --env-file .env stop

      # Eliminar contenedores (no toca volúmenes)
      docker compose -f deploy/compose.yml --env-file .env down --remove-orphans

      # Eliminar incluyendo volúmenes (CUIDADO: borra datos)
      docker compose -f deploy/compose.yml --env-file .env down -v
    - |
      docker compose -f deploy/compose.yml --env-file .env --profile reports-worker up -d
    - |
      docker compose -f deploy/compose.yml --env-file .env --profile pgadmin up -d
    - |
      docker compose -f deploy/compose.yml --env-file .env build --progress=plain <servicio>
    - |
      docker compose -f deploy/compose.yml --env-file .env exec <servicio> bash
      # o sh si no tiene bash
      docker compose -f deploy/compose.yml --env-file .env exec <servicio> sh
    - |
      docker stats
    - |
      docker image prune -f
    - |
      docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev build <servicio>
      docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev up -d <servicio>
      docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev down --remove-orphans
      docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev ps
    - |
      ./Start
      ./scripts/start_dev.sh
---

# Nombre de archivo: SKILL.md
# Ubicación de archivo: .codex-skills/skills/las-focas-docker-rebuild/SKILL.md
# Descripción: Skill portable Codex migrada desde .github/skills/docker-rebuild/SKILL.md

# Skill portable: docker-rebuild

> Fuente original: `.github/skills/docker-rebuild/SKILL.md`. Copia portable generada porque `.codex/` está montado como solo lectura en esta sesión.

# Habilidad: Docker Rebuild

Comandos y procedimientos para reconstruir contenedores Docker en LAS-FOCAS.

## Ubicación del Compose

> **IMPORTANTE**: El archivo de Compose está en `deploy/compose.yml` (prod) o `deploy/docker-compose.dev.yml` (dev), NO en la raíz.

> **CRÍTICO — `--env-file` obligatorio**: todo comando `docker compose` suelto (fuera de `./Start` / `./scripts/start_dev.sh`) sobre estos archivos debe incluir siempre `--env-file .env` (prod) o `--env-file .env.dev` (dev). Sin el flag, Compose busca el `.env` en `deploy/` (donde no existe), no resuelve `${POSTGRES_DB}`/`${POSTGRES_USER}` del servicio `postgres` y lo **recrea con esas variables vacías** — pasó en producción el 2026-07-29 al recrear solo `web`. Detalle en `docs/decisiones.md`, entrada 2026-07-29. Todos los comandos de esta skill ya incluyen el flag; no lo omitas si los adaptás.

## Comandos Básicos (producción — `deploy/compose.yml`)

### Reconstruir un servicio específico

```bash
# Desde la raíz del proyecto:
docker compose -f deploy/compose.yml --env-file .env build <servicio>

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
docker compose -f deploy/compose.yml --env-file .env build --no-cache <servicio>
```

### Reconstruir y reiniciar

```bash
docker compose -f deploy/compose.yml --env-file .env build <servicio>
docker compose -f deploy/compose.yml --env-file .env up -d <servicio>
```

### Reconstruir todos los servicios

```bash
docker compose -f deploy/compose.yml --env-file .env build
docker compose -f deploy/compose.yml --env-file .env up -d
```

## Gestión de Servicios (producción)

### Ver estado

```bash
docker compose -f deploy/compose.yml --env-file .env ps
```

### Ver logs

```bash
# Todos los servicios
docker compose -f deploy/compose.yml --env-file .env logs -f

# Servicio específico
docker compose -f deploy/compose.yml --env-file .env logs -f <servicio>

# Últimas N líneas
docker compose -f deploy/compose.yml --env-file .env logs --tail=100 <servicio>
```

### Reiniciar servicios

```bash
# Un servicio
docker compose -f deploy/compose.yml --env-file .env restart <servicio>

# Todos
docker compose -f deploy/compose.yml --env-file .env restart
```

### Detener servicios

```bash
# Detener sin eliminar
docker compose -f deploy/compose.yml --env-file .env stop

# Eliminar contenedores (no toca volúmenes)
docker compose -f deploy/compose.yml --env-file .env down --remove-orphans

# Eliminar incluyendo volúmenes (CUIDADO: borra datos)
docker compose -f deploy/compose.yml --env-file .env down -v
```

## Perfiles

### Activar worker de reportes

```bash
docker compose -f deploy/compose.yml --env-file .env --profile reports-worker up -d
```

### Activar pgAdmin

```bash
docker compose -f deploy/compose.yml --env-file .env --profile pgadmin up -d
```

## Troubleshooting

### Ver logs de build

```bash
docker compose -f deploy/compose.yml --env-file .env build --progress=plain <servicio>
```

### Entrar a un contenedor

```bash
docker compose -f deploy/compose.yml --env-file .env exec <servicio> bash
# o sh si no tiene bash
docker compose -f deploy/compose.yml --env-file .env exec <servicio> sh
```

### Ver uso de recursos

```bash
docker stats
```

### Limpiar imágenes no usadas

```bash
docker image prune -f
```

## Entorno Dev — `deploy/docker-compose.dev.yml`

El stack `lasfocasdev` corre en paralelo al productivo (`lasfocas`) sin compartir puertos, volúmenes ni red. Usa siempre `--env-file .env.dev`:

```bash
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev build <servicio>
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev up -d <servicio>
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev down --remove-orphans
docker compose -f deploy/docker-compose.dev.yml --env-file .env.dev ps
```

**No tocar `deploy/compose.yml` ni contenedores `lasfocas-*` (producción) sin instrucción explícita y puntual del usuario en ese momento** — ver `docs/decisiones.md`, directiva post-migración Nocturne (2026-07-29). Todo trabajo nuevo por default va a dev.

## Redes Docker (IPAM)

Ambas redes (`lasfocas_net` en prod, `lasfocas_dev_net` en dev) declaran subred **`/24` explícita** en `ipam.config` (`172.20.0.0/24` prod, `172.19.0.0/24` dev) — no se deja en manos del pool `/16` por default de Docker, que puede "secuestrar" rutas del host hacia destinos reales de la intranet dentro del mismo `/16`. Detalle completo, causa raíz y procedimiento de aplicación en ventana de mantenimiento para prod: `docs/mantenimiento_redes_produccion.md` y `docs/decisiones.md` (entradas 2026-08-05). Si se agrega una red nueva a este repo, declarar siempre `ipam.config.subnet` explícito — nunca dejar el default de Docker.

**Docker no permite cambiar la subred de una red existente sin recrearla** (`down` + `up`). Ningún servicio del proyecto usa `ipv4_address` (IP estática); si se agrega una, debe quedar entre `.1` y `.254` del `/24` correspondiente.

## Script de Inicio Rápido

```bash
./Start                    # Prod: down --remove-orphans + up -d --build + healthchecks
./scripts/start_dev.sh     # Dev: idem, con --env-file .env.dev incluido
```

## Consideraciones

1. **PostgreSQL**: no reconstruir postgres si hay datos importantes (usa volumen `postgres_data` / `postgres_dev_data`)
2. **Orden de inicio**: respetar dependencias definidas en compose
3. **Red**: cada stack tiene su propia red con subred `/24` explícita (`lasfocas_net` prod, `lasfocas_dev_net` dev) — nunca dejar el default `/16` de Docker
4. **Versiones**: nunca cambiar a `latest`, mantener versiones fijas
5. **`--env-file` obligatorio**: en todo comando `docker compose` manual sobre estos archivos (ver aviso arriba)
6. **Producción**: no bajar/recrear contenedores `lasfocas-*` sin autorización explícita y puntual del usuario
