# Nombre de archivo: web.md
# Ubicación de archivo: docs/web.md
# Descripción: Plan del panel web con autenticación básica

## Objetivo

Proveer una interfaz web interna para ejecutar tareas y visualizar informes generados por la API.

## Stack propuesto

- **FastAPI** con plantillas Jinja2 para renderizado de páginas.
- Servidor **Uvicorn** detrás de un proxy opcional.
- Consumo de la API interna mediante llamadas HTTP.

## Rutas iniciales

- `GET /` → redirige a `/login` si no hay sesión.
- `GET /login` → muestra formulario de acceso.
- `POST /login` → valida credenciales y crea cookie de sesión.
- `GET /dashboard` → menú principal con enlaces a informes y acciones.

## Autenticación

- Credenciales básicas definidas en variables de entorno (`WEB_USER`, `WEB_PASS`).
- Cookies firmadas para mantener la sesión activa.
- Futuro: integrar SSO interno y gestión de roles.

## Tareas pendientes

- Definir diseño mínimo responsivo.
- Incorporar permisos por rol cuando se amplíe el sistema.
- Integrar generación y descarga de informes.
