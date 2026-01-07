# Nombre de archivo: nlp_intent.Dockerfile
# Ubicación de archivo: deploy/docker/nlp_intent.Dockerfile
# Descripción: Imagen para el microservicio de clasificación de intención

FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY nlp_intent/requirements.txt /app/requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends curl \
	&& rm -rf /var/lib/apt/lists/* \
	&& python -m pip install --upgrade pip \
	&& pip install --no-cache-dir --only-binary=:all: -r /app/requirements.txt

COPY nlp_intent/app /app/app
# Módulos compartidos y core
COPY modules /app/modules
COPY core /app/core

USER 1000:1000
EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
