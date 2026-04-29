# Nombre de archivo: Dockerfile
# Ubicación de archivo: api/Dockerfile
# Descripción: Imagen del servicio API (FastAPI). Hereda dependencias comunes de focas-base:latest.

FROM focas-base:latest
# ENV, WORKDIR /app y dependencias comunes ya están en focas-base.

# Instala solo los paquetes específicos de la API
COPY api/requirements.txt /tmp/api-requirements.txt
RUN pip install --no-cache-dir -r /tmp/api-requirements.txt \
    && rm /tmp/api-requirements.txt

RUN mkdir -p /app/api
COPY api/__init__.py /app/api/__init__.py
COPY api/app /app/api/app
RUN ln -s /app/api/app /app/app
COPY api/api_app /app/api_app
# Incluir módulos compartidos y core (logging, servicios comunes)
COPY modules /app/modules
COPY core /app/core
COPY Templates /app/Templates
# Incluir migraciones Alembic para ejecutar dentro del contenedor API
COPY db /app/db

EXPOSE 8000

# Arranque de la API
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
