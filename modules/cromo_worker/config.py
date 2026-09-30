# Nombre de archivo: config.py
# Ubicación de archivo: modules/cromo_worker/config.py
# Descripción: Constantes y defaults del worker dedicado de ingesta Cromo Red

from __future__ import annotations

NOMBRE_SERVICIO = "cromo_ingesta"
USUARIO_SCHEDULER = "cromo_scheduler"
INTERVALO_HORAS_DEFAULT = 24
HEALTH_PORT = 8096
JOB_ID = "cromo_ingesta_job"
# Barrido semanal `/inner` de pelos (at.62/at.63): fila id=2 de `cromo_ingesta_config`, sembrada
# deshabilitada por la migración 20260930_01. El inicial se corre a mano con
# `scripts/cromo_barrido_pelos_inner.py`.
JOB_ID_PELOS_INNER = "cromo_pelos_inner_job"
CONFIG_ID_PELOS_INNER = 2
