# Nombre de archivo: Dockerfile
# Ubicación de archivo: web/Dockerfile
# Descripción: Imagen del servicio Web (UI) con FastAPI

FROM node:20.12.2-slim AS web-build
WORKDIR /frontend
COPY frontend/package.json frontend/tsconfig.json frontend/index.html ./
COPY frontend/src ./src
RUN npm ci || npm i && npm run build

FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

COPY app /app/app
COPY templates /app/templates
COPY static /app/static
COPY --from=web-build /frontend/dist /app/static/assets

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
