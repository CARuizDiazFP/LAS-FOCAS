# Nombre de archivo: Dockerfile
# Ubicación de archivo: web/Dockerfile
# Descripción: Construye el contenedor para el servicio web

FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi==0.110.1 uvicorn[standard]==0.29.0 \
    && useradd -ms /bin/bash appuser

COPY . /app

USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
