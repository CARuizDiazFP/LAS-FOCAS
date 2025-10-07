# Nombre de archivo: Seguridad.md
# Ubicación de archivo: docs/Seguridad.md
# Descripción: Lineamientos de seguridad, riesgos y controles para LAS-FOCAS

# Seguridad en LAS-FOCAS

Este documento compila los lineamientos de seguridad aplicables al proyecto LAS-FOCAS, riesgos comunes, controles implementados y checklist para nuevas implementaciones.

## Contexto operativo

- Entorno principal: VM Debian 12.4.
- Conectividad: salida a Internet y acceso a red local (intranet).
- Arquitectura: microservicios dockerizados, PostgreSQL local, servicios internos expuestos en red interna de compose.
- Implicancia: toda nueva implementación debe evaluar exposición de puertos/servicios, dependencias y manejo de datos en un entorno mixto (Internet + red local).

## Principios y políticas

- Principio de mínimos privilegios (DB, contenedores, archivos). Evitar usuario root en contenedores salvo necesidad justificada.
- Prohibido exponer secrets en código o logs. Uso de `.env` y planificación de migración a Docker Secrets.
- No usar `latest`: fijar versiones de imágenes y librerías; mantener reproducibilidad.
- Fail-safe por defecto y valores seguros ante ambigüedad (documentados en PR).
- Idempotencia: scripts/servicios deben poder ejecutarse múltiples veces sin efectos laterales inesperados.
- Logging prudente: no registrar texto íntegro del usuario salvo `LOG_RAW_TEXT=true`.

## Controles actuales implementados

- Allowlist de IDs de Telegram en el bot.
- Login básico en panel web (plan de fortalecimiento posterior).
- Redes internas en docker-compose (`expose` en lugar de `ports` para servicios internos).
- Versionado estricto de dependencias (evitar `latest`).
- Validación y escape de entradas en superficies expuestas (bot, APIs).
- Tratamiento de errores con timeouts (HTTP 15s por defecto) y reintentos con backoff.
- Logs estructurados con metadatos (service, action, request_id, timestamps) y prudencia en datos sensibles.
- Auditoría básica de dependencias antes de incorporarlas.
- Servicios web/bot llaman al API de reportes mediante `REPORTS_API_BASE`; asegúrese de que apunte a la red interna (`http://api:8000`).

## Riesgos comunes a considerar

- Exposición de servicios internos a la red host o Internet por error de configuración (ports vs expose).
- Filtración de secrets en repositorio, imágenes o logs.
- Dependencias vulnerables o sin mantenimiento.
- Escalada de privilegios por ejecuciones como root innecesarias.
- Inyección en entradas no validadas (comandos, SQL, rutas de archivos para plantillas/reportes).
- Procesamiento de documentos (LibreOffice) con archivos maliciosos cargados por usuarios.
- Almacenamiento de conversaciones/PII sin controles.

## Checklist para nuevas implementaciones

- Red y exposición
  - ¿Requiere puerto hacia host? Si no, usar `expose` y red interna.
  - Limitar orígenes/ACL cuando corresponda.
- Credenciales y configuración
  - Variables sensibles en `.env` (no commitear). Planear Docker Secrets.
  - Rotación de claves documentada.
- Contenedores
  - Usuario no root si es viable; `readOnlyRootFilesystem` cuando aplique.
  - Imágenes base slim/alpine (si compatible) y multi-stage builds.
- Dependencias
  - Fijar versiones. Revisar CVEs. Eliminar paquetes no usados.
- Datos
  - Clasificar datos (sensibles/no). Minimización y cifrado en reposo/transporte cuando corresponda.
  - Política de retención y acceso.
- Logging y métricas
  - Logs estructurados sin PII salvo flag explícito.
  - Healthchecks y contadores básicos.
- Errores y resiliencia
  - Timeouts, reintentos con backoff, circuit breaker para externos.
- Pruebas
  - Unit tests y mocks para integraciones externas.
  - Tests de integración básicos para endpoints/servicios nuevos.
- Documentación y PR
  - Actualizar `README`, `AGENTS.md` y `docs/` del módulo.
  - Registrar cambios e impactos en `docs/PR/YYYY-MM-DD.md` (esta fecha).

## Respuesta a incidentes (básico)

- Aislar servicio afectado (remover publicación de puertos, escalar logs a nivel debug temporalmente sin PII).
- Revocar/rotar secretos comprometidos y reemitir imágenes.
- Parchear dependencias vulnerables y reconstruir.
- Registrar el incidente, causas y acciones en `docs/PR/` y `docs/decisiones.md`.

## Próximos pasos

- Migrar secrets a Docker Secrets.
- Automatizar escaneo de vulnerabilidades en CI.
- Endurecer headers/CORS en servicios web.
- Revisión periódica de permisos en DB y contenedores.
- Definir controles de validación/sandbox para el microservicio LibreOffice (`office_service`).
