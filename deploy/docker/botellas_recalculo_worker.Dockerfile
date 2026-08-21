FROM focas-base:latest
# curl, tzdata y dependencias Python comunes (fastapi, uvicorn, redis, ...) ya están en focas-base.

COPY core/ /app/core/
COPY db/ /app/db/
COPY modules/__init__.py /app/modules/__init__.py
COPY modules/botellas_recalculo_worker/ /app/modules/botellas_recalculo_worker/

RUN chown -R focas:focas /app
USER focas

CMD ["python", "-m", "modules.botellas_recalculo_worker.worker"]
