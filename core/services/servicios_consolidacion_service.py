# Nombre de archivo: servicios_consolidacion_service.py
# Ubicación de archivo: core/services/servicios_consolidacion_service.py
# Descripción: Cálculo del ID final de una familia de Servicio (cadena de upgrades SLA) y de si un tipo de servicio es verificable

"""Consolida la identidad de un `Servicio` a partir de los IDs conocidos de su familia (columna
`Número Primer Servicio` del Excel SLA como ancla estable, más `Número Línea`/`Línea Upgrade
(De)`/`Línea Upgrade (A)` de cada ingesta). Regla de negocio confirmada con el usuario: el ID más
alto (numéricamente) es siempre el ID de línea vigente — no hace falta perseguir los punteros
`Es Upgrade de/a`, sólo tomar el máximo de todos los IDs numéricos conocidos.

`servicio_id` (el campo que ya leen el bot de Slack y la UI de cables) sólo se sobreescribe si su
valor actual es numérico o no existía todavía — si el módulo de tracking físico
(`core/services/infra_service.py::execute_upgrade`) ya lo dejó en un ID no numérico (ej. "O1C1"),
esa fila queda fuera de la autoridad de esta consolidación; el nuevo ID conocido de todas formas se
agrega a `alias_ids` para que el matching de Cromo lo resuelva igual.
"""

from __future__ import annotations

from dataclasses import dataclass

TIPOS_SERVICIO_VERIFICABLES = frozenset({"INT", "RPV", "ISI", "ISIS", "TLS", "EWS"})


def es_verificable_por_tipo(tipo_servicio: str | None) -> bool:
    if not tipo_servicio:
        return False
    return tipo_servicio.strip().upper() in TIPOS_SERVICIO_VERIFICABLES
