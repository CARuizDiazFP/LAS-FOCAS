# Nombre de archivo: __init__.py
# Ubicación de archivo: core/services/cromo/__init__.py
# Descripción: Exports del paquete de ingesta de inventario de fibra óptica desde Cromo Red

from __future__ import annotations

from core.services.cromo.client import CromoClient, CromoClientError
from core.services.cromo.config import (
    PSIZE_PERMITIDOS,
    CromoConfig,
    CromoConfigError,
    enmascarar,
    get_cromo_config,
)
from core.services.cromo.modelos import Botella, Cable, Fusion, Pelo, Tubo
from core.services.cromo.parser import (
    ArbolBotella,
    ClaseExcluidaError,
    ClaseNoSoportadaError,
    ErrorParseo,
    atributo,
    extraer_tubos_y_pelos,
    parse_arbol_botella,
    parse_botella,
    parse_cable,
    parse_fusion,
    parse_objeto,
    parse_pagina,
    parse_pelo,
    parse_tubo,
    resolver_lat_lon,
)

__all__ = [
    "CromoClient",
    "CromoClientError",
    "CromoConfig",
    "CromoConfigError",
    "PSIZE_PERMITIDOS",
    "enmascarar",
    "get_cromo_config",
    "Botella",
    "Cable",
    "Fusion",
    "Pelo",
    "Tubo",
    "ArbolBotella",
    "ClaseExcluidaError",
    "ClaseNoSoportadaError",
    "ErrorParseo",
    "atributo",
    "extraer_tubos_y_pelos",
    "parse_arbol_botella",
    "parse_botella",
    "parse_cable",
    "parse_fusion",
    "parse_objeto",
    "parse_pagina",
    "parse_pelo",
    "parse_tubo",
    "resolver_lat_lon",
]
