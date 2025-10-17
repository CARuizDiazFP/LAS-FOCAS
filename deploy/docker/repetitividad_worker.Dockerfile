# Nombre de archivo: repetitividad_worker.Dockerfile
# Ubicación de archivo: deploy/docker/repetitividad_worker.Dockerfile
# Descripción: Worker dedicado a mapas/geopandas para informes de repetitividad

FROM python:3.11-slim-bookworm

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gdal-bin \
       libgdal-dev \
       build-essential \
       libc6-dev \
       libgeos-dev \
       libproj-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
RUN pip install --no-cache-dir geopandas==0.14.4

COPY . /app

CMD ["python", "-m", "modules.informes_repetitividad.worker"]
