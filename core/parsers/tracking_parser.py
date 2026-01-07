# Nombre de archivo: tracking_parser.py
# Ubicación de archivo: core/parsers/tracking_parser.py
# Descripción: Parser de trazas de fibra para extraer empalmes, cables y atenuación desde TXT crudo

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)

EMPALME_REGEX = re.compile(r"^Empalme\s+(?P<id>\d+):\s*(?P<descripcion>.+)$", re.IGNORECASE)
FIBRA_REGEX = re.compile(
    r"^(?P<cable>[A-Z0-9\-]+):.*?(?P<atenuacion>\d+(?:\.\d+)?)\s*dB\s*$",
    re.IGNORECASE,
)


@dataclass
class TrackingEntry:
    """Segmento del tracking óptico en orden de aparición."""

    tipo: str  # "empalme" | "tramo"
    empalme_id: Optional[str]
    empalme_descripcion: Optional[str]
    cable_nombre: Optional[str]
    atenuacion_db: Optional[float]
    raw_line: str
    index: int

    def to_dict(self) -> dict:
        """Convierte la entrada a dict plano para persistencia o serialización."""

        return asdict(self)


def parse_tracking(raw_text: str) -> List[TrackingEntry]:
    """Parsea el contenido crudo de un archivo de tracking y devuelve segmentos ordenados.

    - Detecta líneas de empalme ("Empalme <id>: <descripcion>") y crea nodos de tipo "empalme".
    - Detecta líneas de fibra ("F-XYZ: ... 7.06 dB") y crea tramos con nombre de cable y atenuación.
    - Propaga el último empalme detectado a los tramos siguientes para poder enlazar ruta.
    """

    entries: List[TrackingEntry] = []
    current_empalme_id: Optional[str] = None
    current_empalme_desc: Optional[str] = None

    for idx, line in enumerate(raw_text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue

        empalme_match = EMPALME_REGEX.match(stripped)
        if empalme_match:
            current_empalme_id = empalme_match.group("id")
            current_empalme_desc = empalme_match.group("descripcion").strip()
            entries.append(
                TrackingEntry(
                    tipo="empalme",
                    empalme_id=current_empalme_id,
                    empalme_descripcion=current_empalme_desc,
                    cable_nombre=None,
                    atenuacion_db=None,
                    raw_line=stripped,
                    index=idx,
                )
            )
            continue

        fibra_match = FIBRA_REGEX.match(stripped)
        if fibra_match:
            try:
                atenuacion = float(fibra_match.group("atenuacion"))
            except ValueError:
                atenuacion = None
                logger.warning("action=parse_tracking parse_attenuation_failed line=%s", stripped)

            entries.append(
                TrackingEntry(
                    tipo="tramo",
                    empalme_id=current_empalme_id,
                    empalme_descripcion=current_empalme_desc,
                    cable_nombre=fibra_match.group("cable"),
                    atenuacion_db=atenuacion,
                    raw_line=stripped,
                    index=idx,
                )
            )
            continue

        logger.debug("action=parse_tracking skip_unmatched line=%s", stripped)

    logger.info(
        "action=parse_tracking parsed_entries=%d empalmes=%d tramos=%d",
        len(entries),
        sum(1 for e in entries if e.tipo == "empalme"),
        sum(1 for e in entries if e.tipo == "tramo"),
    )
    return entries


def parse_tracking_as_dicts(raw_text: str) -> List[dict]:
    """Helper para obtener la salida como lista de diccionarios."""

    return [entry.to_dict() for entry in parse_tracking(raw_text)]


def iter_empalmes(entries: Iterable[TrackingEntry]) -> Iterable[TrackingEntry]:
    """Filtra solo nodos de empalme."""

    return (entry for entry in entries if entry.tipo == "empalme")


def iter_tramos(entries: Iterable[TrackingEntry]) -> Iterable[TrackingEntry]:
    """Filtra solo tramos de fibra."""

    return (entry for entry in entries if entry.tipo == "tramo")
