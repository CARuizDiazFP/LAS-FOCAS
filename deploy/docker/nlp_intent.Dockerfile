# Nombre de archivo: nlp_intent.Dockerfile
# Ubicación de archivo: deploy/docker/nlp_intent.Dockerfile
# Descripción: Imagen del microservicio de clasificación de intención. Hereda todas las dependencias de focas-base:latest.

FROM focas-base:latest
# Todas las dependencias Python (fastapi, uvicorn, httpx, pydantic, orjson)
# ya están en focas-base. No se requiere instalación adicional.

COPY nlp_intent/app /app/app
# Módulos compartidos y core
COPY modules /app/modules
COPY core /app/core

USER 1000:1000
EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
