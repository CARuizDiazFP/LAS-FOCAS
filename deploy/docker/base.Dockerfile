# Nombre de archivo: base.Dockerfile
# Ubicación de archivo: deploy/docker/base.Dockerfile
# Descripción: Imagen base multi-stage para todos los servicios Python de LAS-FOCAS (excepto office_service).
#              Stage builder: compila wheels precompilados con herramientas de compilación pesadas.
#              Stage runtime: imagen final liviana que instala solo los wheels compilados.
# Build: docker build -t focas-base:latest -f deploy/docker/base.Dockerfile .
# O usar: ./scripts/build_base.sh

# ─── Stage 1: Builder ─────────────────────────────────────────────────────────
# Instala herramientas de compilación y genera wheels precompilados para todos
# los paquetes comunes y sus dependencias transitivas.
FROM python:3.11-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       gcc \
       libpq-dev \
       libffi-dev \
       libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY common-requirements.txt /tmp/common-requirements.txt

# Descarga y compila todos los paquetes comunes como wheels precompilados.
# pip wheel también resuelve y descarga todas las dependencias transitivas.
RUN python -m pip install --upgrade pip \
    && pip wheel \
       --wheel-dir /wheels \
       --no-cache-dir \
       -r /tmp/common-requirements.txt

# ─── Stage 2: Runtime ─────────────────────────────────────────────────────────
# Imagen final liviana: sin compiladores, solo librerías de ejecución.
# Instala los wheels pre-compilados del stage builder (sin acceso a internet).
FROM python:3.11-slim-bookworm AS runtime

ARG REQUIREMENTS_HASH=unknown
LABEL focas.requirements.hash="${REQUIREMENTS_HASH}" \
      focas.image="focas-base" \
      focas.description="Imagen base compartida LAS-FOCAS — Python 3.11 + dependencias comunes"

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG DEBIAN_FRONTEND=noninteractive

# Solo librerías de ejecución (sin compiladores ni headers de desarrollo)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       curl \
       libpq5 \
       libexpat1 \
       tzdata \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
COPY common-requirements.txt /tmp/common-requirements.txt

# Instala desde los wheels locales (sin internet, sin compilación)
# y limpia la carpeta de wheels en el mismo layer para no inflar la imagen final.
RUN pip install --upgrade pip \
    && pip install \
       --no-index \
       --find-links=/wheels \
       -r /tmp/common-requirements.txt \
    && rm -rf /wheels /tmp/common-requirements.txt

WORKDIR /app
