# Nombre de archivo: pelo_servicios.py
# Ubicación de archivo: core/services/cromo/pelo_servicios.py
# Descripción: Regla pura de prioridad de fuentes para decidir qué servicio(s) ocupa cada pelo de un cable

"""Qué número de servicio corresponde a cada pelo de un cable, sin red ni base de datos.

Orden de fuentes definido por el usuario (2026-09-30). La verdad real es el camino óptico entre ODFs,
pero el costo operativo actual no permite inventariarlo, así que se usan los atributos de Cromo:

1. **Descripción del pelo** (`at.61`), parseada por `parser.parsear_servicio`: normalmente la más
   actualizada → `REGEX_EXACTO`, igual que la fase de servicios de siempre.
2. **`at.62` del conector de ODF** al que está conectado el pelo → `ATRIBUTO_CONECTOR_ODF`.
3. **`at.62` del propio pelo** (sólo viaja en `/inner` del cable) → `ATRIBUTO_PELO`. Es la fuente
   menos confiable: cuando un pelo se daña y el servicio migra a otro pelo del mismo cable, Cromo suele
   dejar el `at.62` viejo. Caso real F-PE-AL-99: el pelo 4 ("ATENUADO 2 DB…") conserva 116548, que hoy
   vive en el pelo 1. Por eso se descarta si el número ya quedó ubicado en otro pelo del cable por las
   fuentes 1-2.

Las fuentes 2 y 3 nunca se aplican a un pelo fuera de uso: `at.63` Dañado/Libre, o descripción que lo
dice (cortado, dañado, atenuado, libre, reserva). El ID de línea vigente lo resuelve después PROV
(`_SQL_BUSCAR_SERVICIO` con alias), no esta regla.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from core.services.cromo.parser import parsear_servicio

METODO_REGEX = "REGEX_EXACTO"
METODO_ATRIBUTO_CONECTOR = "ATRIBUTO_CONECTOR_ODF"
METODO_ATRIBUTO_PELO = "ATRIBUTO_PELO"
METODO_MANUAL = "MANUAL"
# Métodos que la conciliación puede crear y retirar. `MANUAL` (y cualquier otro) nunca se toca.
METODOS_AUTOMATICOS = frozenset({METODO_REGEX, METODO_ATRIBUTO_CONECTOR, METODO_ATRIBUTO_PELO})

# Sobre el texto sin tildes y en mayúsculas: "Dañado" y "DANADO" caen igual.
_REGEX_FUERA_DE_USO = re.compile(r"DANAD|CORTAD|ATENUAD|\bLIBRE\b|RESERVA")
_ESTADOS_SIN_SERVICIO = frozenset({"DANADO", "LIBRE"})
_REGEX_NUMERO = re.compile(r"^\d+$")


@dataclass(frozen=True, slots=True)
class PeloAtributos:
    n_id: int
    servicio_raw: Optional[str]  # at.61
    servicio_atributo: Optional[str]  # at.62
    estado_cromo: Optional[str]  # at.63


def _normalizar(texto: Optional[str]) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return sin_tildes.upper().strip()


def _numero_de_atributo(valor: Optional[str]) -> Optional[str]:
    limpio = (valor or "").strip()
    if not _REGEX_NUMERO.match(limpio) or int(limpio) == 0:
        return None
    return limpio


def pelo_fuera_de_uso(pelo: PeloAtributos) -> bool:
    if _normalizar(pelo.estado_cromo) in _ESTADOS_SIN_SERVICIO:
        return True
    return bool(_REGEX_FUERA_DE_USO.search(_normalizar(pelo.servicio_raw)))


def resolver_servicios_de_cable(
    pelos: Iterable[PeloAtributos], conector_at62_por_pelo: Mapping[int, Optional[str]]
) -> dict[int, list[tuple[str, str]]]:
    """`{pelo_n_id: [(numero, metodo), ...]}` para todos los pelos del cable (lista vacía = ninguno).

    Se resuelve por cable entero, no pelo por pelo: el descarte del `at.62` del pelo depende de qué
    números ya ubicaron las fuentes más confiables en los OTROS pelos del mismo cable.
    """
    pelos = list(pelos)
    resultado: dict[int, list[tuple[str, str]]] = {}
    ubicados: set[str] = set()
    pendientes_at62: list[PeloAtributos] = []

    for pelo in pelos:
        numero_texto, _ = parsear_servicio(pelo.servicio_raw)
        if numero_texto:
            resultado[pelo.n_id] = [(numero_texto, METODO_REGEX)]
            ubicados.add(numero_texto)
            continue
        if pelo_fuera_de_uso(pelo):
            resultado[pelo.n_id] = []
            continue
        numero_conector = _numero_de_atributo(conector_at62_por_pelo.get(pelo.n_id))
        if numero_conector:
            resultado[pelo.n_id] = [(numero_conector, METODO_ATRIBUTO_CONECTOR)]
            ubicados.add(numero_conector)
            continue
        pendientes_at62.append(pelo)

    for pelo in pendientes_at62:
        numero_pelo = _numero_de_atributo(pelo.servicio_atributo)
        if numero_pelo and numero_pelo not in ubicados:
            resultado[pelo.n_id] = [(numero_pelo, METODO_ATRIBUTO_PELO)]
        else:
            resultado[pelo.n_id] = []
    return resultado
