# Nombre de archivo: Seguridad.md
# Ubicación de archivo: docs/Seguridad.md
# Descripción: Lineamientos de seguridad, riesgos y controles para LAS-FOCAS

# Seguridad en LAS-FOCAS

Este documento prioriza la seguridad de una arquitectura API + SPA. El foco principal es prevenir exposición de secretos, reforzar CORS, validar entradas y reducir riesgos de XSS y manejo inseguro de tokens en Vue 3 y FastAPI.

Este documento compila los lineamientos de seguridad aplicables al proyecto LAS-FOCAS, riesgos comunes, controles implementados y checklist para nuevas implementaciones.

## Contexto operativo

- Entorno principal: VM Debian 13.
- Conectividad: salida a Internet y acceso a red local (intranet).
- Arquitectura: microservicios dockerizados, PostgreSQL local, servicios internos expuestos en red interna de compose.
- Implicancia: toda nueva implementación debe evaluar exposición de puertos/servicios, dependencias y manejo de datos en un entorno mixto (Internet + red local).

## Principios y políticas

- Principio de mínimos privilegios (DB, contenedores, archivos). Evitar usuario root en contenedores salvo necesidad justificada.
- Prohibido exponer secrets en código o logs. En dev se usan Docker Secrets locales con fallback temporal a `.env`; producción debe usar un secret store administrado.
- No usar `latest`: fijar versiones de imágenes y librerías; mantener reproducibilidad.
- Fail-safe por defecto y valores seguros ante ambigüedad (documentados en PR).
- Idempotencia: scripts/servicios deben poder ejecutarse múltiples veces sin efectos laterales inesperados.
- Logging prudente: no registrar texto íntegro del usuario salvo `LOG_RAW_TEXT=true`.
- En la SPA, auditar cualquier uso de `v-html` y evitar inyección de HTML no confiable.
- En el frontend, evitar `localStorage` para tokens sensibles; priorizar cookies `HttpOnly` o memoria segura según el caso.

## Controles actuales implementados

- Allowlist de IDs de Telegram en el bot.
- Login básico en panel web (plan de fortalecimiento posterior).
- Redes internas en docker-compose (`expose` en lugar de `ports` para servicios internos).
- Versionado estricto de dependencias (evitar `latest`).
- Validación y escape de entradas en superficies expuestas (bot, APIs).
- Validación estricta de entradas/salidas con Pydantic en APIs.
- CORS restrictivo con allowlist explícita en FastAPI.
- Tratamiento de errores con timeouts (HTTP 15s por defecto) y reintentos con backoff.
- Logs estructurados con metadatos (service, action, request_id, timestamps) y prudencia en datos sensibles.
- Auditoría básica de dependencias antes de incorporarlas.
- Servicios web/bot llaman al API de reportes mediante `REPORTS_API_BASE`; asegúrese de que apunte a la red interna (`http://api:8000`).
- Publicación del servicio `web` acotada a la IP LAN `172.18.208.162:8080` en `deploy/compose.yml` para evitar exposición en 0.0.0.0.
- El despliegue estándar no debe depender de motores LLM locales ni de `host.docker.internal`; la clasificación productiva se resuelve por proveedor externo vía API y secreto en `.env`.
- Postgres sin publicación al host: `deploy/compose.yml` usa `expose: 5432` para que solo sea accesible por servicios internos.
- El worker `slack_baneo_worker` expone solo `8095` dentro de la red de compose y toma credenciales Slack desde `.env`; no se publican tokens ni puertos Slack hacia el host.
- Las auditorías de seguridad del repositorio se estandarizan con el agente `security` y las skills `security-scan`, `dependency-audit`, `secret-detection` y `sast-analysis`.
- CI ejecuta `scripts/check_no_plaintext_secrets.sh` para bloquear `.env` versionados, llaves y passwords dev en texto plano.

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
  - Variables sensibles en Docker Secrets o secret store; `.env` solo como fallback local no versionado.
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
WEB_HOST="172.18.208.162" \
MGMT_IFACE="ens224" \
PERSIST_RULES=true \
bash scripts/firewall_hardening.sh
- Publicación del puerto 8080 sólo en la IP LAN: ver `ports` en [deploy/compose.yml](deploy/compose.yml).
- Firewall/iptables (idempotente): usar [scripts/firewall_hardening.sh](scripts/firewall_hardening.sh). Ejecutar como root y ajustar subredes permitidas, por ejemplo:
  - `WEB_ALLOWED_SUBNETS="190.12.96.0/24 192.168.241.0/24" WEB_HOST=172.18.208.162 PERSIST_RULES=true bash scripts/firewall_hardening.sh`
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

## Estrategia de secretos en producción

- Implementado: `deploy/compose.yml` usa Docker Compose Secrets basados en archivo (el host corre Docker en
  modo no-Swarm — `docker info` reporta `Swarm.LocalNodeState: inactive` —, así que no aplica
  `docker secret create`/`external: true`; Compose monta el archivo directamente en `/run/secrets/<nombre>`
  sin necesidad de Swarm).
- Los 9 secretos (`db_password_v1`, `api_key_v1`, `web_secret_key_v1`, `telegram_bot_token_v1`,
  `openai_api_key_v1`, `smtp_password_v1`, `slack_bot_token_v1`, `slack_app_token_v1`,
  `pgadmin_password_v1`) usan archivos **sin prefijo** en `.secrets/*.txt` (el prefijo `Dev_` queda
  reservado exclusivamente para el stack dev, ver `deploy/docker-compose.dev.yml`).
- Los servicios propios consumen `/run/secrets/<nombre>` con el helper compartido `get_secret()`
  (`core/config.py`) y mantienen fallback a `.env` solo durante la transición. `pgadmin_password_v1` es la
  excepción: lo consume directamente la imagen `dpage/pgadmin4` vía `PGADMIN_DEFAULT_PASSWORD_FILE` (no
  pasa por `get_secret()`). El servicio `pgadmin` es opcional (`profiles: ["pgadmin"]`), publicado solo en
  `127.0.0.1` para acceso vía túnel SSH, y `PGADMIN_DEFAULT_EMAIL` se lee de la variable `PGADMIN_EMAIL`
  en `.env`/`.env.dev` (no hay variante `_FILE` para el email en esa imagen).
- **Importante**: si `DATABASE_URL` (o `ALEMBIC_URL`) está seteada en `.env`, tiene prioridad sobre el
  secreto `db_password_v1` en `_engine_url()` (`db/session.py`, `core/services/repetitividad.py`) y lo anula
  por completo. Debe quedar comentada (no solo vacía: una variable vacía igual gana sobre el default en
  `os.getenv`) para que el secret realmente se use.
- La rotación se hará sobrescribiendo el archivo `.secrets/<nombre>_v1.txt` (o creando `*_v2` si se requiere
  convivencia temporal) y recreando los contenedores afectados de a uno, verificando health/DB entre cada
  paso antes de continuar (no usar `./Start`, que reinicia todo el stack de un saque).
- Antes de desplegar, validar que no se use `POSTGRES_PASSWORD` en texto plano en `deploy/compose.yml`
  (`scripts/check_no_plaintext_secrets.sh` lo verifica) y que el archivo `.secrets/<nombre>_v1.txt`
  correspondiente exista y tenga el valor correcto.

## Autenticación y sesiones

- La API core protege rutas sensibles con API key interna (`api_key_v1` o `LAS_FOCAS_API_KEY`); sólo `/health` y `/health/version` son públicos.
- El panel web usa sesiones firmadas con `HttpOnly`, `SameSite=Lax`, `max_age` explícito y `Secure` configurable vía `WEB_SESSION_HTTPS_ONLY`.
- La SPA no debe guardar JWT/tokens sensibles en `localStorage` salvo justificación excepcional y documentada.
- El login del panel aplica rate limit en memoria por IP + usuario. En producción multiworker o multiinstancia debe migrarse a Redis u otro backend compartido.
- Las contraseñas nuevas usan SHA-256 de la entrada completa antes de bcrypt y un prefijo versionado; los bcrypt legacy siguen verificando para migración gradual.

## Workflow de revisión safe-by-design

- Alcance recomendado: secretos, dependencias, SAST y hardening de despliegue.
- Superficies prioritarias: `.env`, `deploy/compose.yml`, Dockerfiles, `Keys/`, scripts operativos, autenticación/sesiones y endpoints expuestos.
- Resultado esperado: hallazgos ordenados por severidad con parche o mitigación mínima, sin exponer secretos completos.
- Referencias operativas: `.github/agents/security.agent.md`, `.github/prompts/revisar-seguridad.prompt.md` y `.github/skills/security-scan/`.

## Próximos pasos

- Automatizar escaneo de vulnerabilidades en CI.
- Endurecer headers/CORS en servicios web.
- Revisión periódica de permisos en DB y contenedores.
- Definir controles de validación/sandbox para el microservicio LibreOffice (`office_service`).
- Revisar con prioridad `v-html`, CORS, cookies de sesión, tokens y exposición de endpoints en cualquier feature nuevo.
