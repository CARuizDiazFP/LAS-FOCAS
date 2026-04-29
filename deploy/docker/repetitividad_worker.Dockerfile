# Nombre de archivo: repetitividad_worker.Dockerfile
# Ubicación de archivo: deploy/docker/repetitividad_worker.Dockerfile
# Descripción: Worker dedicado a mapas/geopandas para informes de repetitividad.
#              Hereda dependencias comunes de focas-base:latest. Solo agrega GDAL y geopandas.

FROM focas-base:latest
# Dependencias Python comunes ya están en focas-base.
# Solo se agregan las librerías OS y Python específicas de geopandas/GDAL.

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

RUN pip install --no-cache-dir geopandas==0.14.4

COPY . /app

CMD ["python", "-m", "modules.informes_repetitividad.worker"]
