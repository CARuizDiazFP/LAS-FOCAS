# Nombre de archivo: soporte_slack_ingreso.py
# Ubicación de archivo: tests/soporte_slack_ingreso.py
# Descripción: Helpers compartidos por los tests del listener de ingresos de Slack (test_slack_ingreso_*.py)

from __future__ import annotations

from typing import Any

from core.services.cromo.camara_botella_busqueda import ResultadoBusquedaExtendida


def _resultado_camara(camara: Any, nombre_norm: str = "") -> ResultadoBusquedaExtendida:
    """Wrapper de test: arma un `ResultadoBusquedaExtendida` con `fuente='camara'` si hay match, o
    sin match (`fuente=None`, `camara=None`) si no — evita repetir los 4 campos del dataclass en
    cada mock de `buscar_camara_o_botella_cromo` (Tarea 2, reemplaza `buscar_camara` directo en
    `_construir_respuesta_camara`). No cubre el caso `fuente="cromo_botella"` porque ningún test de
    este archivo necesita distinguirlo — sólo le importa a `_construir_respuesta_camara` si
    `resultado.camara` es `None` o no."""
    return ResultadoBusquedaExtendida(
        camara=camara, nombre_norm=nombre_norm, fuente="camara" if camara is not None else None, botella=None
    )
