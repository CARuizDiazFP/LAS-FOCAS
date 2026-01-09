# Nombre de archivo: tracking_parser.py
# Ubicación de archivo: core/parsers/tracking_parser.py
# Descripción: Parser de trazas de fibra para extraer empalmes, cables y atenuación desde TXT crudo

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict, field
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Regex para extraer ID de servicio desde nombre de archivo (ej: "FO 111995 C2.txt" -> "111995")
SERVICIO_ID_REGEX = re.compile(r"(?:FO\s*)?(\d{5,})", re.IGNORECASE)

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


@dataclass
class TrackingParseResult:
    """Resultado completo del parsing de un archivo de tracking."""

    servicio_id: Optional[str]
    nombre_archivo: str
    entries: List[TrackingEntry] = field(default_factory=list)
    empalmes_count: int = 0
    tramos_count: int = 0

    def to_dict(self) -> dict:
        """Convierte el resultado a dict para serialización."""

        return {
            "servicio_id": self.servicio_id,
            "nombre_archivo": self.nombre_archivo,
            "entries": [e.to_dict() for e in self.entries],
            "empalmes_count": self.empalmes_count,
            "tramos_count": self.tramos_count,
        }

    def get_empalmes(self) -> List[TrackingEntry]:
        """Retorna solo las entradas de tipo empalme."""

        return [e for e in self.entries if e.tipo == "empalme"]

    def get_topologia(self) -> List[Tuple[str, str]]:
        """Retorna lista de tuplas (empalme_id, descripcion/ubicacion) para los empalmes."""

        return [
            (e.empalme_id, e.empalme_descripcion)
            for e in self.entries
            if e.tipo == "empalme" and e.empalme_id and e.empalme_descripcion
        ]


def extract_servicio_id(filename: str) -> Optional[str]:
    """Extrae el ID del servicio desde el nombre del archivo.

    Args:
        filename: Nombre del archivo (ej: "FO 111995 C2.txt")

    Returns:
        ID del servicio como string (ej: "111995") o None si no se encuentra.

    Ejemplos:
        - "FO 111995 C2.txt" -> "111995"
        - "FO111995.txt" -> "111995"
        - "111995_backup.txt" -> "111995"
        - "tracking_servicio_999999.txt" -> "999999"
    """

    match = SERVICIO_ID_REGEX.search(filename)
    if match:
        return match.group(1)
    return None


def parse_tracking(raw_text: str, filename: str = "") -> TrackingParseResult:
    """Parsea el contenido crudo de un archivo de tracking y devuelve resultado estructurado.

    Args:
        raw_text: Contenido del archivo de tracking.
        filename: Nombre del archivo para extraer el ID del servicio.

    Returns:
        TrackingParseResult con ID de servicio, entradas parseadas y conteos.

    - Detecta líneas de empalme ("Empalme <id>: <descripcion>") y crea nodos de tipo "empalme".
    - Detecta líneas de fibra ("F-XYZ: ... 7.06 dB") y crea tramos con nombre de cable y atenuación.
    - Propaga el último empalme detectado a los tramos siguientes para poder enlazar ruta.
    """

    entries: List[TrackingEntry] = []
    current_empalme_id: Optional[str] = None
    current_empalme_desc: Optional[str] = None

    # Extraer ID del servicio desde el nombre del archivo
    servicio_id = extract_servicio_id(filename) if filename else None

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

    empalmes_count = sum(1 for e in entries if e.tipo == "empalme")
    tramos_count = sum(1 for e in entries if e.tipo == "tramo")

    logger.info(
        "action=parse_tracking filename=%s servicio_id=%s parsed_entries=%d empalmes=%d tramos=%d",
        filename,
        servicio_id,
        len(entries),
        empalmes_count,
        tramos_count,
    )

    return TrackingParseResult(
        servicio_id=servicio_id,
        nombre_archivo=filename,
        entries=entries,
        empalmes_count=empalmes_count,
        tramos_count=tramos_count,
    )


def parse_tracking_as_dicts(raw_text: str, filename: str = "") -> dict:
    """Helper para obtener la salida como diccionario completo."""

    return parse_tracking(raw_text, filename).to_dict()


def parse_tracking_entries(raw_text: str) -> List[TrackingEntry]:
    """Parsea y retorna solo las entradas (compatibilidad hacia atrás)."""

    return parse_tracking(raw_text).entries


def iter_empalmes(entries: Iterable[TrackingEntry]) -> Iterable[TrackingEntry]:
    """Filtra solo nodos de empalme."""

    return (entry for entry in entries if entry.tipo == "empalme")


def iter_tramos(entries: Iterable[TrackingEntry]) -> Iterable[TrackingEntry]:
    """Filtra solo tramos de fibra."""

    return (entry for entry in entries if entry.tipo == "tramo")
