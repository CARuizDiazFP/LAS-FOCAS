# Nombre de archivo: vlan_comparator.py
# Ubicación de archivo: web/tools/vlan_comparator.py
# Descripción: Utilidades para parsear configuraciones Cisco y comparar VLANs permitidas

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Set

MIN_VLAN_ID = 1
MAX_VLAN_ID = 4094

_VLAN_CMD_PATTERN = re.compile(
    r"switchport\s+trunk\s+allowed\s+vlan(?:\s+add)?\s+(?P<values>[0-9,\-\s]+)",
    re.IGNORECASE,
)
_TOKEN_PATTERN = re.compile(r"\d+(?:\s*-\s*\d+)?")


@dataclass(frozen=True, slots=True)
class VLANComparison:
    """Resultado de comparar dos conjuntos de VLANs."""

    vlans_a: List[int]
    vlans_b: List[int]
    only_a: List[int]
    only_b: List[int]
    common: List[int]


def parse_cisco_vlans(config_text: str) -> Set[int]:
    """Extrae todas las VLANs permitidas en configuraciones Cisco IOS.

    Se buscan líneas con `switchport trunk allowed vlan` (con o sin `add`),
    se expanden rangos (ej: ``1-3``) y se devuelven IDs únicos y ordenados.
    """

    vlans: Set[int] = set()
    if not config_text:
        return vlans

    for match in _VLAN_CMD_PATTERN.finditer(config_text):
        values = match.group("values") or ""
        for token in _TOKEN_PATTERN.findall(values):
            clean = token.replace(" ", "")
            if not clean:
                continue
            if "-" in clean:
                start_str, end_str = clean.split("-", 1)
                _add_range(vlans, start_str, end_str)
            else:
                _add_single(vlans, clean)
    return vlans


def compare_vlan_sets(vlan_a: Set[int], vlan_b: Set[int]) -> VLANComparison:
    """Devuelve diferencias y coincidencias entre dos conjuntos de VLANs."""

    sorted_a = sorted(vlan_a)
    sorted_b = sorted(vlan_b)
    only_a = sorted(vlan_a - vlan_b)
    only_b = sorted(vlan_b - vlan_a)
    common = sorted(vlan_a & vlan_b)
    return VLANComparison(sorted_a, sorted_b, only_a, only_b, common)


def _add_single(target: Set[int], value: str) -> None:
    try:
        vlan_id = int(value)
    except ValueError:
        return
    if MIN_VLAN_ID <= vlan_id <= MAX_VLAN_ID:
        target.add(vlan_id)


def _add_range(target: Set[int], start: str, end: str) -> None:
    try:
        start_id = int(start)
        end_id = int(end)
    except ValueError:
        return
    if start_id > end_id:
        start_id, end_id = end_id, start_id
    start_id = max(MIN_VLAN_ID, start_id)
    end_id = min(MAX_VLAN_ID, end_id)
    if start_id > end_id:
        return
    target.update(range(start_id, end_id + 1))


__all__ = ["parse_cisco_vlans", "compare_vlan_sets", "VLANComparison"]
