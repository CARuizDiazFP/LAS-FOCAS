# Nombre de archivo: fo_monitor_worker.Dockerfile
# Ubicación de archivo: deploy/docker/fo_monitor_worker.Dockerfile
# Descripción: Dockerfile del worker de FO Monitor (verificación PRE/POST de cables con burritoIA vía Slack)

FROM focas-base:latest
# curl, tzdata y dependencias Python comunes (fastapi, uvicorn, sqlalchemy, pyproj) ya
# están en focas-base; slack_sdk no (lo trae el requirements propio).

COPY modules/fo_monitor_worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY core/ /app/core/
COPY db/ /app/db/
COPY modules/__init__.py /app/modules/__init__.py
# core/services/fo_monitor/alcance.py reusa RE_BOT_SUFIJO de modules/slack_baneo_notifier/camara_search.py
# (mismo criterio que botellas_recalculo_worker.Dockerfile: el paquete no importa slack_sdk al cargarse).
COPY modules/slack_baneo_notifier/ /app/modules/slack_baneo_notifier/
COPY modules/fo_monitor_worker/ /app/modules/fo_monitor_worker/

RUN chown -R focas:focas /app
USER focas

CMD ["python", "-m", "modules.fo_monitor_worker.worker"]
