# Nombre de archivo: cromo_worker.Dockerfile
# Ubicación de archivo: deploy/docker/cromo_worker.Dockerfile
# Descripción: Worker dedicado de ingesta Cromo Red. Hereda dependencias comunes de focas-base:latest.

FROM focas-base:latest
# curl, tzdata y dependencias Python comunes (fastapi, uvicorn, asyncpg, json5, ...) ya están en focas-base.
# TZ se inyecta vía variable de entorno en compose (TZ=America/Argentina/Buenos_Aires).

# Instala solo los paquetes específicos del worker Cromo
COPY modules/cromo_worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY core/ /app/core/
COPY db/ /app/db/
COPY modules/__init__.py /app/modules/__init__.py
# core/services/camara_hierarchy_service.py (vía botella_recompute_queue →
# botella_duplicados_service, importado por core/services/cromo/ingesta.py desde el fix "ID dual"
# del 2026-08-22) reusa RE_BOT_SUFIJO y helpers de normalización de
# modules/slack_baneo_notifier/camara_search.py; ese submódulo no importa slack_sdk a nivel de
# paquete (__init__.py vacío), así que copiarlo acá no arrastra dependencias del worker de Slack.
# Sin esta línea el worker cae en ModuleNotFoundError al arrancar (crash-loop con
# restart: unless-stopped) — mismo COPY que ya tiene botellas_recalculo_worker.Dockerfile.
COPY modules/slack_baneo_notifier/ /app/modules/slack_baneo_notifier/
COPY modules/cromo_worker/ /app/modules/cromo_worker/

RUN chown -R focas:focas /app
USER focas

CMD ["python", "-m", "modules.cromo_worker.worker"]
