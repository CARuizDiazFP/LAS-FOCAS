# Nombre de archivo: office_service.md
# Ubicación de archivo: docs/office_service.md
# Descripción: Documentación del microservicio LibreOffice/UNO

# Microservicio LibreOffice/UNO

## Contexto

El proyecto LAS-FOCAS requiere generar informes y transformar plantillas heredadas de Sandy sin depender de pywin32. Para ello se implementa un microservicio dockerizado que encapsula LibreOffice en modo headless (UNO) y expone una API REST mínima basada en FastAPI.

## Arquitectura

- Imagen base `python:3.11-slim-bookworm`.
- Instalación de `libreoffice-core`, `libreoffice-writer`, `python3-uno` y fuentes básicas para renderizar documentos.
- Proceso `soffice --headless` levantado por `office_service.app.runner` antes de iniciar Uvicorn.
- API FastAPI (`office_service.app.main`) con endpoints:
  - `GET /health`: reporta estado general del servicio y conectividad UNO.
  - `POST /convert`: placeholder para conversiones de documentos (pendiente de implementación con UNO verdaderamente activo).
- Configuración vía variables `OFFICE_*`. Ejemplos relevantes:
  - `OFFICE_ENABLE_UNO=true|false` para forzar modo offline.
  - `OFFICE_SOFFICE_PORT` (default 2002) y `OFFICE_SOFFICE_CONNECT_HOST` (default 127.0.0.1).
  - `OFFICE_LOG_LEVEL=INFO`.

## Uso previsto

1. Desplegar el servicio junto al stack principal mediante `docker-compose`.
2. Consumir la API interna (no se publica al host) desde otros microservicios que requieran conversiones o manipulación de documentos.
3. Consumir las plantillas oficiales desde `Templates/` (repositorio raíz). El contenedor deberá montar esta carpeta en próximas iteraciones (`TODO: definir volumen templates/`).

## Próximos pasos

- Implementar flujo real de conversión (`UNO` + guardado en volumen compartido).
- Gestionar colas para operaciones pesadas (integración futura con worker Celery/RQ).
- Añadir endpoints para gestión de plantillas (listar/actualizar) con autenticación interna.

## Consideraciones de seguridad

- El servicio se expone únicamente a la red interna `lasfocas_net` y no publica puertos al host.
- `office` es el usuario no privilegiado dentro del contenedor.
- Requiere validación de archivos de entrada (tamaño, extensión) antes de habilitar conversiones reales.

## Tests

- `tests/test_office_service_health.py` valida la salud del endpoint en modo offline y configuración por defecto.
- Ejecutar `pytest tests/test_office_service_health.py` antes de desplegar modificaciones funcionales.

## Referencias

- Documentación UNO: https://wiki.documentfoundation.org/Documentation/DevGuide/OpenOffice.org_Developers_Guide
- Librería python-uno incluida con LibreOffice (`python3-uno`).
