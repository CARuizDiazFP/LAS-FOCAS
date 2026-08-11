# Nombre de archivo: cromo_worker.Dockerfile
# Ubicación de archivo: deploy/docker/cromo_worker.Dockerfile
# Descripción: Worker dedicado de ingesta Cromo Red. Hereda dependencias comunes de focas-base:latest.

FROM focas-base:latest
# curl, tzdata y dependencias Python comunes (fastapi, uvicorn, asyncpg, json5, ...) ya están en focas-base.
# TZ se inyecta vía variable de entorno en compose (TZ=America/Argentina/Buenos_Aires).

# Instala solo los paquetes específicos del worker Cromo
COPY modules/cromo_worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY core/ /app/core/
COPY db/ /app/db/
COPY modules/__init__.py /app/modules/__init__.py
COPY modules/cromo_worker/ /app/modules/cromo_worker/

RUN chown -R focas:focas /app
USER focas

CMD ["python", "-m", "modules.cromo_worker.worker"]
