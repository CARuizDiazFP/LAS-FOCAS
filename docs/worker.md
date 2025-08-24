# Nombre de archivo: worker.md
# Ubicación de archivo: docs/worker.md
# Descripción: Responsabilidades del servicio worker

El servicio **worker** procesa en segundo plano las tareas encoladas por la API utilizando Redis y RQ, evitando bloquear los servicios interactivos.

## Responsabilidades principales
- Consumir trabajos de la cola y ejecutar los generadores de informes (Repetitividad y SLA).
- Manejar reintentos y tiempos máximos registrando logs estructurados.
- Guardar los archivos producidos y notificar resultados a la API o al bot cuando corresponde.

## Configuración básica
- `REDIS_URL`: ubicación de la instancia de Redis utilizada como cola.
- `WORKER_CONCURRENCY`: cantidad de procesos simultáneos para ejecutar trabajos.

El módulo se inicia desde `modules/worker.py` y puede ejecutarse como servicio independiente.
