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


def _a_entero(valor: str | None) -> int | None:
    if valor is None:
        return None
    texto = valor.strip()
    if not texto:
        return None
    try:
        return int(texto)
    except ValueError:
        return None


@dataclass(slots=True)
class IdentidadConsolidada:
    servicio_id: str
    numero_linea: str
    alias_ids: list[str]


def consolidar_identidad_servicio(
    *,
    numero_primer_servicio: str,
    numero_linea_excel: str | None,
    linea_upgrade_de: str | None,
    linea_upgrade_a: str | None,
    servicio_id_actual: str | None,
    numero_linea_actual: str | None,
    alias_ids_actual: list[str] | None,
) -> IdentidadConsolidada:
    candidatos_str = {
        valor
        for valor in (
            numero_primer_servicio,
            numero_linea_excel,
            linea_upgrade_de,
            linea_upgrade_a,
            numero_linea_actual,
            servicio_id_actual,
            *(alias_ids_actual or []),
        )
        if valor and valor != "-"
    }

    candidatos_numericos = [
        (str(entero), entero) for valor in candidatos_str if (entero := _a_entero(valor)) is not None
    ]

    id_final = (
        max(candidatos_numericos, key=lambda par: par[1])[0]
        if candidatos_numericos
        else numero_primer_servicio
    )

    servicio_id_es_numerico_o_vacio = servicio_id_actual is None or _a_entero(servicio_id_actual) is not None
    servicio_id_final = id_final if servicio_id_es_numerico_o_vacio else servicio_id_actual

    alias_existentes = [
        valor for valor in (alias_ids_actual or [])
        if valor and valor != "-" and valor not in (id_final, servicio_id_final)
    ]

    id_final_entero = _a_entero(id_final)
    servicio_id_final_entero = _a_entero(servicio_id_final)

    alias_nuevos = sorted(
        (
            valor
            for valor in candidatos_str
            if valor not in alias_existentes
            and _a_entero(valor) not in (id_final_entero, servicio_id_final_entero)
        ),
        key=lambda valor: (_a_entero(valor) is None, _a_entero(valor) or 0, valor),
    )

    return IdentidadConsolidada(
        servicio_id=servicio_id_final,
        numero_linea=id_final,
        alias_ids=[*alias_existentes, *alias_nuevos],
    )
