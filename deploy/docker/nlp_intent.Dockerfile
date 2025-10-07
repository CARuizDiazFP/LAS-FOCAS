# Nombre de archivo: nlp_intent.Dockerfile
# Ubicación de archivo: deploy/docker/nlp_intent.Dockerfile
# Descripción: Imagen para el microservicio de clasificación de intención

FROM python:3.11-slim
WORKDIR /app

COPY nlp_intent/requirements.txt /app/requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends curl \
	&& rm -rf /var/lib/apt/lists/* \
	&& pip install --no-cache-dir -r /app/requirements.txt

COPY nlp_intent/app /app/app
# Módulos compartidos y core
COPY modules /app/modules
COPY core /app/core

USER 1000:1000
EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
