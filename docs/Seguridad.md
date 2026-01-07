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
- Publicación del servicio `web` acotada a la IP LAN `192.168.241.28:8080` en `deploy/compose.yml` para evitar exposición en 0.0.0.0.
- Postgres sin publicación al host: `deploy/compose.yml` usa `expose: 5432` para que solo sea accesible por servicios internos.

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
  - Para la toolchain geoespacial (`matplotlib`, `contextily`, `pyproj`, GDAL/PROJ) monitorear CVEs de librerías nativas y validar hashes/firmas en cada rebuild.
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

## Endurecimiento de red y firewall (2025-12-30)

- Objetivo: limitar el acceso a `lasfocas-web` a las subredes requeridas, reforzar `rp_filter` y asegurar que las reglas persistan tras reinicio.cd /home/focal/proyectos/LAS-FOCAS
WEB_ALLOWED_SUBNETS="190.12.96.0/24" \
WEB_HOST="192.168.241.28" \
MGMT_IFACE="ens224" \
PERSIST_RULES=true \
bash scripts/firewall_hardening.sh
- Publicación del puerto 8080 sólo en la IP LAN: ver `ports` en [deploy/compose.yml](deploy/compose.yml).
- Firewall/iptables (idempotente): usar [scripts/firewall_hardening.sh](scripts/firewall_hardening.sh). Ejecutar como root y ajustar subredes permitidas, por ejemplo:
  - `WEB_ALLOWED_SUBNETS="190.12.96.0/24 192.168.241.0/24" WEB_HOST=192.168.241.28 PERSIST_RULES=true bash scripts/firewall_hardening.sh`
  - Reglas aplicadas: `INPUT` y `DOCKER-USER` permiten sólo las subredes definidas hacia 8080, luego `DROP`; `POSTROUTING` mantiene SNAT `172.18.0.0/16 -> ens224` sin duplicados.
- `rp_filter`: el script fija `1` en interfaces generales y mantiene `2` en `ens224` (o la interfaz definida en `MGMT_IFACE`), con persistencia en `/etc/sysctl.d/99-lasfocas.conf`.
- Persistencia de reglas: habilitar `iptables-persistent`/`netfilter-persistent` y ejecutar con `PERSIST_RULES=true` (el script guarda automáticamente si la herramienta está instalada). Verificar con `iptables-save` y `sysctl net.ipv4.conf.all.rp_filter net.ipv4.conf.ens224.rp_filter`.
- Control de superficie: revisar servicios escuchando con `ss -tulpen` y desactivar los innecesarios; asegurar SSH sólo por la red de gestión y con autenticación por clave pública.
- TLS y autenticación: si el portal queda accesible en LAN, front-end detrás de proxy TLS (Nginx/Traefik) y proteger `/health` con auth básica o allowlist de IP.

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
