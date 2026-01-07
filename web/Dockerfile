# Nombre de archivo: Dockerfile
# Ubicación de archivo: web/Dockerfile
# Descripción: Imagen del servicio Web (UI) con FastAPI

FROM node:20.12.2-slim AS web-build
WORKDIR /frontend
# Copiamos sólo el frontend (el build context ahora es la raíz del repo)
COPY web/frontend/package.json web/frontend/tsconfig.json web/frontend/index.html ./
COPY web/frontend/package-lock.json ./package-lock.json
COPY web/frontend/src ./src
RUN if [ -f package-lock.json ]; then \
        npm ci --no-audit --no-fund; \
    else \
        npm install --no-audit --no-fund --prefer-offline; \
    fi \
    && npm run build

FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY web/requirements.txt /app/requirements.txt
# Instalamos dependencias (bcrypt fijado en requirements para evitar backend defectuoso)
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir --only-binary=:all: -r requirements.txt

COPY web/app /app/app
COPY web/web_app /app/web_app
COPY web/templates /app/templates
COPY web/static /app/static
COPY web/tools /app/web/tools
COPY web/chat_ws.py /app/web/chat_ws.py
# Incluir paquete core para logging centralizado
COPY core /app/core
COPY modules /app/modules
COPY db /app/db
COPY --from=web-build /frontend/dist /app/static/assets

EXPOSE 8080

CMD ["uvicorn", "web_app.main:app", "--host", "0.0.0.0", "--port", "8080"]
