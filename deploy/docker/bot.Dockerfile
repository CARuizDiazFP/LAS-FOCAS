# Nombre de archivo: bot.Dockerfile
# Ubicación de archivo: deploy/docker/bot.Dockerfile
# Descripción: Imagen del bot de Telegram (aiogram). Hereda dependencias comunes de focas-base:latest.

FROM focas-base:latest
# ENV, WORKDIR /app y dependencias comunes ya están en focas-base.

# Instala solo aiogram (el resto de las dependencias del bot están en focas-base)
COPY bot_telegram/requirements.txt /app/bot_requirements.txt
RUN pip install --no-cache-dir -r /app/bot_requirements.txt

# Copiamos solo lo necesario del proyecto
COPY bot_telegram /app/bot_telegram

# Usuario no root opcional (hardening)
# RUN useradd -m bot && chown -R bot:bot /app && USER bot

CMD ["python", "-m", "bot_telegram.app"]
