# Nombre de archivo: localidades_catalogo.py
# Ubicación de archivo: core/services/localidades_catalogo.py
# Descripción: Catálogo de localidades derivado de Cromo, para quitar la localidad que el técnico agrega al final del nombre de una cámara

"""Reconoce la **localidad que el técnico agrega al final** del nombre de una cámara.

Caso real (prod, 2026-09-29, casos #204/#205 de `app.ingresos_sin_match`): "Poste colectora oeste
panamericana km 31.500 EL TALAR" contra el inventario "Poste Colectora Oeste Panamericana Km. 31.500".
La cascada exige TODOS los tokens y "talar" no está en el nombre, así que no matchea. Es la causa J
del relevamiento del 2026-09-28 (`docs/relevamiento_ingresos_sin_match_2026-09-28.md`).

**Fuente del catálogo**: `app.cromo_botellas.localidad` (vigentes) — la localidad que Cromo guarda
para cada Botella, no una lista mantenida a mano — más las formas de Capital que escriben los
técnicos ("CF", "C.F.", "CABA").

**Regla de corte: sólo al final y justo después de un número.** "… 31.500 EL TALAR" y "… 4551
(munro)" se cortan; "Cra 25 de Mayo y Moreno" o "Poste Lavalle - Campana" no, porque ahí la
"localidad" es parte del nombre (una calle o el sufijo que desambigua). El número delante es la
señal de que lo anterior ya es una dirección completa (calle + altura/km).

El catálogo se cachea por proceso `_TTL_SEGUNDOS`; si la consulta falla se devuelve vacío sin
cachear (igual que `nodos_catalogo`).
"""

from __future__ import annotations

import logging
import re
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from modules.slack_baneo_notifier.camara_search import _normalizar

logger = logging.getLogger(__name__)

_TTL_SEGUNDOS = 600
# Capital no siempre figura así en Cromo ("capital federal", "ciudad autónoma de buenos aires").
_LOCALIDADES_FIJAS = frozenset({"cf", "c f", "caba", "capital federal", "capital", "ciudad autonoma de buenos aires"})
# Palabras de la localidad que se comparan: hasta 5 ("ciudad autonoma de buenos aires").
_MAX_PALABRAS = 5

_cache: tuple[float, frozenset[str]] | None = None


def invalidar_cache() -> None:
    global _cache
    _cache = None


def _clave(texto: str) -> str:
    """Forma comparable: sin acentos, minúsculas, sin puntuación ni paréntesis."""
    return re.sub(r"\s+", " ", re.sub(r"[.,;:()\[\]]", " ", _normalizar(texto or ""))).strip()


def _cargar(session: Session) -> frozenset[str] | None:
    try:
        # Savepoint: misma sesión que el handler de Slack (ver `nodos_catalogo._cargar`).
        with session.begin_nested():
            filas = session.execute(
                text("SELECT DISTINCT localidad FROM app.cromo_botellas WHERE vigente AND localidad IS NOT NULL")
            ).all()
    except Exception as exc:  # una mejora de búsqueda nunca puede romper el flujo de ingreso
        logger.warning("No se pudo cargar el catálogo de localidades: %s", exc)
        return None
    claves = {_clave(fila[0]) for fila in filas}
    # Sin números y de 4+ letras: "pila" (typo de Pilar en Cromo) queda, "" y basura no.
    return frozenset(c for c in claves if len(c) >= 4 and not re.search(r"\d", c)) | _LOCALIDADES_FIJAS


def localidades(session: Session) -> frozenset[str]:
    """Catálogo de localidades normalizadas (cacheado `_TTL_SEGUNDOS`)."""
    global _cache
    ahora = time.monotonic()
    if _cache is not None and ahora - _cache[0] < _TTL_SEGUNDOS:
        return _cache[1]
    claves = _cargar(session)
    if claves is None:
        return _LOCALIDADES_FIJAS
    _cache = (ahora, claves)
    return claves


def quitar_localidad_final(nombre: str, catalogo: frozenset[str]) -> str:
    """`nombre` sin la localidad final, o `nombre` sin cambios si no termina en una localidad que
    siga a un número. Prueba primero la localidad más larga ("san isidro" antes que "isidro")."""
    palabras = (nombre or "").split()
    for n in range(min(_MAX_PALABRAS, len(palabras) - 1), 0, -1):
        previa = palabras[-n - 1]
        if not re.search(r"\d", previa):
            continue
        if _clave(" ".join(palabras[-n:])) in catalogo:
            return " ".join(palabras[:-n])
    return nombre


__all__ = ["invalidar_cache", "localidades", "quitar_localidad_final"]
