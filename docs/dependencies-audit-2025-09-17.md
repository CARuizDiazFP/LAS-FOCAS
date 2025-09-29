# Auditoría de dependencias (Python) — 2025-09-17

Este reporte resume el estado de dependencias Python por servicio, cambios aplicados hoy y recomendaciones de seguridad/mantenimiento.

## Alcance

- Servicios analizados: raíz (herramientas/tests), `api/`, `web/`, `nlp_intent/`, `bot_telegram/`, y módulos `modules/` (informes SLA y Repetitividad).
- Node/Frontend queda fuera de alcance por ahora (pendiente revisarlo en otro pase).

## Uso real vs. requirements

- Importaciones detectadas en el workspace: fastapi, starlette, httpx, sqlalchemy, psycopg, passlib[bcrypt], jinja2, orjson, pydantic, pandas, openpyxl, python-docx.
- `modules/` usa: pandas, pydantic (modelos), python-docx (generación .docx) y `modules/common/libreoffice_export.py` para convertir a PDF con LibreOffice.
- `bot_telegram/` usa: aiogram, pandas, openpyxl, python-docx (alineado con su requirements).

## Cambios aplicados

- Añadidos a `web/requirements.txt`:
  - pydantic==2.9.2
  - pandas==2.2.2
  - openpyxl==3.1.2
  - python-docx==0.8.11

- Añadidos a `requirements.txt` (raíz) para facilitar ejecuciones/tests fuera de Docker:
  - pydantic==2.9.2
  - pandas==2.2.2
  - openpyxl==3.1.2
  - python-docx==0.8.11

- Instalados en el venv actual: pydantic, pandas, openpyxl, python-docx.

## Observaciones y riesgos

- Divergencia de versiones entre servicios:
  - FastAPI: raíz 0.110.1, web 0.111.0, api 0.112.2, nlp_intent 0.110.1.
  - Uvicorn: raíz 0.29.x, web 0.30.1, api 0.30.6, nlp_intent 0.29.x.
  - Pydantic: raíz 2.9.2, nlp_intent 2.6.3.
  - orjson: raíz/web 3.10.3–3.10.6.
  Recomendación: homogeneizar versiones para evitar incompatibilidades sutiles (Starlette subyacente, tipos de Request/Response, etc.).

- Pruebas: ejecutar TODA la suite (`pytest` en la raíz) puede producir colisiones de importación entre `api/app` y `web/app` (ambos paquetes se llaman `app`).
  - Efecto observado: cuando primero se importa `api/app/main.py`, luego los tests de `web` que hacen `from app.main import app` reciben el módulo de la API, produciendo fallos (p. ej., `app.main` sin `psycopg`).
  - Mitigaciones sugeridas:
    - A corto plazo: ejecutar tests por servicio (como ya hace CI) o forzar `sys.path.insert(0, ...)` en los tests para asegurar prioridad, evitando `append`.
    - A mediano plazo: renombrar uno de los paquetes (`api_app`, `web_app`) o usar layouts tipo `src/` para aislar imports.

- Warnings:
  - passlib: DeprecationWarning sobre `crypt` (removido en Python 3.13). Seguimiento recomendado antes de migrar a 3.13.
  - pandas: FutureWarning por encadenamiento `inplace` en `modules/informes_sla/processor.py`. No crítico, pero conviene ajustar en una refactor.

- Contenido en requirements:
  - `pytest` figura en algunos requirements de runtime (raíz y `nlp_intent`). Recomendado mover a un `requirements-dev.txt`/extras para no arrastrarlo a producción.

## Próximos pasos recomendados

1. Unificar versiones mayores por servicio (FastAPI, Uvicorn, Pydantic, orjson) y fijar Starlette si es necesario, probando compatibilidad.
2. Separar dependencias de desarrollo (`pytest`, herramientas de lint/format) en archivos dev o extras.
3. Eliminar el conflicto de paquete `app` entre `api/` y `web/` (renombre o `src/` layout) para permitir `pytest` integral sin hacks.
4. Añadir `constraints.txt` opcional para bloquear transitive deps críticas.
5. Revisar Node/Frontend en un pase separado (npm audit, dependabot/renovate).

## Validación

- Tests de `web`: 10/10 PASAN localmente tras instalar dependencias nuevas. Persisten solo warnings no críticos.
- Ejecución de toda la suite en la raíz puede fallar por el conflicto de módulos descrito (no es una regresión de este cambio, ya existía como riesgo latente).
