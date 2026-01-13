# Nombre de archivo: tracking_parser.py
# Ubicación de archivo: core/parsers/tracking_parser.py
# Descripción: Parser de trazas de fibra para extraer empalmes, cables, puntas A/B y detectar tránsitos

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict, field
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Regex para extraer ID de servicio desde nombre de archivo (ej: "FO 111995 C2.txt" -> "111995")
# Soporta IDs de 4 o más dígitos (ej: "3601", "91710")
SERVICIO_ID_REGEX = re.compile(r"(?:FO\s*)?(\d{4,})", re.IGNORECASE)

# Regex para extraer alias del servicio
# Soporta: "52547 O1C1.txt" -> "O1C1", "91710 C1.txt" -> "C1", "3601 C2.txt" -> "C2"
ALIAS_REGEX = re.compile(r"(\d{4,})\s+([A-Z]\d+(?:[A-Z]\d+)?)", re.IGNORECASE)

EMPALME_REGEX = re.compile(r"^Empalme\s+(?P<id>\d+):\s*(?P<descripcion>.+)$", re.IGNORECASE)
FIBRA_REGEX = re.compile(
    r"^(?P<cable>[A-Z0-9\-]+):.*?(?P<atenuacion>\d+(?:\.\d+)?)\s*dB\s*$",
    re.IGNORECASE,
)

# Regex para detectar línea de Punta A o B (inicio con "Punta A:" o "Punta B:")
PUNTA_REGEX = re.compile(r"^Punta\s+(?P<tipo>[AB]):\s*(?P<descripcion>.+)$", re.IGNORECASE)

# Regex para extraer pelo-conector (ej: P09-C10, P-09/C-10, Pelo 9 Conector 10)
PELO_CONECTOR_REGEX = re.compile(
    r"(?:P(?:elo)?[\s\-]?0*(?P<pelo>\d+))[\s\-\/]*(?:C(?:onector)?[\s\-]?0*(?P<conector>\d+))",
    re.IGNORECASE,
)

# Palabras clave que identifican puntos de tránsito (equipos de distribución)
TRANSITO_KEYWORDS = frozenset(["ODF", "NODO", "RACK", "BANDEJA", "DISTRIBUIDOR", "DDF"])

# Regex para detectar cantidad de pelos/hilos (ej: "2 Pelos")
PELOS_COUNT_REGEX = re.compile(r"(\d+)\s*Pelos?", re.IGNORECASE)


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
    es_transito: bool = False  # True si contiene keywords de tránsito (ODF/NODO/RACK)

    def to_dict(self) -> dict:
        """Convierte la entrada a dict plano para persistencia o serialización."""

        return asdict(self)


@dataclass
class PuntaTerminal:
    """Punto terminal de la ruta (Punta A o Punta B)."""

    tipo: str  # "A" | "B"
    sitio_descripcion: Optional[str]  # ODF MAIPU 316 1
    identificador_fisico: Optional[str]  # RACK 1 BANDEJA 2
    pelo_conector: Optional[str]  # P09-C10
    raw_line: str

    def to_dict(self) -> dict:
        """Convierte a dict para serialización."""
        return asdict(self)


@dataclass
class TrackingParseResult:
    """Resultado completo del parsing de un archivo de tracking."""

    servicio_id: Optional[str]
    alias_id: Optional[str]  # Alias del servicio (ej: O1C1)
    nombre_archivo: str
    entries: List[TrackingEntry] = field(default_factory=list)
    empalmes_count: int = 0
    tramos_count: int = 0
    transitos_count: int = 0  # Cantidad de empalmes que son tránsitos
    cantidad_pelos: Optional[int] = None  # Cantidad de pelos/hilos del servicio
    punta_a: Optional[PuntaTerminal] = None
    punta_b: Optional[PuntaTerminal] = None

    def to_dict(self) -> dict:
        """Convierte el resultado a dict para serialización."""

        return {
            "servicio_id": self.servicio_id,
            "alias_id": self.alias_id,
            "nombre_archivo": self.nombre_archivo,
            "entries": [e.to_dict() for e in self.entries],
            "empalmes_count": self.empalmes_count,
            "tramos_count": self.tramos_count,
            "transitos_count": self.transitos_count,
            "cantidad_pelos": self.cantidad_pelos,
            "punta_a": self.punta_a.to_dict() if self.punta_a else None,
            "punta_b": self.punta_b.to_dict() if self.punta_b else None,
        }

    def get_empalmes(self) -> List[TrackingEntry]:
        """Retorna solo las entradas de tipo empalme."""

        return [e for e in self.entries if e.tipo == "empalme"]

    def get_transitos(self) -> List[TrackingEntry]:
        """Retorna solo los empalmes que son tránsitos (ODF/NODO/RACK)."""

        return [e for e in self.entries if e.tipo == "empalme" and e.es_transito]

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


def extract_alias_id(filename: str) -> Optional[str]:
    """Extrae el alias del servicio desde el nombre del archivo.

    Args:
        filename: Nombre del archivo (ej: "52547 O1C1.txt")

    Returns:
        Alias como string (ej: "O1C1") o None si no se encuentra.
    """
    match = ALIAS_REGEX.search(filename)
    if match:
        return match.group(2).upper()
    return None


def is_transito(descripcion: str) -> bool:
    """Determina si una descripción de empalme corresponde a un tránsito.

    Un tránsito es un punto de distribución como ODF, NODO, RACK, etc.
    donde la fibra puede cambiar de conectividad pero no hay empalme físico.

    Args:
        descripcion: Texto descriptivo del empalme.

    Returns:
        True si contiene keywords de tránsito.
    """
    desc_upper = descripcion.upper()
    return any(kw in desc_upper for kw in TRANSITO_KEYWORDS)


def extract_pelo_conector(text: str) -> Optional[str]:
    """Extrae la referencia pelo-conector de un texto.

    Args:
        text: Texto que puede contener referencia P##-C## o similar.

    Returns:
        String normalizado "P##-C##" o None si no se encuentra.
    """
    match = PELO_CONECTOR_REGEX.search(text)
    if match:
        pelo = match.group("pelo")
        conector = match.group("conector")
        return f"P{pelo.zfill(2)}-C{conector.zfill(2)}"
    return None


def extract_cantidad_pelos(raw_text: str) -> Optional[int]:
    """Extrae la cantidad de pelos/hilos del tracking.

    Args:
        raw_text: Contenido completo del archivo.

    Returns:
        Cantidad de pelos como int, o None si no se encuentra.
    """
    match = PELOS_COUNT_REGEX.search(raw_text)
    if match:
        return int(match.group(1))
    return None


def parse_punta(line: str) -> Optional[PuntaTerminal]:
    """Parsea una línea de punta terminal (Punta A: o Punta B:).

    Args:
        line: Línea de texto que comienza con "Punta A:" o "Punta B:"

    Returns:
        PuntaTerminal con datos extraídos, o None si no coincide.
    """
    match = PUNTA_REGEX.match(line.strip())
    if not match:
        return None

    tipo = match.group("tipo").upper()
    descripcion = match.group("descripcion").strip()

    # Intentar separar sitio de identificador físico y conector
    sitio_descripcion = descripcion
    identificador_fisico = None
    pelo_conector = None

    # Formato 1: "O-1234166-15: 16" -> sitio "O-1234166-15", conector "16"
    # Buscar patrón "texto: numero" al final
    conector_match = re.search(r"^(.+?):\s*(\d+)\s*$", descripcion)
    if conector_match:
        sitio_descripcion = conector_match.group(1).strip()
        pelo_conector = conector_match.group(2)
    else:
        # Formato 2: "ODF MAIPU 316 1 RACK 1 BANDEJA 2 P09-C10"
        # Buscar RACK/BANDEJA para separar
        rack_match = re.search(r"(RACK\s+\d+.*?)(?=\s*P\d|\s*$)", descripcion, re.IGNORECASE)
        if rack_match:
            identificador_fisico = rack_match.group(1).strip()
            # El sitio es lo que está antes del RACK
            sitio_start = descripcion.upper().find("RACK")
            if sitio_start > 0:
                sitio_descripcion = descripcion[:sitio_start].strip()
        
        # Intentar extraer P09-C10 style
        pelo_conector = extract_pelo_conector(descripcion)

    return PuntaTerminal(
        tipo=tipo,
        sitio_descripcion=sitio_descripcion,
        identificador_fisico=identificador_fisico,
        pelo_conector=pelo_conector,
        raw_line=line.strip(),
    )


def parse_tracking(raw_text: str, filename: str = "") -> TrackingParseResult:
    """Parsea el contenido crudo de un archivo de tracking y devuelve resultado estructurado.

    Args:
        raw_text: Contenido del archivo de tracking.
        filename: Nombre del archivo para extraer el ID del servicio.

    Returns:
        TrackingParseResult con ID de servicio, entradas parseadas, puntas y conteos.

    - Detecta líneas de empalme ("Empalme <id>: <descripcion>") y crea nodos de tipo "empalme".
    - Detecta líneas de fibra ("F-XYZ: ... 7.06 dB") y crea tramos con nombre de cable y atenuación.
    - Detecta líneas de Punta A/B para extraer puntos terminales.
    - Marca empalmes como tránsito si contienen keywords ODF/NODO/RACK.
    - Propaga el último empalme detectado a los tramos siguientes para poder enlazar ruta.
    """

    entries: List[TrackingEntry] = []
    current_empalme_id: Optional[str] = None
    current_empalme_desc: Optional[str] = None
    punta_a: Optional[PuntaTerminal] = None
    punta_b: Optional[PuntaTerminal] = None

    # Extraer ID del servicio y alias desde el nombre del archivo
    servicio_id = extract_servicio_id(filename) if filename else None
    alias_id = extract_alias_id(filename) if filename else None

    # Extraer cantidad de pelos
    cantidad_pelos = extract_cantidad_pelos(raw_text)

    for idx, line in enumerate(raw_text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue

        # Verificar si es una línea de Punta A o B
        punta = parse_punta(stripped)
        if punta:
            if punta.tipo == "A":
                punta_a = punta
            else:
                punta_b = punta
            continue

        empalme_match = EMPALME_REGEX.match(stripped)
        if empalme_match:
            current_empalme_id = empalme_match.group("id")
            current_empalme_desc = empalme_match.group("descripcion").strip()
            es_transito_empalme = is_transito(current_empalme_desc)
            entries.append(
                TrackingEntry(
                    tipo="empalme",
                    empalme_id=current_empalme_id,
                    empalme_descripcion=current_empalme_desc,
                    cable_nombre=None,
                    atenuacion_db=None,
                    raw_line=stripped,
                    index=idx,
                    es_transito=es_transito_empalme,
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
                    es_transito=False,
                )
            )
            continue

        logger.debug("action=parse_tracking skip_unmatched line=%s", stripped)

    empalmes_count = sum(1 for e in entries if e.tipo == "empalme")
    tramos_count = sum(1 for e in entries if e.tipo == "tramo")
    transitos_count = sum(1 for e in entries if e.tipo == "empalme" and e.es_transito)

    logger.info(
        "action=parse_tracking filename=%s servicio_id=%s alias=%s parsed_entries=%d empalmes=%d tramos=%d transitos=%d pelos=%s",
        filename,
        servicio_id,
        alias_id,
        len(entries),
        empalmes_count,
        tramos_count,
        transitos_count,
        cantidad_pelos,
    )

    return TrackingParseResult(
        servicio_id=servicio_id,
        alias_id=alias_id,
        nombre_archivo=filename,
        entries=entries,
        empalmes_count=empalmes_count,
        tramos_count=tramos_count,
        transitos_count=transitos_count,
        cantidad_pelos=cantidad_pelos,
        punta_a=punta_a,
        punta_b=punta_b,
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
