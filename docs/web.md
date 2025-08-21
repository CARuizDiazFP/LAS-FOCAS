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

## Servicio base implementado

El repositorio incluye un microservicio inicial en `web/main.py` que utiliza **FastAPI** y expone dos rutas básicas:

- `GET /` devuelve un mensaje de bienvenida.
- `GET /health` responde con `{"status": "ok"}` para verificaciones de salud.

Este servicio se construye con `web/Dockerfile` sobre la imagen `python:3.11-slim` y se despliega mediante `deploy/compose.yml` como servicio `web`, publicando el puerto `8080` al host.

## Autenticación

- Credenciales básicas definidas en variables de entorno (`WEB_USER`, `WEB_PASS`).
- Cookies firmadas para mantener la sesión activa.
- Futuro: integrar SSO interno y gestión de roles.

## Tareas pendientes

- Definir diseño mínimo responsivo.
- Incorporar permisos por rol cuando se amplíe el sistema.
- Integrar generación y descarga de informes.
