# Nombre de archivo: __init__.py
# Ubicación de archivo: core/services/cromo/arbitro/reglas/__init__.py
# Descripción: Catálogo de reglas del árbitro de Cromo, en el orden en que las corre el motor

from __future__ import annotations

from core.services.cromo.arbitro.reglas.odf_por_camino import (
    ReglaContradiccionServicio,
    ReglaOdfPorCamino,
)
from core.services.cromo.arbitro.senales import Regla

REGLAS: tuple[Regla, ...] = (
    ReglaOdfPorCamino(),
    ReglaContradiccionServicio(),
)

__all__ = ["REGLAS"]
