# Nombre de archivo: Dockerfile
# Ubicación de archivo: office_service/Dockerfile
# Descripción: Imagen Docker del microservicio LibreOffice/UNO

FROM python:3.11-slim-bookworm

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/usr/lib/python3/dist-packages:$PYTHONPATH

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libreoffice-core \
       libreoffice-writer \
       libreoffice-java-common \
       python3-uno \
       fonts-dejavu \
       locales \
       curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /usr/sbin/nologin office

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /app

RUN chown -R office:office /app

USER office

EXPOSE 8090 2002

ENV OFFICE_ENABLE_UNO=true \
    OFFICE_SOFFICE_BINARY=/usr/bin/soffice \
    OFFICE_SOFFICE_ACCEPT_STRING=socket,host=0.0.0.0,port=2002;urp;StarOffice.ComponentContext \
    OFFICE_UVICORN_HOST=0.0.0.0 \
    OFFICE_UVICORN_PORT=8090

CMD ["python", "-m", "app.runner"]
