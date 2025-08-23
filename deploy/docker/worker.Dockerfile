# Nombre de archivo: worker.Dockerfile
# Ubicación de archivo: deploy/docker/worker.Dockerfile
# Descripción: Imagen para el servicio de tareas en segundo plano

FROM python:3.11-slim

WORKDIR /app

COPY ../../requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY ../../modules /app/modules
COPY ../../core /app/core

RUN useradd -m worker && chown -R worker:worker /app
USER worker

CMD ["python", "-m", "modules.worker"]
