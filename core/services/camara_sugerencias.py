# Nombre de archivo: camara_sugerencias.py
# Ubicación de archivo: core/services/camara_sugerencias.py
# Descripción: Sugerencias "¿Quisiste decir…?" para un nombre de cámara sin match — nunca resuelven ni registran nada

"""Sugerencias de cámara para un nombre que la búsqueda no pudo resolver.

Cubre la causa J del relevamiento del 2026-09-28 (`docs/relevamiento_ingresos_sin_match_2026-09-28.md`,
54 de 201 casos de prod): el texto tiene la altura correcta pero palabras que el nombre del
inventario no tiene ("Botella, terraza. Esmeralda 726. CF" contra "Bot. 2 Tza. Esmeralda 726 C.F.",
"Cra capitán bermudez 4551 (munro)") o un typo ("Cra juano manso 720"). La cascada exige TODOS los
tokens y falla.

**Deliberadamente no es un match.** Un typo resuelto automáticamente puede registrar el ingreso en
la cámara equivocada — peor que no registrarlo. Las sugerencias sólo se muestran (respuesta de Slack)
para que el técnico corrija y use "Revalidar ingreso" o "Forzar ingreso".

Criterio (medido sobre los casos reales): la candidata tiene que contener **todos** los números del
texto como números completos y compartir al menos un token de calle (se comparan los primeros 4
caracteres, lo que absorbe typos al final de palabra). Sin números en el texto no se sugiere nada: un
nombre de calle solo tiene cientos de candidatas.

El índice (nombres de `app.camaras` + `app.cromo_botellas`) se cachea por proceso `_TTL_SEGUNDOS`; si
la carga falla se devuelve vacío sin cachear.
"""

from __future__ import annotations

import logging
import re
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from modules.slack_baneo_notifier.camara_search import _normalizar, preparar_nombre_busqueda, quitar_botella_uno

logger = logging.getLogger(__name__)

_TTL_SEGUNDOS = 600
# Prefijos de 4 letras que no identifican una calle: descriptores, tipo de elemento y localidades
# que casi todos los nombres comparten.
_PREFIJOS_IGNORADOS = {
    "capi", "fede", "buen", "aire", "bote", "terr", "cama", "post", "call", "cale", "aven",
    "esqu", "fren", "caba", "faca", "piso", "sala",
}

_Entrada = tuple[str, frozenset[str], frozenset[str]]
_cache: tuple[float, list[_Entrada]] | None = None


def invalidar_cache() -> None:
    global _cache
    _cache = None


def _tokens(texto_normalizado: str) -> tuple[frozenset[str], frozenset[str]]:
    limpio = re.sub(r"[.,;:()<>|/]", " ", texto_normalizado)
    numeros = frozenset(re.findall(r"\d+", limpio))
    prefijos = frozenset(
        w[:4] for w in limpio.split() if len(w) >= 4 and not w.isdigit() and w[:4] not in _PREFIJOS_IGNORADOS
    )
    return numeros, prefijos


def _indice(session: Session) -> list[_Entrada]:
    global _cache
    ahora = time.monotonic()
    if _cache is not None and ahora - _cache[0] < _TTL_SEGUNDOS:
        return _cache[1]
    try:
        # Savepoint: misma sesión que el handler de Slack (ver `nodos_catalogo._cargar`).
        with session.begin_nested():
            filas = session.execute(
                text(
                    "SELECT nombre FROM app.camaras WHERE nombre IS NOT NULL "
                    "UNION SELECT nombre FROM app.cromo_botellas WHERE nombre IS NOT NULL AND vigente"
                )
            ).all()
    except Exception as exc:  # una sugerencia nunca puede romper la respuesta al técnico
        logger.warning("No se pudo cargar el índice de sugerencias de cámara: %s", exc)
        return []
    indice = [(fila[0], *_tokens(_normalizar(fila[0]))) for fila in filas if fila[0]]
    _cache = (ahora, indice)
    return indice


def sugerir_camaras(nombre: str, session: Session, *, limite: int = 3) -> list[str]:
    """Hasta `limite` nombres del inventario parecidos a `nombre` (mejor primero). Lista vacía si el
    texto no tiene números o ningún token de calle."""
    # Mismo preprocesamiento que la búsqueda: sin él, el "1" de "Bot 1" se exigiría como número
    # ("Paseo colon 701 bot 1" no sugería nada) y "bot2" no aportaría el "2".
    numeros, prefijos = _tokens(_normalizar(quitar_botella_uno(preparar_nombre_busqueda(nombre or ""))))
    if not numeros or not prefijos:
        return []
    puntuadas: list[tuple[int, str]] = []
    for candidato, c_numeros, c_prefijos in _indice(session):
        if not numeros <= c_numeros:
            continue
        coincidencias = len(prefijos & c_prefijos)
        if coincidencias:
            puntuadas.append((coincidencias, candidato))
    puntuadas.sort(key=lambda par: (-par[0], len(par[1]), par[1]))
    vistos: set[str] = set()
    resultado: list[str] = []
    for _, candidato in puntuadas:
        clave = _normalizar(candidato)
        if clave in vistos:
            continue
        vistos.add(clave)
        resultado.append(candidato)
        if len(resultado) == limite:
            break
    return resultado


__all__ = ["invalidar_cache", "sugerir_camaras"]
