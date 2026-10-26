# Nombre de archivo: office_service.md
# Ubicación de archivo: docs/office_service.md
# Descripción: Documentación del microservicio LibreOffice/UNO para soporte de conversiones del stack moderno

# Microservicio LibreOffice/UNO

## Contexto

El proyecto LAS-FOCAS requiere generar informes y transformar plantillas heredadas de Sandy sin depender de pywin32. Para ello se implementa un microservicio dockerizado que encapsula LibreOffice en modo headless (UNO) y expone una API REST mínima basada en FastAPI para consumo interno por la API y la SPA.

## Arquitectura

- Imagen base `python:3.11-slim-bookworm`.
- Instalación de `libreoffice-core`, `libreoffice-writer`, `python3-uno` y fuentes básicas para renderizar documentos.
- Proceso `soffice --headless` levantado por `office_service.app.runner` antes de iniciar Uvicorn.
- API FastAPI (`office_service.app.main`) con endpoints:
  - `GET /health`: reporta estado general del servicio y conectividad UNO.
  - `POST /convert`: convierte un documento a PDF (implementado el 2026-10-26; antes era un placeholder que respondía 422 a todo).
- Configuración vía variables `OFFICE_*`. Ejemplos relevantes:
  - `OFFICE_ENABLE_UNO=true|false` para forzar modo offline.
  - `OFFICE_SOFFICE_PORT` (default 2002) y `OFFICE_SOFFICE_CONNECT_HOST` (default 127.0.0.1).
  - `OFFICE_LOG_LEVEL=INFO`.
  - `OFFICE_MAX_FILE_SIZE` (bytes, default 50 MB) y `OFFICE_CONVERT_TIMEOUT` (segundos, default 120).

## `POST /convert`

- **Pedido**: `multipart/form-data` con el campo `file`; `output_format` por query (default y único valor
  aceptado hoy: `pdf`).
- **Respuesta 200**: los bytes del PDF (`application/pdf`, `Content-Disposition: attachment`).
- **Errores**: 400 formato de salida o extensión no soportados, o archivo vacío; 413 supera
  `OFFICE_MAX_FILE_SIZE`; 503 sin binario `soffice`; 504 timeout; 500 `soffice` no generó salida.
- **Entradas aceptadas**: `.docx`, `.doc`, `.odt`, `.rtf`. La imagen sólo instala `libreoffice-writer`:
  planillas y presentaciones necesitarían `libreoffice-calc`/`-impress`.
- **Cómo convierte**: un `soffice --headless --convert-to` por pedido, en un directorio temporal y con
  un perfil de usuario propio (`-env:UserInstallation`), porque el perfil por defecto lo tiene tomado
  la instancia UNO del `runner`. Las conversiones se serializan. Medido en dev: DOCX de una página
  ≈ 6 s (arranque en frío de `soffice`); la instancia UNO sigue disponible después.
- **Consumidor**: la herramienta MCP `ConvertirDocAPdf` (`core/mcp/registry.py`, ver `docs/mcp.md`).

```bash
curl -fsS -X POST "http://office:8090/convert?output_format=pdf" -F "file=@informe.docx" -o informe.pdf
```

## Uso previsto

1. Desplegar el servicio junto al stack principal mediante `docker-compose`.
2. Consumir la API interna (no se publica al host) desde otros microservicios que requieran conversiones o manipulación de documentos.
3. Consumir las plantillas oficiales desde `Templates/` (repositorio raíz). El contenedor deberá montar esta carpeta en próximas iteraciones (`TODO: definir volumen templates/`).

## Próximos pasos

- Gestionar colas para operaciones pesadas (integración futura con worker Celery/RQ).
- Añadir endpoints para gestión de plantillas (listar/actualizar) con autenticación interna.

## Consideraciones de seguridad

- El servicio se expone únicamente a la red interna `lasfocas_net` y no publica puertos al host.
- `office` es el usuario no privilegiado dentro del contenedor.
- `/convert` valida extensión, tamaño (lectura por bloques, corta al superar el máximo) y usa un nombre de
  archivo saneado dentro de un directorio temporal que se borra al terminar.
- No consume secretos sensibles actualmente; su configuración usa variables `OFFICE_*` operativas. Si se agregan integraciones externas, deberán usar Docker Secrets o el helper compartido antes de aceptar tokens por entorno.

## Tests

- `tests/test_office_service_health.py` valida la salud del endpoint en modo offline y configuración por defecto.
- `tests/test_office_service_convert.py` cubre `/convert` (éxito, 400, 413, 503, 504, 500 y el comando con perfil propio) con `soffice` simulado.
- Ejecutar `pytest tests/test_office_service_health.py tests/test_office_service_convert.py` antes de desplegar modificaciones funcionales.

## Referencias

- Documentación UNO: https://wiki.documentfoundation.org/Documentation/DevGuide/OpenOffice.org_Developers_Guide
- Librería python-uno incluida con LibreOffice (`python3-uno`).
