# Nombre de archivo: Dockerfile
# Ubicación de archivo: api/Dockerfile
# Descripción: Imagen minimal para FastAPI (Python 3.11) con healthcheck por curl

FROM python:3.11-slim

# Evitar prompts interactivos y cache de pip
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias mínimas para healthchecks
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Requisitos primero para aprovechar cache
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir --only-binary=:all: -r requirements.txt

# Copiamos el código de la app y exponemos ambos paquetes (app y api.app)
RUN mkdir -p /app/api
COPY api/__init__.py /app/api/__init__.py
COPY api/app /app/api/app
RUN ln -s /app/api/app /app/app
COPY api/api_app /app/api_app
# Incluir módulos compartidos y core (logging, servicios comunes)
COPY modules /app/modules
COPY core /app/core
COPY Templates /app/Templates
# Incluir migraciones Alembic para ejecutar dentro del contenedor API
COPY db /app/db

EXPOSE 8000

# Arranque de la API
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
