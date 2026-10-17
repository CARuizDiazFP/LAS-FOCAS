# Nombre de archivo: config.py
# Ubicación de archivo: modules/fo_monitor_worker/config.py
# Descripción: Constantes del worker de FO Monitor (puerto de health, intervalo de tick, clave del advisory lock)

from __future__ import annotations

NOMBRE_SERVICIO = "fo_monitor"
HEALTH_PORT = 8098
TICK_SECONDS = 10
# pg_advisory_lock global: garantiza una sola instancia activa del motor aunque se levanten dos
# contenedores (p. ej. un `docker compose up` accidental con otro project name).
ADVISORY_LOCK_KEY = 0x464F4D4F4E  # "FOMON"
