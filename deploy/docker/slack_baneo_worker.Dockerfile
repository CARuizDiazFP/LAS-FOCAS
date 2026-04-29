# Nombre de archivo: slack_baneo_worker.Dockerfile
# Ubicación de archivo: deploy/docker/slack_baneo_worker.Dockerfile
# Descripción: Worker de notificaciones Slack para baneos. Hereda dependencias comunes de focas-base:latest.

FROM focas-base:latest
# curl, tzdata y dependencias Python comunes ya están en focas-base.
# TZ se inyecta vía variable de entorno en compose (TZ=America/Argentina/Buenos_Aires).

# Instala solo los paquetes específicos del worker Slack
COPY modules/slack_baneo_notifier/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY core/ /app/core/
COPY db/ /app/db/
COPY modules/__init__.py /app/modules/__init__.py
COPY modules/slack_baneo_notifier/ /app/modules/slack_baneo_notifier/

RUN useradd -m -u 1000 worker
USER worker

CMD ["python", "-m", "modules.slack_baneo_notifier.worker"]
