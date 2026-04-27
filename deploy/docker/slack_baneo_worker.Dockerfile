# Nombre de archivo: slack_baneo_worker.Dockerfile
# Ubicación de archivo: deploy/docker/slack_baneo_worker.Dockerfile
# Descripción: Worker dedicado a notificaciones periódicas de baneos de cámaras a Slack

FROM python:3.11-slim-bookworm

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tzdata \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Argentina/Buenos_Aires

WORKDIR /app

COPY modules/slack_baneo_notifier/requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY core/ /app/core/
COPY db/ /app/db/
COPY modules/__init__.py /app/modules/__init__.py
COPY modules/slack_baneo_notifier/ /app/modules/slack_baneo_notifier/

RUN useradd -m -u 1000 worker
USER worker

CMD ["python", "-m", "modules.slack_baneo_notifier.worker"]
