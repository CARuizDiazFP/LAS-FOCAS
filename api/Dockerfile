# Nombre de archivo: Dockerfile
# Ubicación de archivo: api/Dockerfile
# Descripción: Imagen minimal para FastAPI (Python 3.11) con healthcheck por curl

FROM python:3.11-slim

# Evitar prompts interactivos y cache de pip
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias del sistema mínimas (curl para healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Requisitos primero para aprovechar cache
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

# Copiamos el código de la app
COPY app /app/app

# Crear usuario no root para ejecutar la API y aplicar principio de mínimos privilegios
RUN useradd -m api && chown -R api:api /app
USER api

EXPOSE 8000

# Arranque de la API
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
