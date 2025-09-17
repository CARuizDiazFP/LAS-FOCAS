# Nombre de archivo: README.md
# Ubicación de archivo: web/README.md
# Descripción: Uso rápido del servicio Web (UI)

# Web (UI) — Uso rápido

## Desarrollo local (opción rápida con uvicorn)

1. Crear entorno e instalar dependencias (ver `requirements.txt`).
2. Ejecutar:

```
uvicorn app.main:app --reload --port 8080
```

Abrir `http://127.0.0.1:8080`.

## Docker/Compose

Se levanta con el stack general del proyecto:

- Servicio `web` en `8080:8080`.
- `api` en `8001:8000` (para evitar conflicto con 8000 de la VM).
- `ollama` expuesto en `11434` y `nlp_intent` apuntando a `http://ollama:11434`.
