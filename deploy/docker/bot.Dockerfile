# Nombre de archivo: bot.Dockerfile
# Ubicación de archivo: deploy/docker/bot.Dockerfile
# Descripción: Imagen del bot de Telegram (aiogram, Python 3.11-slim)

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias nativas para contextily/pyproj (GDAL/PROJ)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gdal-bin \
        libgdal-dev \
        libproj-dev \
        libgeos-dev \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Instalación de dependencias del bot
COPY bot_telegram/requirements.txt /app/bot_requirements.txt
RUN pip install --no-cache-dir -r /app/bot_requirements.txt

# Copiamos solo lo necesario del proyecto
COPY bot_telegram /app/bot_telegram

# Usuario no root opcional (hardening)
# RUN useradd -m bot && chown -R bot:bot /app && USER bot

CMD ["python", "-m", "bot_telegram.app"]
