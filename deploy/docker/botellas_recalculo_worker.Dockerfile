# Nombre de archivo: botellas_recalculo_worker.Dockerfile
# Ubicación de archivo: deploy/docker/botellas_recalculo_worker.Dockerfile
# Descripción: Dockerfile del worker dedicado de recálculo de Botellas duplicadas

FROM focas-base:latest
# curl, tzdata y dependencias Python comunes (fastapi, uvicorn, redis, ...) ya están en focas-base.

COPY core/ /app/core/
COPY db/ /app/db/
COPY modules/__init__.py /app/modules/__init__.py
# core/services/camara_hierarchy_service.py reusa RE_BOT_SUFIJO y helpers de normalización de
# modules/slack_baneo_notifier/camara_search.py (misma regex de negocio probada contra datos
# reales del listener de ingresos Slack); ese submódulo no importa slack_sdk a nivel de paquete
# (__init__.py vacío), así que copiarlo acá no arrastra dependencias del worker de Slack.
COPY modules/slack_baneo_notifier/ /app/modules/slack_baneo_notifier/
COPY modules/botellas_recalculo_worker/ /app/modules/botellas_recalculo_worker/

RUN chown -R focas:focas /app
USER focas

CMD ["python", "-m", "modules.botellas_recalculo_worker.worker"]
