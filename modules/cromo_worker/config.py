# Nombre de archivo: config.py
# Ubicación de archivo: modules/cromo_worker/config.py
# Descripción: Constantes y defaults del worker dedicado de ingesta Cromo Red

from __future__ import annotations

NOMBRE_SERVICIO = "cromo_ingesta"
USUARIO_SCHEDULER = "cromo_scheduler"
INTERVALO_HORAS_DEFAULT = 24
HEALTH_PORT = 8096
JOB_ID = "cromo_ingesta_job"
