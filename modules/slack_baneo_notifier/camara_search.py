# Nombre de archivo: camara_search.py
# Ubicación de archivo: modules/slack_baneo_notifier/camara_search.py
# Descripción: Búsqueda robusta de cámaras por nombre con normalización y abreviaturas para el listener de ingresos

"""Búsqueda tolerante de cámaras a partir de texto libre escrito por técnicos.

El nombre recibido puede tener abreviaturas, acentos alternos, ausencia de
números, etc.  La estrategia en cascada garantiza que se intenten varios
niveles de coincidencia antes de rendirse.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from db.models.cromo import CromoBotella
    from db.models.infra import Camara

# Exportado explícitamente para reuso desde `core/services/cromo/camara_botella_busqueda.py`
# (búsqueda extendida Camara + CromoBotella): esa cascada equivalente contra `CromoBotella.nombre`
# reusa este mismo pipeline de normalización sin duplicarlo. `_limpiar_puntuacion` se agrega además
# de los 4 helpers pedidos porque es el primer paso del pipeline (limpiar puntuación → expandir
# abreviaturas → normalizar → sinónimos) — omitirlo produciría una normalización distinta a la que
# usa `buscar_camara()` internamente para el mismo input. `_filtrar_bots_secundarios` (agregado en
# la revisión del 2026-08-23) sólo toca `.nombre` vía regex — nada específico de `Camara` — así que
# también se reusa contra candidatas `CromoBotella` para evitar que "Cra Mitre 440" (sin mención de
# "bot"/"botella") empareje incorrectamente "Bot 2 Cra Mitre 440".
__all__ = [
    "_expandir_abreviaturas",
    "_aplicar_sinonimos",
    "_normalizar",
    "_filtrar_por_numeros",
    "_filtrar_bots_secundarios",
    "_filtrar_numero_de_botella",
    "tiene_gemela_critica",
    "recorte_pierde_la_botella",
    "_limpiar_puntuacion",
    "buscar_camara",
    "normalizar_candidato",
    "preparar_nombre_busqueda",
    "separar_prefijo_empalme",
    "botella_cromo_por_n_id",
    "resto_corrobora_botella",
    "camara_por_prefijo_empalme",
    "quitar_botella_uno",
    "extraer_tipo_movimiento",
    "extraer_slack_user_id_autorizacion",
    "AmbiguousSearchError",
    "NumeroNoCoincideError",
]

# ── Tabla de abreviaturas comunes usadas por técnicos ────────────────────
# NOTA: "Cra" NO está en esta tabla.  Los nombres de cámara almacenados en DB
# conservan "Cra" de forma literal (ej: "Bot 2 Cra Poste …"); expandirlo a
# "carrera" destruiría el match ILIKE.  El Intento 4 cubre este caso.
_ABREVIATURAS: dict[str, str] = {
    r"\bclle\b": "calle",
    r"\ball\b": "calle",   # alias informal
    r"\bav\b": "avenida",
    r"\bave\b": "avenida",
    r"\bpje\b": "pasaje",
    r"\bpas\b": "pasaje",
    r"\bbv\b": "boulevard",
    r"\bblvd\b": "boulevard",
    r"\bdr\b": "doctor",
    r"\bpte\b": "presidente",
    r"\bsn\b": "san",
    r"\bsta\b": "santa",
    r"\bsto\b": "santo",
    r"\bcf\b": "",          # código de filial — ignorar al buscar
    # "C.F." escrito con puntos: `_limpiar_puntuacion` ya convirtió cada punto en espacio, así que
    # llega como los dos tokens sueltos "c f" y el patrón `\bcf\b` de arriba no lo alcanza. Sin esta
    # entrada, "Cra X CF" y "Cra X C.F." normalizan distinto — medido contra prod el 2026-09-08: el
    # detector de Cámaras duplicadas informaba 0 grupos cuando había 96 pares que sólo difieren en eso.
    r"\bc\s+f\b": "",
}

# ── Diccionario de sinónimos (aplicado DESPUÉS de normalizar) ────────────
# Permite empatar variaciones semánticas frecuentes en escritura técnica.
# Se aplican sobre el texto ya en minúsculas y sin acentos (post-unidecode).
_SINONIMOS: dict[str, str] = {
    r"\bbotella\b": "bot",    # "Botella" → "Bot" (prefijo de cámara)
    r"\bcamara\b": "cra",    # "camara" / "cámara" (post-unidecode) → "cra"
}

# Regex principal: campo del Workflow "*Nombre: Nodo/Camara/botella*\n[valor]"
_RE_NOMBRE_WORKFLOW = re.compile(
    r"(?i)\*?Nombre:\s*Nodo[/\\]C[aá]mara[/\\]botella\*?\n(.+?)(?:\n|$)"
)
# Fallback cuando la primera línea capturada por `_RE_NOMBRE_WORKFLOW` resulta demasiado corta/
# insuficiente (`_pocos_tokens_significativos`, mismo umbral que la heurística de ambigüedad de
# `buscar_camara`): probablemente un salto de línea accidental del técnico al copiar/pegar el
# nombre — real en prod, ticket MKT 122293, 2026-09-07: campo cargado como "e:\nCra Curupayti 2951
# CF - CURUPAYTI 2964 - Capital Federal - Capital Federal". En ese caso se extiende la captura hasta
# el próximo campo en negrita ("\n*") o el fin del mensaje — `re.DOTALL` permite que `(.+?)` cruce
# los saltos de línea intermedios. No se usa como regex principal para no swallowear contenido de
# otro campo cuando la primera línea YA es un nombre válido y autosuficiente.
_RE_NOMBRE_WORKFLOW_EXTENDIDO = re.compile(
    r"(?i)\*?Nombre:\s*Nodo[/\\]C[aá]mara[/\\]botella\*?\n(.+?)(?=\n\*|\Z)",
    re.DOTALL,
)
# Primera línea residual de copy/paste antes del nombre real ("me:\nCra Acevedo 396 CF - …"): 1 a 3
# caracteres seguidos de ":". Sólo se quita en la captura extendida (la primera línea ya se juzgó
# insuficiente), nunca de un nombre de una sola línea.
_RE_PREFIJO_BASURA = re.compile(r"^\w{1,3}:\s+")
# Regex fallback: campo libre "Cámara: [valor]" o "Cámara, [valor]"
_RE_CAMPO_CAMARA = re.compile(r"(?i)c[aá]maras?\s*[,:]\s*(.+?)(?:\n|$)")

# Regex para extraer tipo de movimiento (Ingreso/Egreso)
_RE_TIPO_MOVIMIENTO_WORKFLOW = re.compile(r"(?i)\*?Ingreso o Egreso\*?\n\s*(Ingreso|Egreso)\b")
# Regex para extraer Slack user ID de la mención de persona que solicitó autorización
_RE_PERSONA_AUTORIZACION_WORKFLOW = re.compile(
    r"(?i)Persona que solicito La Autorizacion\s*\n\s*<@(U[A-Z0-9]+)"
)

# Detecta menciones del tipo "Botella 1 y 2", "Bot 1 y 2", "botellas 2 y 3", etc.
# Captura los dos números para expandirlos en búsquedas independientes.
# Desde 2026-09-28 (relevamiento de `ingresos_sin_match` de prod,
# `docs/relevamiento_ingresos_sin_match_2026-09-28.md`) también acepta el número pegado y el "bot"
# repetido ("bot1 y bot2", caso real "Cra monteagudo 202 bot1 y bot2"), que antes caía entero como
# un solo nombre y no matcheaba ninguna de las dos botellas.
_RE_MULTI_BOT = re.compile(
    r"(?i)\bbot(?:ella)?s?\.?\s*(\d+)\s*(?:y|&)\s*(?:bot(?:ella)?s?\.?\s*)?(\d+)\b"
)

# ── Preprocesamiento de la búsqueda (2026-09-28) ──────────────────────────────────────────────
# Tres formas de escritura reales que la cascada no podía resolver, medidas contra los 201 casos
# `ingresos_sin_match` de prod (ver `docs/relevamiento_ingresos_sin_match_2026-09-28.md`). Se
# aplican sólo a la ENTRADA de la búsqueda (`preparar_nombre_busqueda`), nunca a
# `_limpiar_puntuacion`/`_normalizar`: esos dos también normalizan nombres del inventario para el
# detector de duplicados y la jerarquía Cámara/Botella, y cambiarlos movería grupos ya calculados.

# "bot2", "BOT2.", "bo2", "bot.2" → "Bot 2". Sin esto, `\bbot(ella)?\b` (detección de `tiene_bot`)
# no ve la botella — no hay límite de palabra entre "t" y "2" — y la cascada DESCARTA justamente las
# botellas secundarias (26 filas reales). Sólo con el número PEGADO: "Bot 2"/"Bot. 2" ya funcionaban.
# Un dígito y lookahead `(?!\d)`, mismo criterio que `RE_BOT_SUFIJO` ("Bot 30 de Septiembre").
_RE_BOT_PEGADO = re.compile(r"(?i)\b(?:bot(?:ella)?|bo)\.?([1-9])(?!\d)")
# Letras seguidas de número sin espacio ("huergo701", "Solis1702") → "huergo 701". Mínimo 3 letras
# para no partir códigos cortos como "R197"/"F1" (ésos los cubre el filtro de números sin `\b`).
_RE_LETRAS_NUMERO = re.compile(r"(?<=[^\W\d_]{3})(?=\d)")
# "Bot 1"/"Botella 1": por convención la Botella 1 es la Cámara principal, cuyo nombre NO lleva
# "Bot 1" (ver `detectar_multi_bot`). Se quita sólo como SEGUNDO intento (`quitar_botella_uno`):
# hay nombres reales que sí lo llevan literal ("Cra Juan Domingo Peron 498 Bot 1 CF").
_RE_BOTELLA_UNO = re.compile(r"(?i)\bbot(?:ella)?\.?\s*1(?!\d)\.?")


# "Empalme 10245762: Cra 25 de Mayo 302" (caso real, 2026-10-23): el técnico antepone el `n_id` de
# Cromo de la Botella (8 dígitos) — "empalme" es como llaman a la Botella en la calle. Sólo al
# principio del texto y seguido de ":"/"-" o del fin del texto.
_RE_PREFIJO_EMPALME = re.compile(r"(?i)^\s*empalme\s*#?\s*(\d{8})\s*(?:[:\-–]\s*|$)")


def separar_prefijo_empalme(texto: str) -> tuple[int | None, str]:
    """``("Empalme 10245762: Cra X 1")`` → ``(10245762, "Cra X 1")``. Sin el prefijo devuelve
    ``(None, texto)`` sin cambios."""
    match = _RE_PREFIJO_EMPALME.match(texto or "")
    if not match:
        return None, texto
    return int(match.group(1)), texto[match.end():].strip()


def botella_cromo_por_n_id(n_id: int, session: Session) -> "CromoBotella | None":
    """`CromoBotella` por `n_id`, sólo si es vigente y está vinculada a una Cámara. Compartida con la
    búsqueda por ID explícito de `core/services/cromo/camara_botella_busqueda.py`."""
    from db.models.cromo import CromoBotella

    botella = session.get(CromoBotella, n_id)
    if botella is None or botella.camara_id is None or not botella.vigente:
        return None
    return botella


def resto_corrobora_botella(botella: "CromoBotella", resto: str) -> bool:
    """El texto que acompaña a un ID explícito no contradice a la Botella: vacío, o comparte con su
    nombre un número o una palabra de 4+ letras. Un ID mal tipeado que exista no puede resolver a
    una cámara que el resto del texto contradice (hallazgo de la revisión de 2026-09-28)."""
    resto = _normalizar(resto or "")
    resto = re.sub(r"\b(?:id|de|botella|bot|n[°ºo]?)\b", " ", resto)
    senales = set(re.findall(r"\d+", resto)) | set(re.findall(r"[a-z]{4,}", resto))
    if not senales:
        return True
    nombre_botella = _normalizar(botella.nombre or "")
    return any(re.search(rf"(?<![a-z0-9]){re.escape(x)}(?![a-z0-9])", nombre_botella) for x in senales)


def camara_por_prefijo_empalme(texto: str, session: Session) -> tuple["CromoBotella | None", str]:
    """Resuelve el prefijo "Empalme <n_id>" por `n_id` de Cromo. Devuelve ``(botella, resto)``: la
    Botella si el `n_id` existe, es vigente, tiene Cámara y el resto del texto la corrobora; si no,
    ``(None, resto)`` — el texto SIN el prefijo, para seguir la búsqueda por nombre sin exigir ese
    número. Sin prefijo, ``(None, texto)``."""
    n_id, resto = separar_prefijo_empalme(texto)
    if n_id is None:
        return None, texto
    botella = botella_cromo_por_n_id(n_id, session)
    if botella is not None and resto_corrobora_botella(botella, resto):
        return botella, resto
    return None, resto


def preparar_nombre_busqueda(texto: str) -> str:
    """Normaliza las formas de escritura de la entrada que la cascada no resuelve: "bot" pegado al
    número y letras pegadas al número. Idempotente — se puede aplicar más de una vez sin efecto."""
    texto = _RE_BOT_PEGADO.sub(lambda m: f"Bot {m.group(1)}", texto)
    texto = _RE_LETRAS_NUMERO.sub(" ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def quitar_botella_uno(texto: str) -> str:
    """Quita la mención "Bot 1"/"Botella 1" (= la Cámara principal). Devuelve el texto sin cambios
    si no la tiene — el caller compara para saber si hay una variante que reintentar."""
    return re.sub(r"\s+", " ", _RE_BOTELLA_UNO.sub(" ", texto)).strip()

# Detecta el sufijo "Bot N" (botella secundaria) dentro de un nombre de cámara — constante
# exportable, compartida con `core/services/camara_hierarchy_service.py` (jerarquía Cámara/Botella,
# Etapa Infra). Clase de un solo dígito [1-9] a propósito: evita el falso positivo real encontrado en
# datos reales, "Bot 30 de Septiembre y J.M.Estrada" ("30" es parte del nombre de la calle, no un
# índice de botella) — con una clase de un solo carácter, el lookahead `(?!\d)` falla porque a "3" le
# sigue otro dígito ("0"), y la coincidencia se descarta. El lookahead (no un `\b` de cierre) es
# necesario porque hay nombres reales sin espacio tras el número ("Bot 3CF") donde un `\b` de cierre
# fallaría (dígito seguido de letra, ambos \w, sin límite de palabra entre ellos).
#
# `\.?` final (2026-08-14): bug real encontrado en datos de Cromo — nombres con el punto DESPUÉS del
# dígito ("Bot 2. Cra Marcos Sastre y Colectora Este") dejaban ese punto como residuo al inicio del
# nombre resultante ("`. Cra Marcos Sastre y Colectora Este`"), porque el regex sólo consumía un punto
# ANTES del dígito ("Bot. 2"), nunca después. Va después del lookahead a propósito: el lookahead sigue
# evaluando el carácter inmediatamente siguiente al dígito sin que el punto opcional interfiera (
# "Bot 30 de Septiembre..." sigue sin matchear, el lookahead ve "0" antes de que el `\.?` entre en
# juego). Confirmado real contra `lasfocasdev-postgres`: 7 Cámaras con este residuo, ver
# `docs/decisiones.md` entrada 2026-08-14.
RE_BOT_SUFIJO = re.compile(r"\bbot\.?\s*[1-9](?!\d)\.?", re.IGNORECASE)

# Detecta sufijos de ruido operativo: "- CUADRILLA DE HIDROCONS", "/ Móvil 4", etc.
# Solo corta en separador (-, /, |) SEGUIDO de una stopword operativa conocida.
# Preserva localidades con guion: "Poste Lavalle - Campana" (Campana no es stopword).
_RE_RUIDO_OPERATIVO = re.compile(
    r"(?i)\s*[-/|]\s*"
    r"(?:cuadrilla|m[oó]vil|contratista|ticket|equipo|personal|guardia|"
    r"inspector|t[eé]cnico|brigada|grupo|empresa)\b.*"
)

# "CRITICA" va aparte de `_RE_RUIDO_OPERATIVO` y ANCLADA al final del nombre a propósito. Las
# stopwords de arriba son siempre terminales en los datos reales ("- CUADRILLA DE HIDROCONS"), así
# que su `.*` greedy no hace daño; "crítica", en cambio, es un calificador que podría venir seguido
# de información que sí identifica el sitio. Sin el ancla, "Cra Ruta 9 - Critica Km 45" y
# "… Km 46" colapsarían al mismo nombre — dos postes distintos de la misma ruta. Hoy los 10 casos
# reales en prod son todos terminales, pero esta normalización también decide si crear o reusar una
# Cámara padre durante la ingesta, así que el modo de falla sería silencioso. Plural incluido:
# el archivo de negocio se llama "Criticas en seguimiento".
_RE_SUFIJO_CRITICA = re.compile(r"(?i)\s*[-/|]\s*cr[ií]tic[ao]s?\s*$")


def detectar_multi_bot(nombre_raw: str) -> list[str] | None:
    """Detecta si el nombre menciona múltiples botellas/bots en un mismo campo.

    Patrones reconocidos: "Botella 1 y 2", "Bot 1 y 2", "botellas 2 y 3", etc.

    Regla de numeración canónica:
      - Botella 1 (N=1) corresponde a la cámara principal, cuyo nombre NO lleva
        el prefijo "Bot"; se busca con la dirección base sin prefijo.
      - Botella N≥2 lleva "Bot N" como prefijo en la DB; se le antepone "Bot N".

    Ejemplo::

        "Bartolomé Mitre 301. Botella 1 y 2. CF"
        → ["Bartolomé Mitre 301 CF", "Bot 2 Bartolomé Mitre 301 CF"]

    Returns:
        Lista de 2 strings limpios para pasar a ``buscar_camara()``, o ``None``
        si no se detectó el patrón.
    """
    match = _RE_MULTI_BOT.search(nombre_raw)
    if not match:
        return None

    n1, n2 = int(match.group(1)), int(match.group(2))
    # Remover el patrón multi-bot y limpiar el resultado
    base = _RE_MULTI_BOT.sub("", nombre_raw)
    # Eliminar puntuación sobrante (comas, puntos no seguidos de dígito, punto y coma)
    base = re.sub(r"[,;]", " ", base)
    base = re.sub(r"\.(?!\d)", " ", base)
    base = re.sub(r"\s+", " ", base).strip()

    base = _RE_BOT_PEGADO.sub(lambda m: f"Bot {m.group(1)}", base)
    # Un "Bot"/"Botella" SIN número al principio ("Bot monteagudo 202 bot1 y bot2", caso real de prod
    # 2026-09-28) es la palabra genérica, no una botella: si queda en la base, la Botella 1 se busca
    # como "Bot monteagudo 202", `tiene_bot` deja pasar las botellas secundarias y resuelve a la Bot 2.
    base = re.sub(r"(?i)^\s*bot(?:ella)?s?\.?\s+(?![1-9](?!\d))", "", base)
    base = re.sub(r"\s+", " ", base).strip()

    nombres: list[str] = []
    for n in sorted({n1, n2}):
        if n == 1:
            # Botella 1 = cámara principal sin prefijo Bot
            nombres.append(base)
        else:
            nombres.append(f"Bot {n} {base}")
    return nombres


def limpiar_ruido_operativo(texto: str) -> str:
    """Elimina sufijos de ruido operativo del nombre de cámara.

    Corta en el primer separador (-, /, |) seguido de una stopword operativa
    conocida (cuadrilla, móvil, contratista, equipo, técnico, etc.).

    Solo actúa cuando el token posterior al separador es reconocido como ruido.
    Las localidades con guion (ej: "Poste Lavalle - Campana") se preservan
    intactas porque "Campana" no es una stopword operativa.

    Ejemplo::

        "Cra Quesada 2396 CF - CUADRILLA DE HIDROCONS"  →  "Cra Quesada 2396 CF"
        "Camara 1 - Móvil 4"                            →  "Camara 1"
        "Poste Lavalle - Campana"                       →  "Poste Lavalle - Campana"
        "Cra San Martin 1 CF - CRITICA"                 →  "Cra San Martin 1 CF"
        "Cra Ruta 9 - Critica Km 45"                    →  "Cra Ruta 9 - Critica Km 45"
    """
    return _RE_SUFIJO_CRITICA.sub("", _RE_RUIDO_OPERATIVO.sub("", texto)).strip()


def _limpiar_puntuacion(texto: str) -> str:
    """Elimina signos de puntuación irrelevantes antes de normalizar.

    - Comas, punto y coma, puntos NO precedidos de dígitos (para preservar
      decimales como "7.06 dB").
    - Guiones rodeados de espacios (" - ") → espacio simple.
    - Normaliza espacios múltiples resultantes.
    """
    # Punto y coma y comas → espacio
    texto = re.sub(r"[,;]", " ", texto)
    # Punto no seguido de dígito → espacio (preserva decimales: 7.06 intacto)
    texto = re.sub(r"\.(?!\d)", " ", texto)
    # Guión con espacios (separador de texto largo) → espacio
    texto = re.sub(r"\s+-\s+", " ", texto)
    # Normalizar espacios
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _normalizar(texto: str) -> str:
    """Normaliza texto: sin acentos, minúsculas, espacios simples."""
    try:
        from unidecode import unidecode
        texto = unidecode(texto)
    except ImportError:
        pass
    texto = texto.lower().strip()
    texto = re.sub(r"\s+", " ", texto)
    return texto


def _aplicar_sinonimos(texto_norm: str) -> str:
    """Aplica el diccionario de sinónimos sobre texto ya normalizado (lowercase, sin acentos)."""
    for patron, reemplazo in _SINONIMOS.items():
        texto_norm = re.sub(patron, reemplazo, texto_norm, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", texto_norm).strip()


def _expandir_abreviaturas(texto: str) -> str:
    """Reemplaza abreviaturas comunes por su forma completa."""
    for patron, reemplazo in _ABREVIATURAS.items():
        texto = re.sub(patron, reemplazo, texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def expandir_abreviaturas_y_sinonimos(texto_normalizado: str) -> str:
    """Aplica sobre un texto YA normalizado (unaccent+lowercase+sin puntuación — ej. la salida de
    `camara_hierarchy_service.normalizar_para_agrupar`) la misma expansión de abreviaturas viales y
    sinónimos que ya usa `buscar_camara()` para texto libre de técnicos — reusa `_ABREVIATURAS`/
    `_SINONIMOS` sin duplicar las tablas. Pensada para detectar candidatas a duplicado entre nombres
    ya estructurados de la DB (`core/services/camara_duplicados_service.py`), no sólo texto libre."""
    return _aplicar_sinonimos(_expandir_abreviaturas(texto_normalizado))


def normalizar_candidato(nombre: str) -> str:
    """Pipeline completo de normalización (puntuación → abreviaturas → minúsculas/acentos →
    sinónimos) aplicado a un nombre del inventario, para compararlo por igualdad contra la entrada
    ya normalizada — desempate "coincidencia exacta" de la cascada."""
    return _aplicar_sinonimos(_normalizar(_expandir_abreviaturas(_limpiar_puntuacion(nombre or ""))))


def _pocos_tokens_significativos(texto: str) -> bool:
    """True si `texto` tiene menos de 2 tokens significativos (≥3 chars) y ningún número.

    Reusa el mismo pipeline de normalización y el mismo umbral que la heurística de ambigüedad
    de `buscar_camara()` — una línea que caería en `AmbiguousSearchError(cantidad=0)` es, por
    definición, demasiado corta/insuficiente para ser un nombre de cámara completo.
    """
    limpio = _limpiar_puntuacion(texto)
    expandido = _expandir_abreviaturas(limpio)
    norm = _aplicar_sinonimos(_normalizar(expandido))
    numeros = re.findall(r"\d+", norm)
    tokens_sig = [t for t in norm.split() if len(t) >= 3]
    return len(tokens_sig) < 2 and not numeros


def extraer_nombre_camara(mensaje: str) -> str:
    """Extrae el nombre de cámara del mensaje.

    Prioridad:
      1. Formato Workflow: ``*Nombre: Nodo/Camara/botella*\\n[valor]``
      2. Campo libre: ``Cámara: [valor]``
      3. Fallback: primera línea del mensaje.

    Si la primera línea del formato Workflow resulta insuficiente (`_pocos_tokens_significativos`),
    se asume que es un salto de línea accidental del técnico al copiar/pegar y se extiende la
    captura a las líneas siguientes hasta el próximo campo (`_RE_NOMBRE_WORKFLOW_EXTENDIDO`).
    """
    match = _RE_NOMBRE_WORKFLOW.search(mensaje)
    if match:
        primera_linea = match.group(1).strip()
        if _pocos_tokens_significativos(primera_linea):
            match_extendido = _RE_NOMBRE_WORKFLOW_EXTENDIDO.search(mensaje)
            if match_extendido:
                extendido = re.sub(r"\s*\n\s*", " ", match_extendido.group(1)).strip()
                # Una primera línea de basura de copy/paste ("me:", caso real 2026-09-15/17, 5 filas)
                # no es parte del nombre: sin esto "me: Cra Acevedo 396 CF" no matchea.
                return _RE_PREFIJO_BASURA.sub("", extendido)
        return primera_linea
    match = _RE_CAMPO_CAMARA.search(mensaje)
    if match:
        return match.group(1).strip()
    # Fallback: usar solo la primera línea del mensaje
    return mensaje.split("\n")[0].strip()


def extraer_tipo_movimiento(mensaje: str) -> str | None:
    """Extrae el tipo de movimiento (Ingreso o Egreso) del mensaje del Workflow.

    Retorna exactamente ``"Ingreso"`` o ``"Egreso"`` si el campo está presente, ``None`` si no.
    """
    match = _RE_TIPO_MOVIMIENTO_WORKFLOW.search(mensaje)
    if match:
        # El regex es (?i): group(1) preserva el casing tal como llegó en la fuente
        # (ej. "ingreso", "INGRESO"), NO el casing literal del patrón. Normalizar acá
        # es obligatorio porque `registrar_movimiento_ingreso` hace un chequeo de
        # string exacto contra "Ingreso" y trata cualquier otro valor como Egreso —
        # sin este .capitalize(), un "ingreso" en minúsculas del Workflow de Slack
        # se registraría silenciosamente como Egreso.
        return match.group(1).capitalize()
    return None


def extraer_slack_user_id_autorizacion(mensaje: str) -> str | None:
    """Extrae el Slack user ID de la mención de persona que solicitó la autorización.

    Retorna el ID del usuario (ej. ``U0AUB6CRE4A``) sin el nombre mostrado, ``None`` si no existe.
    """
    match = _RE_PERSONA_AUTORIZACION_WORKFLOW.search(mensaje)
    if match:
        return match.group(1)
    return None


class AmbiguousSearchError(Exception):
    """Se lanza cuando la búsqueda de cámara no puede identificar una entidad unívoca.

    Cubre dos casos:

    * **Nombre insuficiente** (``cantidad == 0``): el string tiene menos de 2
      tokens significativos y ningún número; es imposible hacer una búsqueda
      precisa sin consultar la DB.
    * **Múltiples candidatos** (``cantidad > 1``): la cascada de búsqueda nunca
      redujo los resultados a exactamente una cámara.

    Attributes:
        nombre_raw:  Nombre original ingresado por el técnico.
        cantidad:    Número de candidatos encontrados (0 si el nombre es insuficiente).
        candidatos:  Lista de nombres de cámaras candidatas (hasta 3 — decisión de producto
                     2026-08-23: máximo 3 sugerencias en cualquier mensaje que use esta excepción).
    """

    def __init__(self, nombre_raw: str, cantidad: int, candidatos: list[str]) -> None:
        self.nombre_raw = nombre_raw
        self.cantidad = cantidad
        self.candidatos = candidatos[:3]
        super().__init__(
            f"Búsqueda ambigua: '{nombre_raw}' devuelve {cantidad} candidatos"
        )


class NumeroNoCoincideError(AmbiguousSearchError):
    """El texto trae números y ninguna cámara los tiene, pero sin esos números sí hay parecidas.

    Caso típico: el técnico escribió mal la altura ("Cra Mitre 404" para "Cra Mitre 440"). Las
    candidatas son SÓLO sugerencias — nunca se asigna automáticamente una cámara parecida (decisión
    del usuario 2026-10-23: "son pocos casos pero hay"). Es subclase de `AmbiguousSearchError` a
    propósito: todo caller que hoy trata la ambigüedad como "no se puede resolver" (revalidación,
    corrección, reproceso, baneo masivo) la sigue tratando igual sin cambios; sólo el listener la
    captura antes para responder "No encontré X con ese número. ¿Quisiste decir…?".

    ``cantidad`` es la cantidad de parecidas encontradas; ``candidatos`` las hasta 3 más similares.
    """


def buscar_camara(
    nombre_raw: str, session: Session, *, desempatar: bool = True
) -> tuple["Camara | None", str]:
    """Busca una cámara, intentando primero sólo con el texto antes del primer guión.

    Cuando el técnico pega en el Workflow el título completo que muestra Cromo para una Cámara/
    Botella (``<Nombre> - <Calle> <Altura> - <Localidad> - <Provincia>``, ver
    `docs/decisiones.md` entrada 2026-09-07, caso real "Cra Curupayti 2951 CF - CURUPAYTI 2964 -
    Capital Federal - Capital Federal"), todo lo posterior al primer guión son atributos de Cromo,
    no parte del nombre real. Por eso el primer intento usa sólo el prefijo antes del guión; si eso
    no resuelve a una única cámara (ni matchea, ni es ambiguo), se reintenta con el string completo
    — esto preserva casos donde el sufijo SÍ es parte legítima del nombre real y necesaria para
    desambiguar (ej. "Poste Lavalle - Campana", ver `TestLimpiarRuidoOperativo
    .test_localidad_con_guion_se_preserva`).

    Antes que nada (2026-10-23), el prefijo "Empalme <n_id de 8 dígitos>:" se resuelve por `n_id`
    de Cromo (`camara_por_prefijo_empalme`): si la Botella existe y tiene Cámara, es match directo;
    si no, se quita el prefijo y su número no cuenta como requerido.
    """
    botella, nombre_raw = camara_por_prefijo_empalme(nombre_raw, session)
    if botella is not None:
        return botella.camara, _aplicar_sinonimos(
            _normalizar(_expandir_abreviaturas(_limpiar_puntuacion(nombre_raw)))
        )
    nombre_raw = preparar_nombre_busqueda(nombre_raw)
    if "-" in nombre_raw:
        prefijo = nombre_raw.split("-", 1)[0].strip()
        if prefijo and prefijo != nombre_raw.strip() and not recorte_pierde_la_botella(prefijo, nombre_raw):
            try:
                # Sin desempate por coincidencia exacta: el prefijo es un RECORTE, y que una
                # candidata coincida exacto con el recorte no prueba nada ("terraza Viamonte 898-
                # Piso 4 C.F." terminaba en "terraza Viamonte 898" — medido 2026-09-28).
                camara, nombre_norm = _buscar_camara_intento(prefijo, session, desempate_exacto=False)
            except AmbiguousSearchError:
                pass  # el prefijo solo no alcanza — cae al intento con el string completo
            else:
                if camara is not None:
                    return camara, nombre_norm
    return _buscar_camara_intento(nombre_raw, session, desempate_exacto=desempatar)


def _tokens_significativos(texto: str) -> list[str]:
    """Tokens de `texto` con al menos 3 caracteres (umbral de la cascada)."""
    return [t for t in texto.split() if len(t) >= 3]


class _CascadaBusqueda:
    """Estado de una corrida de `_buscar_camara_intento`: restricciones del input y grupo ambiguo.

    Conserva el grupo más acotado (menos candidatos) que ningún intento pudo reducir a una sola.
    """

    def __init__(
        self, nombre_raw: str, session: Session, nombre_norm: str, desempate_exacto: bool
    ) -> None:
        self.nombre_raw = nombre_raw
        self.session = session
        self.nombre_norm = nombre_norm
        self.desempate_exacto = desempate_exacto
        # Números requeridos: si el input tiene "440", solo aceptamos cámaras con "440"
        self.numeros_requeridos: set[str] = set(re.findall(r"\d+", nombre_norm))
        # Bot/Botella: si el técnico lo menciona explícitamente, permitimos bots secundarios
        self.tiene_bot: bool = bool(re.search(r"\bbot(ella)?\b", nombre_raw, re.IGNORECASE))
        self.ambiguos: list["Camara"] = []

    def _filtrar(self, candidatos: list["Camara"]) -> list["Camara"]:
        candidatos = _filtrar_por_numeros(candidatos, self.numeros_requeridos)
        candidatos = _filtrar_bots_secundarios(candidatos, self.tiene_bot)
        return _filtrar_numero_de_botella(candidatos, self.nombre_raw)

    def candidatos_ilike(self, patron: str) -> list["Camara"]:
        return self._filtrar(_buscar_ilike_lista(patron, self.session))

    def candidatos_tokens(self, tokens: list[str]) -> list["Camara"]:
        return self._filtrar(_buscar_tokens_lista(tokens, self.session))

    def _desempatar_por_exacta(self, candidatos: list["Camara"]) -> "Camara | None":
        # Desempate (2026-09-28): si exactamente UNA candidata coincide por igualdad con la
        # entrada normalizada, es ésa — "Cra Libertad 991 CF" contra "BOTELLA CRITICA Cra
        # Libertad 991 CF". Dos o más exactas (duplicados reales del inventario, "X C.F." y
        # "X CF") siguen siendo ambiguas: nunca se elige entre dos Cámaras distintas.
        if not self.desempate_exacto or tiene_gemela_critica(candidatos):
            return None
        exactas = [c for c in candidatos if normalizar_candidato(c.nombre) == self.nombre_norm]
        return exactas[0] if len(exactas) == 1 else None

    def evaluar(self, candidatos: list["Camara"]) -> "Camara | None":
        if len(candidatos) == 1:
            return candidatos[0]
        if len(candidatos) > 1:
            elegida = self._desempatar_por_exacta(candidatos)
            if elegida is not None:
                return elegida
            if not self.ambiguos or len(candidatos) < len(self.ambiguos):
                self.ambiguos = candidatos
        return None

    def probar(self, patron: str) -> "Camara | None":
        """ILIKE con `patron` y, si hay 2+ tokens significativos, todos los tokens (AND)."""
        resultado = self.evaluar(self.candidatos_ilike(patron))
        if resultado:
            return resultado
        tokens = _tokens_significativos(patron)
        if len(tokens) >= 2:
            return self.evaluar(self.candidatos_tokens(tokens)) or None
        return None


# Tipo de elemento y descriptores que, solos, no identifican una calle: si al quitar los números
# del texto sólo quedan éstos ("Cra 440" → "cra"), no se buscan parecidas — serían miles.
_TOKENS_GENERICOS = frozenset({"cra", "bot", "poste", "tza", "calle", "avenida", "pasaje", "esq"})


def _parecidas_sin_numeros(cascada: _CascadaBusqueda) -> list["Camara"]:
    """Cámaras que coinciden con el texto SIN sus números (reemplaza al viejo Intento 3, que era
    inalcanzable: sólo corría cuando el texto no tenía números, y entonces no había nada que quitar).

    Sólo para un texto CON números al que los intentos 1, 2 y 4 no le encontraron nada. Se busca por
    tokens (AND ILIKE) sobre la forma expandida y la literal, con los mismos filtros de bot y de
    número de botella que la cascada — pero sin el de números, que es justamente el que no coincide.
    Si sin los números quedan menos de 2 tokens significativos, o sólo tokens genéricos ("cra",
    "calle"), no se busca nada. Devuelve las candidatas ordenadas de más a menos parecidas al texto;
    NUNCA se usan como match (ver `NumeroNoCoincideError`)."""
    literal = _aplicar_sinonimos(_normalizar(_limpiar_puntuacion(cascada.nombre_raw)))
    vistas: dict[int, "Camara"] = {}
    for texto in dict.fromkeys((cascada.nombre_norm, literal)):
        sin_numeros = re.sub(r"\s+", " ", re.sub(r"\d+", " ", texto)).strip()
        tokens = _tokens_significativos(sin_numeros)
        if len(tokens) < 2 or set(tokens) <= _TOKENS_GENERICOS:
            continue
        candidatas = _buscar_tokens_lista(tokens, cascada.session)
        candidatas = _filtrar_bots_secundarios(candidatas, cascada.tiene_bot)
        for camara in _filtrar_numero_de_botella(candidatas, cascada.nombre_raw):
            vistas.setdefault(camara.id, camara)

    def _similitud(camara: "Camara") -> float:
        return SequenceMatcher(None, cascada.nombre_norm, normalizar_candidato(camara.nombre)).ratio()

    return sorted(vistas.values(), key=lambda c: (-_similitud(c), len(c.nombre or ""), c.id))


def _intento_sin_expansion(cascada: _CascadaBusqueda) -> tuple["Camara | None", str]:
    """Intento 4: nombre raw normalizado SIN expansión de abreviaturas.

    Cubre el caso en que la DB almacena el nombre con abreviaturas literales.
    """
    nombre_raw_norm = _aplicar_sinonimos(_normalizar(_limpiar_puntuacion(cascada.nombre_raw)))
    if nombre_raw_norm != cascada.nombre_norm:
        return cascada.probar(nombre_raw_norm), nombre_raw_norm
    return None, nombre_raw_norm


def _buscar_camara_intento(
    nombre_raw: str, session: Session, *, desempate_exacto: bool = True
) -> tuple["Camara | None", str]:
    """Busca una cámara en DB tolerando abreviaturas, sinónimos y variaciones ortográficas.

    Preprocesamiento:
      - Limpieza de puntuación (comas, puntos, guiones separadores)
      - Expansión de abreviaturas viales (av→avenida, clle→calle, etc.)
      - Normalización (unidecode + lowercase)
      - Aplicación de sinónimos (botella→bot, camara→cra)

    Regla de numeración:
      Si el input contiene números, solo se aceptan cámaras cuyo nombre los
      contenga exactamente (como palabras completas). Una cámara con otro número
      nunca es match (ej: 440 ≠ 399): a lo sumo es una sugerencia (Intento 3).

    Regla de Botella/Bot:
      Si el input NO menciona explícitamente "bot" o "botella", se excluyen
      resultados de cámaras secundarias tipo "Bot 2", "Bot 3", etc.

    Estrategia en cascada:
      1. ILIKE '%nombre_norm%' en Camara.nombre y CamaraAlias.alias_nombre
      2. Todos los tokens (≥3 chars) presentes — AND ILIKE
      4. Fallback con nombre raw normalizado SIN expansión (para abreviaturas
         almacenadas literalmente en DB, p.ej. "Cra")
      3. Se evalúa al final, después del 4 (desde 2026-10-23): si el input
         TIENE números y ningún intento encontró nada —ni siquiera un grupo
         ambiguo—, se buscan parecidas sin esos números
         (`_parecidas_sin_numeros`). Si hay, se lanza ``NumeroNoCoincideError``
         con hasta 3 sugerencias; nunca se asigna una.

    Filtro de ambigüedad:
      - Heurística previa: si hay < 2 tokens significativos (≥3 chars) y ningún
        número, se lanza ``AmbiguousSearchError(cantidad=0)`` sin consultar la DB.
      - Si algún intento de la cascada devuelve múltiples candidatos (tras los
        filtros de números y bots) y ningún intento posterior los reduce a 1,
        se lanza ``AmbiguousSearchError`` con el grupo más acotado encontrado.

    Args:
        nombre_raw: Nombre extraído del mensaje (sin normalizar).
        session:    Sesión SQLAlchemy activa.

    Returns:
        Tupla ``(camara, nombre_normalizado_usado)`` cuando se identifica
        exactamente una cámara, o ``(None, nombre_norm)`` cuando no se encontró
        ninguna (flujo de auto-registro).

    Raises:
        AmbiguousSearchError: Cuando el nombre es ambiguo o insuficientemente
            específico para identificar una cámara de forma unívoca.
        NumeroNoCoincideError: (subclase) Cuando el número del input no coincide
            con ninguna cámara pero sin él hay parecidas (sólo sugerencias).
    """
    # ── Pre-proceso ──────────────────────────────────────────────────────
    nombre_limpio = _limpiar_puntuacion(nombre_raw)
    nombre_expandido = _expandir_abreviaturas(nombre_limpio)
    nombre_norm = _aplicar_sinonimos(_normalizar(nombre_expandido))
    cascada = _CascadaBusqueda(nombre_raw, session, nombre_norm, desempate_exacto)

    # ── Heurística pre-búsqueda: nombre insuficientemente específico ──────
    if len(_tokens_significativos(nombre_norm)) < 2 and not cascada.numeros_requeridos:
        raise AmbiguousSearchError(nombre_raw, 0, [])

    # ── Intentos 1 y 2: nombre normalizado completo y todos sus tokens ───
    resultado = cascada.probar(nombre_norm)
    if resultado:
        return resultado, nombre_norm
    # ── Intento 4 (sin expansión) ────────────────────────────────────────
    resultado, nombre_usado = _intento_sin_expansion(cascada)
    if resultado:
        return resultado, nombre_usado

    # ── Resolución final: múltiples candidatos sin reducir a 1 → ambiguo ─
    if cascada.ambiguos:
        nombres_candidatos = [c.nombre for c in cascada.ambiguos[:3]]
        raise AmbiguousSearchError(nombre_raw, len(cascada.ambiguos), nombres_candidatos)

    # ── Intento 3: el número no coincide con ninguna → sólo sugerencias ──
    if cascada.numeros_requeridos:
        parecidas = _parecidas_sin_numeros(cascada)
        if parecidas:
            raise NumeroNoCoincideError(nombre_raw, len(parecidas), [c.nombre for c in parecidas[:3]])
    return None, nombre_norm


def _filtrar_por_numeros(
    candidatos: list["Camara"], numeros_requeridos: set[str]
) -> list["Camara"]:
    """Descarta candidatos cuyo nombre no contenga todos los números requeridos.

    Usa coincidencia de número completo (``(?<!\\d)<n>(?!\\d)``) sobre el nombre
    normalizado.  Si ``numeros_requeridos`` está vacío, retorna la lista sin
    cambios.
    """
    if not numeros_requeridos:
        return candidatos
    resultado: list["Camara"] = []
    for cam in candidatos:
        nombre_norm = _normalizar(cam.nombre or "")
        if all(_contiene_numero(nombre_norm, n) for n in numeros_requeridos):
            resultado.append(cam)
    return resultado


def _contiene_numero(nombre_norm: str, numero: str) -> bool:
    """`numero` aparece en `nombre_norm` como número completo.

    Desde 2026-09-28, sin `\b` a la izquierda para números de 3+ dígitos: con `\b`, "197" nunca
    matcheaba "(R197)" ni "99" matcheaba "99B", y el nombre EXACTO del inventario se descartaba a sí
    mismo. Un número corto (1-2 dígitos) sí exige que no lo preceda una letra —salvo "bot"— porque ahí
    la letra delante casi siempre es otro dato: el "2" de "Bot 2" no puede satisfacerse con el "P2"
    (piso) de otra cámara (hallazgo de la revisión de la rama, caso real "Bot 2 Interiror Parana 3745
    P2 - Unicenter"). Nunca acepta "440" dentro de "4400"."""
    for m in re.finditer(rf"(?<!\d){re.escape(numero)}(?!\d)", nombre_norm):
        if len(numero) >= 3:
            return True
        previo = nombre_norm[: m.start()]
        if not previo or not previo[-1].isalpha() or re.search(r"bot\.?$", previo):
            return True
    return False


_RE_NUMERO_BOTELLA = re.compile(r"(?i)\bbot(?:ella)?\.?\s*([1-9])(?!\d)")


def _filtrar_numero_de_botella(candidatos: list["Camara"], nombre_raw: str) -> list["Camara"]:
    """Si el texto nombra una botella secundaria concreta ("Bot 2"), la candidata tiene que tener
    ESA botella — no alcanza con que el número aparezca en otra parte del nombre ("Ed 2", "Piso 2").

    Hallazgo de la revisión de la rama (2026-09-28): "Avalos 2829 Bot2 - Sala telefonia Ed 2 Subs"
    resolvía a "Bot. Avalos 2829 - Sala telefonia Ed 2 Subs VICE" (una botella sin número, de otra
    cámara) porque el "2" requerido lo aportaba "Ed 2". "Bot 1" no restringe: es la Cámara principal,
    cuyo nombre no lo lleva."""
    pedidos = {n for n in _RE_NUMERO_BOTELLA.findall(nombre_raw or "") if n != "1"}
    if not pedidos:
        return candidatos
    return [c for c in candidatos if pedidos <= set(_RE_NUMERO_BOTELLA.findall(c.nombre or ""))]


_RE_CRITICA = re.compile(r"(?i)cr[ií]tic")


def recorte_pierde_la_botella(prefijo: str, nombre_completo: str) -> bool:
    """True si el texto completo nombra una botella secundaria ("… - Bot 2") que el recorte antes
    del guion ya no incluye. Ese recorte describe OTRA cosa (la cámara, no la botella pedida) y no
    se prueba: en la revisión de la rama, "Cra Av Peron 7964 esq. Jose Maria Paz - Bot 2" resolvía
    por el recorte a otra cámara."""
    pedidos = {n for n in _RE_NUMERO_BOTELLA.findall(nombre_completo or "") if n != "1"}
    return bool(pedidos) and not pedidos <= set(_RE_NUMERO_BOTELLA.findall(prefijo or ""))


def tiene_gemela_critica(candidatos: list) -> bool:
    """True si alguna candidata es una variante "CRITICA" ("X - CRITICA", "BOTELLA CRITICA X").

    El listener quita el sufijo " - CRITICA" del texto ANTES de buscar (`limpiar_ruido_operativo`),
    así que la búsqueda no puede saber si el técnico pidió la crítica o la común: con una gemela
    crítica entre las candidatas, ningún desempate elige (hallazgo de la revisión de la rama: "Cra
    Diag Norte 902 Esq Suipacha - CRITICA" terminaba en la común, que además estaba BANEADA)."""
    return any(_RE_CRITICA.search(getattr(c, "nombre", None) or "") for c in candidatos)


def _filtrar_bots_secundarios(
    candidatos: list["Camara"], tiene_bot: bool
) -> list["Camara"]:
    """Si el usuario NO mencionó 'bot'/'botella', excluye cámaras tipo 'Bot 2', 'Bot 3', etc.

    Esto evita que "Cra Mitre 440" empareje "Bot 2 Cra Mitre 440" cuando el
    técnico claramente se refiere a la cámara principal.
    """
    if tiene_bot:
        return candidatos
    return [c for c in candidatos if not RE_BOT_SUFIJO.search(c.nombre or "")]


def _buscar_ilike_lista(patron: str, session: Session) -> list["Camara"]:
    """Query ILIKE '%patron%' sobre Camara.nombre y CamaraAlias.alias_nombre.

    Retorna lista de candidatos sin filtrar, deduplicada por id.
    """
    from db.models.infra import Camara, CamaraAlias

    # Búsqueda en nombre directo
    por_nombre = (
        session.query(Camara)
        .filter(func.unaccent(func.lower(Camara.nombre)).ilike(f"%{patron}%"))
        .all()
    )
    # Búsqueda en aliases (JOIN)
    por_alias = (
        session.query(Camara)
        .join(CamaraAlias, CamaraAlias.camara_id == Camara.id)
        .filter(func.unaccent(func.lower(CamaraAlias.alias_nombre)).ilike(f"%{patron}%"))
        .all()
    )
    # Deduplicar preservando orden
    seen: set[int] = set()
    result: list["Camara"] = []
    for c in por_nombre + por_alias:
        if c.id not in seen:
            seen.add(c.id)
            result.append(c)
    return result


def _buscar_tokens_lista(tokens: list[str], session: Session) -> list["Camara"]:
    """Busca cámaras cuyo nombre o algún alias contenga TODOS los tokens.

    Retorna lista de candidatos sin filtrar, deduplicada por id.
    """
    from db.models.infra import Camara, CamaraAlias
    from sqlalchemy import and_

    # En nombre directo
    condiciones_nombre = [
        func.unaccent(func.lower(Camara.nombre)).ilike(f"%{token}%")
        for token in tokens
    ]
    por_nombre = session.query(Camara).filter(and_(*condiciones_nombre)).all()

    # En aliases
    condiciones_alias = [
        func.unaccent(func.lower(CamaraAlias.alias_nombre)).ilike(f"%{token}%")
        for token in tokens
    ]
    por_alias = (
        session.query(Camara)
        .join(CamaraAlias, CamaraAlias.camara_id == Camara.id)
        .filter(and_(*condiciones_alias))
        .all()
    )
    # Deduplicar preservando orden
    seen: set[int] = set()
    result: list["Camara"] = []
    for c in por_nombre + por_alias:
        if c.id not in seen:
            seen.add(c.id)
            result.append(c)
    return result


def _buscar_ilike(patron: str, session: Session) -> "Camara | None":
    """Wrapper de _buscar_ilike_lista que aplica _mejor_candidato.

    Mantenido para compatibilidad con tests que parchean esta función.
    """
    return _mejor_candidato(_buscar_ilike_lista(patron, session))


def _buscar_tokens(tokens: list[str], session: Session) -> "Camara | None":
    """Wrapper de _buscar_tokens_lista que aplica _mejor_candidato.

    Mantenido para compatibilidad con tests que parchean esta función.
    """
    return _mejor_candidato(_buscar_tokens_lista(tokens, session))


def _mejor_candidato(candidatos: list["Camara"]) -> "Camara | None":
    """De una lista de candidatos retorna el de nombre más corto (mejor match)."""
    if not candidatos:
        return None
    return min(candidatos, key=lambda c: len(c.nombre))
