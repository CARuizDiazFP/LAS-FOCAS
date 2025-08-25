# Nombre de archivo: web.md
# Ubicación de archivo: docs/web.md
# Descripción: Plan del panel web con autenticación básica

## Objetivo

Proveer una interfaz web interna para ejecutar tareas y visualizar informes generados por la API.

## Stack propuesto

- **FastAPI** con plantillas Jinja2 para renderizado de páginas.
- Servidor **Uvicorn** detrás de un proxy inverso opcional.
- Consumo de la API interna mediante llamadas HTTP.

## Rutas iniciales

- `GET /` → redirige a `/login` si no hay sesión.
- `GET /login` → muestra formulario de acceso.
- `POST /login` → valida credenciales y crea cookie de sesión.
- `GET /dashboard` → menú principal con enlaces a informes y acciones.

## Servicio base implementado

El repositorio incluye un microservicio en `web/main.py` que utiliza **FastAPI** con plantillas **Jinja2** y un componente **React** mínimo. Las rutas básicas son:

- `GET /` renderiza `index.html` mostrando el rol del usuario.
- `GET /health` responde con `{"status": "ok"}` para verificaciones de salud.
- `GET /admin` accesible solo para usuarios con rol `admin`.
- `GET /login` entrega un formulario de acceso aún en desarrollo.
- `GET /metrics` expone métricas simples sin autenticación.

Este servicio se construye con `web/Dockerfile` sobre la imagen `python:3.11-slim` y se despliega mediante `deploy/compose.yml` como servicio `web`, exponiendo el puerto `8080` solo a la red interna. Para publicar externamente se requiere un proxy inverso.

## Logging

El servicio inicializa el log mediante `configure_logging("web")`, lo que emite registros en formato JSON con campos `action`, `request_id` y demás metadatos. Además, se inyecta `RequestIDMiddleware` para generar el encabezado `X-Request-ID` en cada respuesta.

## Autenticación

- Credenciales diferenciadas por rol:
  - `WEB_ADMIN_USERNAME` / `WEB_ADMIN_PASSWORD`.
  - `WEB_LECTOR_USERNAME` / `WEB_LECTOR_PASSWORD`.
- Si no se envían credenciales o el encabezado es inválido, el servicio redirige a `/login`.
- Solo cuando las credenciales son erróneas se devuelve 401 con `WWW-Authenticate`.
- Las rutas pueden restringirse según el rol detectado.
- Futuro: integrar SSO interno.

## Tareas pendientes

- Ajustar diseño mínimo responsivo.
- Integrar generación y descarga de informes.
