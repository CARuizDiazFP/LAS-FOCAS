# Nombre de archivo: nodos_catalogo.py
# Ubicación de archivo: core/services/nodos_catalogo.py
# Descripción: Catálogo de nombres de Nodo derivado del inventario, para reconocer un Nodo aunque el técnico no escriba la palabra "Nodo"

"""Reconoce que un nombre libre se refiere a un **Nodo** aunque no diga "Nodo".

El listener de ingresos ignora los mensajes de Nodo — no son cámaras y hoy no se banean, aunque
tengan ODFs adentro — pero sólo los detectaba por la palabra "nodo" (regex `_RE_NODO` del listener, hoy `_RE_PALABRA_NODO` acá). En el
relevamiento de prod del 2026-09-28 (`docs/relevamiento_ingresos_sin_match_2026-09-28.md`), 35 de
201 casos sin match eran Nodos escritos sin esa palabra: "Atento", "Barrio Norte", "Congreso",
"Tacuari 1", "Data Tacuari, sala1", "Paraguay 2302"…

**Fuente del catálogo**: el propio inventario, no una lista mantenida a mano. Cromo publica los
racks/ODFs de cada Nodo con el nombre del Nodo adentro ("Nodo Barrio Norte - Rack 3 Electronica -
ME", "Rack 2 Nodo Llavallol", "NODO El Rincon 842 Rack 1 de Electrónica") — son los mismos nombres
"Nodo …" que aparecen en el tracking y en la consulta de Path. Se leen de `app.cromo_odfs`
(vigentes) y de `app.camaras`, y de cada uno se extraen las claves del Nodo (ver `_claves_de_nombre`).

**Regla de comparación: nombre ENTERO, nunca contenido.** "Congreso" es el Nodo Congreso; "Cra
Congreso 3449 CF" es una cámara y no se toca. Antes de comparar, la entrada se normaliza con el mismo
pipeline de la búsqueda y se le quitan prefijos/sufijos que no identifican ("data"/"datacenter"/"dc",
"sala N"/"rack N", un único dígito final — "Tacuari 1" es la sala 1 del Nodo Tacuari).

El catálogo se cachea por proceso durante `_TTL_SEGUNDOS`. Si la consulta falla, se devuelve vacío
**sin cachear** — un error transitorio no puede dejar la detección apagada diez minutos.
"""

from __future__ import annotations

import logging
import re
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from modules.slack_baneo_notifier.camara_search import normalizar_candidato

logger = logging.getLogger(__name__)

_TTL_SEGUNDOS = 600

_RE_PALABRA_NODO = re.compile(r"(?i)\bnodos?\b")
# Lo que sigue al nombre del Nodo y describe el equipamiento, no el Nodo: se corta ahí.
_RE_CORTE_EQUIPAMIENTO = re.compile(
    r"(?i)\s*(?:\brack\b|\bsala\b|\bpiso\b|\bp\s*°|\bp\d|\bpb\b|\belectr\w*|\bodf\b|\(|$)"
)
# Segmentos entre guiones que son sólo equipamiento/servicio ("ME", "LD", "OLT"): no son claves.
_SEGMENTOS_IGNORADOS = {"me", "ld", "olt", "gpon", "dwdm", "meth", "sdh", "otn", "fo"}

# Entrada: prefijos que no identifican ("Data Tacuari", "DC tacuari", "Nodo X" ya lo cubre el regex).
_RE_PREFIJO_ENTRADA = re.compile(r"^(?:data\s*center|datacenter|data|dc|nodo)\s+")
_RE_SUFIJO_SALA = re.compile(r"\s+(?:sala|rack)\s*\d*$")
_RE_DIGITO_FINAL = re.compile(r"\s+\d$")

_cache: tuple[float, frozenset[str]] | None = None


def invalidar_cache() -> None:
    """Descarta el catálogo cacheado (tests, o tras una ingesta de ODFs)."""
    global _cache
    _cache = None


def _limpiar_clave(clave: str) -> set[str]:
    """Una clave normalizada y sus variantes:

    - **Sin número final**, pero sólo si el número es corto (índice de Nodo: "retiro 2" → "retiro",
      "la plata 2") o el nombre empieza con artículo ("el rincon 842" → "el rincon"). Un número
      largo es una altura de calle: "Nodo Mitre 3821" daría la clave "mitre", y un técnico que
      escriba sólo "Mitre" quedaría ignorado en silencio como si fuera un Nodo. Se prefiere el error
      visible (sin match) al silencioso — por eso "santa fe 4965" NO produce "santa fe".
    - **Sin artículo "el" inicial** ("rincon"): los técnicos escriben "Rincón" para El Rincon.
    """
    clave = clave.strip()
    if len(clave) < 3:
        return set()
    variantes = {clave}
    match = re.search(r"(?:\s+(\d+))+$", clave)
    if match:
        sin_numeros = clave[: match.start()].strip()
        con_articulo = re.match(r"(?:el|la|los|las)\s", sin_numeros) is not None
        if len(sin_numeros) >= 3 and (len(match.group(1)) <= 2 or con_articulo):
            variantes.add(sin_numeros)
    for v in list(variantes):
        if v.startswith("el ") and len(v) > 5:
            variantes.add(v[3:])
    return variantes


def _claves_de_nombre(nombre: str) -> set[str]:
    """Claves de Nodo de un nombre del inventario que contiene la palabra "Nodo".

    "Nodo Barrio Norte - Rack 3 Electronica - ME"            → {"barrio norte"}
    "Rack 2 Nodo Libertador 710 - Vicente Lopez"             → {"libertador 710", "vicente lopez"}
    "NODO La Lucila Rack 1 - Debenedetti 602  VTE LOPEZ"     → {"la lucila", "debenedetti 602 vte lopez"}
    "Nodo Sta Fe 4965 Rack 1 Electrónica METH"               → {"santa fe 4965"}
    "NODO El Rincon 842 Rack 1 de Electrónica"               → {"el rincon 842", "el rincon", "rincon 842", "rincon"}
    """
    match = _RE_PALABRA_NODO.search(nombre)
    if not match:
        return set()
    resto = nombre[match.end():]
    claves: set[str] = set()
    for i, segmento in enumerate(re.split(r"\s+-\s+|\s*-\s*(?=[A-Za-z])", resto)):
        segmento = re.sub(r"(?i)^\s*odf\s+", "", segmento)
        corte = _RE_CORTE_EQUIPAMIENTO.search(segmento)
        segmento = segmento[: corte.start()] if corte else segmento
        clave = re.sub(r"^\W+|\W+$", "", normalizar_candidato(segmento))
        if not clave or clave in _SEGMENTOS_IGNORADOS:
            continue
        if i == 0:
            claves |= _limpiar_clave(clave)
        elif len(clave.split()) >= 2:
            # Segmentos siguientes (dirección/localidad del Nodo): tal cual, y sólo de 2+ palabras —
            # uno suelto ("Facebook", el cliente de un rack) no identifica al Nodo.
            claves.add(clave)
    return claves


def _cargar(session: Session) -> frozenset[str] | None:
    try:
        filas = session.execute(
            text(
                "SELECT nombre FROM app.camaras WHERE nombre ~* '\\mnodos?\\M' "
                "UNION SELECT nombre FROM app.cromo_odfs WHERE vigente AND nombre ~* '\\mnodos?\\M'"
            )
        ).all()
        nombres = [fila[0] for fila in filas if fila[0]]
    except Exception as exc:  # catálogo es una mejora, nunca puede romper el flujo de ingreso
        logger.warning("No se pudo cargar el catálogo de Nodos: %s", exc)
        return None
    claves: set[str] = set()
    for nombre in nombres:
        claves |= _claves_de_nombre(nombre)
    return frozenset(claves)


def claves_nodo(session: Session) -> frozenset[str]:
    """Catálogo de claves de Nodo (cacheado `_TTL_SEGUNDOS`)."""
    global _cache
    ahora = time.monotonic()
    if _cache is not None and ahora - _cache[0] < _TTL_SEGUNDOS:
        return _cache[1]
    claves = _cargar(session)
    if claves is None:
        return frozenset()
    _cache = (ahora, claves)
    return claves


def _variantes_entrada(nombre: str) -> set[str]:
    base = normalizar_candidato(nombre)
    variantes = {base}
    sin_prefijo = _RE_PREFIJO_ENTRADA.sub("", base)
    variantes.add(sin_prefijo)
    for v in list(variantes):
        sin_sala = _RE_SUFIJO_SALA.sub("", v).strip()
        variantes.add(sin_sala)
        variantes.add(_RE_DIGITO_FINAL.sub("", sin_sala).strip())
    return {v for v in variantes if v}


def es_nombre_de_nodo(nombre: str, session: Session) -> bool:
    """True si `nombre`, entero, es el nombre de un Nodo del catálogo (con o sin la palabra "Nodo")."""
    if not nombre or not nombre.strip():
        return False
    claves = claves_nodo(session)
    return bool(claves) and not _variantes_entrada(nombre).isdisjoint(claves)


def corresponde_a_nodo(nombre: str, session: Session) -> bool:
    """Criterio único de "esto es un Nodo, no una cámara": la palabra "Nodo" en el texto (criterio
    histórico del listener) o el nombre entero de un Nodo del catálogo."""
    return bool(_RE_PALABRA_NODO.search(nombre or "")) or es_nombre_de_nodo(nombre, session)


__all__ = ["claves_nodo", "corresponde_a_nodo", "es_nombre_de_nodo", "invalidar_cache"]
