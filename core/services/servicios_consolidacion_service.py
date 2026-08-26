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

Invariante de representación: cada ID entra a la consolidación por `_forma_canonica()` y de ahí en
adelante se trabaja SÓLO con esa forma. Un ID numérico se representa siempre como `str(int(valor))`
("093", " 93 " y "93" son el mismo ID de línea y colapsan a "93"); uno no numérico ("O1C1") se
compara por igualdad exacta de string. Por eso ni `numero_linea`/`servicio_id` ni `alias_ids` pueden
contener dos strings distintos que representen el mismo entero.
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


def _es_valor_util(valor: str | None) -> bool:
    """Descarta celdas vacías del Excel SLA: `None`, string vacío y el guión de "sin dato"."""
    return bool(valor) and valor != "-"


def _forma_canonica(valor: str) -> str:
    """Representación ÚNICA de un ID, para que "mismo ID" sea exactamente "mismo string".

    - Numérico → `str(int(valor))`: sin ceros a la izquierda ni espacios ("093" → "93").
    - No numérico (ej. "O1C1", ID de tracking físico) → el string tal cual: no hay canonicalización
      posible y sólo se lo puede comparar por igualdad exacta contra otro no numérico.

    Canonicalizar una sola vez al entrar (y no comparar "de a pares" más abajo) es lo que hace
    estructuralmente imposible que dos formas del mismo entero coexistan en el resultado. Además
    elimina de raíz la colisión `None == None`: cada valor no numérico conserva su propio string
    como clave de identidad, en vez de compartir un sentinel `None` con los demás no numéricos.
    """
    entero = _a_entero(valor)
    return str(entero) if entero is not None else valor


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
    # Canonicalización única y temprana: de acá para abajo NO se vuelve a mirar el string crudo del
    # Excel/DB, sólo su forma canónica. Como el set deduplica por esa forma, dos columnas con el
    # mismo ID escrito distinto ("0300" y "300") entran una sola vez.
    candidatos = {
        _forma_canonica(valor)
        for valor in (
            numero_primer_servicio,
            numero_linea_excel,
            linea_upgrade_de,
            linea_upgrade_a,
            numero_linea_actual,
            servicio_id_actual,
            *(alias_ids_actual or []),
        )
        if _es_valor_util(valor)
    }

    enteros_candidatos = [
        entero for valor in candidatos if (entero := _a_entero(valor)) is not None
    ]

    # El ID numérico más alto es el vigente. `str(max(...))` ya es la forma canónica, y `max` sobre
    # enteros es determinístico (el set no puede tener dos formas del mismo entero).
    id_final = (
        str(max(enteros_candidatos))
        if enteros_candidatos
        else _forma_canonica(numero_primer_servicio)
    )

    servicio_id_es_numerico_o_vacio = servicio_id_actual is None or _a_entero(servicio_id_actual) is not None
    servicio_id_final = id_final if servicio_id_es_numerico_o_vacio else _forma_canonica(servicio_id_actual)

    # Ambos ya son canónicos, así que un simple `in` alcanza para excluirlos de los alias: compara
    # por valor entero cuando son numéricos y por string exacto cuando no lo son.
    ids_vigentes = (id_final, servicio_id_final)

    # `alias_existentes` conserva el orden histórico de `alias_ids_actual`. Desempate cuando dos
    # entradas representan el mismo entero ("093" y "93"): gana siempre la forma canónica, con lo
    # cual el resultado no depende de cuál venía primero ni del orden de iteración de `candidatos`.
    alias_existentes: list[str] = []
    for valor in alias_ids_actual or []:
        if not _es_valor_util(valor):
            continue
        canonico = _forma_canonica(valor)
        if canonico in ids_vigentes or canonico in alias_existentes:
            continue
        alias_existentes.append(canonico)

    alias_nuevos = sorted(
        (
            valor
            for valor in candidatos
            if valor not in ids_vigentes and valor not in alias_existentes
        ),
        key=lambda valor: (_a_entero(valor) is None, _a_entero(valor) or 0, valor),
    )

    return IdentidadConsolidada(
        servicio_id=servicio_id_final,
        numero_linea=id_final,
        alias_ids=[*alias_existentes, *alias_nuevos],
    )
