# Nombre de archivo: direccion_comparacion.py
# Ubicación de archivo: core/services/cromo/direccion_comparacion.py
# Descripción: Señal de comparación entre la dirección PROV (texto libre) y la calle/altura estructurada de una ODF Cromo — para el modal de asociación manual de Servicios sin ODF

"""Compara `servicios_equipos_ultima_milla.direccion` (texto libre cargado por PROV, ej.
`"PERON, JUAN DOMINGO, TTE. GENERAL 650 P.5"`) contra `calle`/`altura` estructurados de una ODF
Cromo (ej. `("AVENIDA BARTOLOME MITRE", "2525")`) y devuelve una señal (`SenalDireccion`) para que
el operador la vea en el modal de asociación manual — **nunca bloquea** la confirmación, sólo
informa. Función pura: sin DB, sin efectos secundarios.

Reusa la normalización de texto de `modules/slack_baneo_notifier/camara_search.py`
(`_limpiar_puntuacion`, `_normalizar`, `expandir_abreviaturas_y_sinonimos`) para no duplicar las
tablas de abreviaturas/sinónimos viales que ese módulo ya mantiene.
"""

from __future__ import annotations

import re
from enum import Enum

from modules.slack_baneo_notifier.camara_search import (
    _limpiar_puntuacion,
    _normalizar,
    expandir_abreviaturas_y_sinonimos,
)

__all__ = ["SenalDireccion", "comparar_direccion_prov_vs_odf"]

# Stopwords descartadas al armar los tokens significativos de una calle — artículos/preposiciones
# frecuentes en nombres de calle ("Avenida de los Constituyentes", "Pasaje del Carmen") que no
# aportan señal para distinguir una calle de otra.
_STOPWORDS = {"de", "la", "el", "los", "las", "y", "del"}

# Sufijo de piso/depto al final de una dirección PROV (ej. "P.19", "Piso 3", "Dpto B", "Depto. 4A")
# — se descarta antes de buscar la altura, porque si no el número de piso podría confundirse con
# la altura de la calle. Anclado al final del string (`$`) para no comerse texto interno legítimo
# (ej. "TTE. GENERAL" en medio de una calle no matchea porque no está al final).
_RE_PISO_DEPTO_SUFIJO = re.compile(
    r"(?i)\s+(?:p\.?\s*\d+[a-z]?|piso\s*\d+[a-z]?|dpto\.?\s*[a-z0-9]+|depto\.?\s*[a-z0-9]+)\.?\s*$"
)

# Altura: número al final del string restante (después de descartar el sufijo de piso/depto).
_RE_ALTURA_FINAL = re.compile(r"(\d+)\s*$")


class SenalDireccion(str, Enum):
    """Resultado de comparar una dirección PROV contra la calle/altura de una ODF Cromo.

    Mismos valores que el CHECK de la migración de la Task 1 — este enum es la fuente de verdad
    en código, la migración sólo replica los strings.
    """

    COINCIDE = "coincide"
    NO_COINCIDE = "no_coincide"
    NO_SE_PUDO_COMPARAR = "no_se_pudo_comparar"


def _extraer_calle_y_altura_prov(direccion: str | None) -> tuple[str | None, str | None]:
    """Separa calle y altura de un string libre de dirección PROV.

    El formato real de PROV es simple: `"<calle> <altura> [piso/depto]"` — sin localidad ni
    provincia en este campo (a diferencia del título completo que muestra Cromo). Por eso no hace
    falta un parser genérico de direcciones: alcanza con descartar el sufijo de piso/depto si está
    presente y tomar como altura el número que queda al final.

    Devuelve `(None, None)` si `direccion` está vacía o si no se puede identificar una altura
    (no hay un número al final) — nunca inventa una altura.
    """
    if not direccion or not direccion.strip():
        return None, None

    texto = _RE_PISO_DEPTO_SUFIJO.sub("", direccion.strip()).strip()

    match = _RE_ALTURA_FINAL.search(texto)
    if not match:
        return None, None

    altura = match.group(1)
    calle = texto[: match.start()].strip(" ,.;")
    if not calle:
        return None, None

    return calle, altura


def _tokens_significativos(texto: str) -> set[str]:
    """Normaliza y tokeniza `texto`, descartando tokens de menos de 3 caracteres y stopwords.

    Reusa el pipeline de normalización de `camara_search.py` (limpieza de puntuación,
    unaccent+lowercase, expansión de abreviaturas y sinónimos viales) para que variantes como
    `"AV."`/`"AVENIDA"` terminen siendo el mismo token — sin esto, la intersección de tokens
    fallaría por diferencias puramente ortográficas, no de contenido.
    """
    if not texto:
        return set()

    limpio = _limpiar_puntuacion(texto)
    normalizado = _normalizar(limpio)
    expandido = expandir_abreviaturas_y_sinonimos(normalizado)
    return {t for t in expandido.split() if len(t) >= 3 and t not in _STOPWORDS}


def _normalizar_altura(altura: str) -> str:
    """Normaliza una altura para comparar ignorando ceros a la izquierda (`"0650"` == `"650"`)."""
    altura = altura.strip()
    if altura.isdigit():
        return str(int(altura))
    return altura


def comparar_direccion_prov_vs_odf(
    direccion_prov: str | None,
    calle_odf: str | None,
    altura_odf: str | None,
) -> SenalDireccion:
    """Compara la dirección libre de PROV contra la calle/altura estructurada de una ODF Cromo.

    La comparación de calle es por **intersección de tokens significativos**, no por substring ni
    por orden — esto resuelve el caso típico de PROV cargando "apellido, nombre invertido" en
    nombres de calle con persona (ej. `"PERON, JUAN DOMINGO, TTE. GENERAL"` vs.
    `"TTE GRAL JUAN D PERON"`) sin necesidad de reconstruir el nombre canónico de la calle.

    La altura es la señal decisiva: si ambos lados tienen altura y no coinciden (sin ceros a la
    izquierda), el resultado es siempre `NO_COINCIDE` — dos direcciones con distinta altura son
    distintas incluso si la calle matchea (típico: un domicilio viejo en la misma calle). Sólo
    cuando la altura coincide se evalúa si hay evidencia de que también es la misma calle: con
    tokens en común, `COINCIDE`; sin tokens en común, la altura pudo coincidir por azar y no hay
    evidencia suficiente para afirmar ni descartar — `NO_SE_PUDO_COMPARAR`.

    Si falta información de cualquiera de los dos lados (dirección PROV vacía, ODF sin calle o sin
    altura, o no se pudo extraer calle/altura del texto de PROV), devuelve `NO_SE_PUDO_COMPARAR`
    directamente — nunca fuerza una conclusión sin evidencia. Es sólo una señal para el operador:
    esta función no decide nada de flujo, no bloquea ninguna asociación manual.
    """
    if not direccion_prov or not direccion_prov.strip():
        return SenalDireccion.NO_SE_PUDO_COMPARAR
    if not calle_odf or not altura_odf:
        return SenalDireccion.NO_SE_PUDO_COMPARAR

    calle_prov, altura_prov = _extraer_calle_y_altura_prov(direccion_prov)
    if not calle_prov or not altura_prov:
        return SenalDireccion.NO_SE_PUDO_COMPARAR

    if _normalizar_altura(altura_prov) != _normalizar_altura(altura_odf):
        return SenalDireccion.NO_COINCIDE

    tokens_prov = _tokens_significativos(calle_prov)
    tokens_odf = _tokens_significativos(calle_odf)
    if tokens_prov & tokens_odf:
        return SenalDireccion.COINCIDE

    return SenalDireccion.NO_SE_PUDO_COMPARAR
