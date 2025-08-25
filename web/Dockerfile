# Nombre de archivo: Dockerfile
# Ubicación de archivo: web/Dockerfile
# Descripción: Construye el contenedor para el servicio web

FROM python:3.11-slim

WORKDIR /app

# Copiamos el archivo de dependencias compartido y lo instalamos sin caché
COPY ../requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && useradd -ms /bin/bash appuser

# Incorporamos el código fuente del servicio
COPY . /app

USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
