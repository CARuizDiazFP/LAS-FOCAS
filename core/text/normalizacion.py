# Nombre de archivo: normalizacion.py
# Ubicación de archivo: core/text/normalizacion.py
# Descripción: Normalización pura de nombres de cámara/botella: puntuación, abreviaturas, sinónimos y preprocesado (sin DB)

from __future__ import annotations

import re

# ── Tabla de abreviaturas comunes usadas por técnicos ────────────────────
# NOTA: "Cra" NO está en esta tabla.  Los nombres de cámara almacenados en DB
# conservan "Cra" de forma literal (ej: "Bot 2 Cra Poste …"); expandirlo a
# "carrera" destruiría el match ILIKE.  El Intento 4 cubre este caso.
ABREVIATURAS: dict[str, str] = {
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
    # "C.F." escrito con puntos: `limpiar_puntuacion` ya convirtió cada punto en espacio, así que
    # llega como los dos tokens sueltos "c f" y el patrón `\bcf\b` de arriba no lo alcanza. Sin esta
    # entrada, "Cra X CF" y "Cra X C.F." normalizan distinto — medido contra prod el 2026-09-08: el
    # detector de Cámaras duplicadas informaba 0 grupos cuando había 96 pares que sólo difieren en eso.
    r"\bc\s+f\b": "",
}

# ── Diccionario de sinónimos (aplicado DESPUÉS de normalizar) ────────────
# Permite empatar variaciones semánticas frecuentes en escritura técnica.
# Se aplican sobre el texto ya en minúsculas y sin acentos (post-unidecode).
SINONIMOS: dict[str, str] = {
    r"\bbotella\b": "bot",    # "Botella" → "Bot" (prefijo de cámara)
    r"\bcamara\b": "cra",    # "camara" / "cámara" (post-unidecode) → "cra"
}

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
# `limpiar_puntuacion`/`normalizar`: esos dos también normalizan nombres del inventario para el
# detector de duplicados y la jerarquía Cámara/Botella, y cambiarlos movería grupos ya calculados.

# "bot2", "BOT2.", "bo2", "bot.2" → "Bot 2". Sin esto, `\bbot(ella)?\b` (detección de `tiene_bot`)
# no ve la botella — no hay límite de palabra entre "t" y "2" — y la cascada DESCARTA justamente las
# botellas secundarias (26 filas reales). Sólo con el número PEGADO: "Bot 2"/"Bot. 2" ya funcionaban.
# Un dígito y lookahead `(?!\d)`, mismo criterio que `RE_BOT_SUFIJO` ("Bot 30 de Septiembre").
RE_BOT_PEGADO = re.compile(r"(?i)\b(?:bot(?:ella)?|bo)\.?([1-9])(?!\d)")
# Letras seguidas de número sin espacio ("huergo701", "Solis1702") → "huergo 701". Mínimo 3 letras
# para no partir códigos cortos como "R197"/"F1" (ésos los cubre el filtro de números sin `\b`).
_RE_LETRAS_NUMERO = re.compile(r"(?<=[^\W\d_]{3})(?=\d)")
# "Bot 1"/"Botella 1": por convención la Botella 1 es la Cámara principal, cuyo nombre NO lleva
# "Bot 1" (ver `detectar_multi_bot`). Se quita sólo como SEGUNDO intento (`quitar_botella_uno`):
# hay nombres reales que sí lo llevan literal ("Cra Juan Domingo Peron 498 Bot 1 CF").
_RE_BOTELLA_UNO = re.compile(r"(?i)\bbot(?:ella)?\.?\s*1(?!\d)\.?")

# "Empalme 10245762: Cra 25 de Mayo 302" (caso real, 2026-10-23): el técnico antepone el `n_id` de
# Cromo de la Botella — "empalme" es como llaman a la Botella en la calle. 7 u 8 dígitos (prefijos
# reales de prod: 9429606, 9404415, 9542798, 9472462, 10245762; el `n_id` mínimo es 6.630.905, sin
# choque con el Fontaine ID, que llega a 1.274.823). Sólo al principio del texto: con la palabra
# "Empalme", seguido de ":"/"-" o del fin del texto; sin ella ("6635973: Cra …", también real),
# sólo seguido de ":"/"-". Siempre se corrobora contra el resto (`resto_corrobora_botella`).
_RE_PREFIJO_EMPALME = re.compile(
    r"(?i)^\s*(?:empalme\s*#?\s*(\d{7,8})\s*(?:[:\-–]\s*|$)|#?(\d{7,8})\s*[:\-–]\s*)"
)


def separar_prefijo_empalme(texto: str) -> tuple[int | None, str]:
    """``("Empalme 10245762: Cra X 1")`` → ``(10245762, "Cra X 1")``. Sin el prefijo devuelve
    ``(None, texto)`` sin cambios."""
    match = _RE_PREFIJO_EMPALME.match(texto or "")
    if not match:
        return None, texto
    return int(match.group(1) or match.group(2)), texto[match.end():].strip()


def preparar_nombre_busqueda(texto: str) -> str:
    """Normaliza las formas de escritura de la entrada que la cascada no resuelve: "bot" pegado al
    número y letras pegadas al número. Idempotente — se puede aplicar más de una vez sin efecto."""
    texto = RE_BOT_PEGADO.sub(lambda m: f"Bot {m.group(1)}", texto)
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

    base = RE_BOT_PEGADO.sub(lambda m: f"Bot {m.group(1)}", base)
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


def limpiar_puntuacion(texto: str) -> str:
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


def normalizar(texto: str) -> str:
    """Normaliza texto: sin acentos, minúsculas, espacios simples."""
    try:
        from unidecode import unidecode
        texto = unidecode(texto)
    except ImportError:
        pass
    texto = texto.lower().strip()
    texto = re.sub(r"\s+", " ", texto)
    return texto


def aplicar_sinonimos(texto_norm: str) -> str:
    """Aplica el diccionario de sinónimos sobre texto ya normalizado (lowercase, sin acentos)."""
    for patron, reemplazo in SINONIMOS.items():
        texto_norm = re.sub(patron, reemplazo, texto_norm, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", texto_norm).strip()


def expandir_abreviaturas(texto: str) -> str:
    """Reemplaza abreviaturas comunes por su forma completa."""
    for patron, reemplazo in ABREVIATURAS.items():
        texto = re.sub(patron, reemplazo, texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def expandir_abreviaturas_y_sinonimos(texto_normalizado: str) -> str:
    """Aplica sobre un texto YA normalizado (unaccent+lowercase+sin puntuación — ej. la salida de
    `camara_hierarchy_service.normalizar_para_agrupar`) la misma expansión de abreviaturas viales y
    sinónimos que ya usa `buscar_camara()` para texto libre de técnicos — reusa `ABREVIATURAS`/
    `SINONIMOS` sin duplicar las tablas. Pensada para detectar candidatas a duplicado entre nombres
    ya estructurados de la DB (`core/services/camara_duplicados_service.py`), no sólo texto libre."""
    return aplicar_sinonimos(expandir_abreviaturas(texto_normalizado))


def normalizar_candidato(nombre: str) -> str:
    """Pipeline completo de normalización (puntuación → abreviaturas → minúsculas/acentos →
    sinónimos) aplicado a un nombre del inventario, para compararlo por igualdad contra la entrada
    ya normalizada — desempate "coincidencia exacta" de la cascada."""
    return aplicar_sinonimos(normalizar(expandir_abreviaturas(limpiar_puntuacion(nombre or ""))))


def pocos_tokens_significativos(texto: str) -> bool:
    """True si `texto` tiene menos de 2 tokens significativos (≥3 chars) y ningún número.

    Reusa el mismo pipeline de normalización y el mismo umbral que la heurística de ambigüedad
    de `buscar_camara()` — una línea que caería en `AmbiguousSearchError(cantidad=0)` es, por
    definición, demasiado corta/insuficiente para ser un nombre de cámara completo.
    """
    limpio = limpiar_puntuacion(texto)
    expandido = expandir_abreviaturas(limpio)
    norm = aplicar_sinonimos(normalizar(expandido))
    numeros = re.findall(r"\d+", norm)
    tokens_sig = [t for t in norm.split() if len(t) >= 3]
    return len(tokens_sig) < 2 and not numeros


def tokens_significativos(texto: str) -> list[str]:
    """Tokens de `texto` con al menos 3 caracteres (umbral de la cascada)."""
    return [t for t in texto.split() if len(t) >= 3]


RE_NUMERO_BOTELLA = re.compile(r"(?i)\bbot(?:ella)?\.?\s*([1-9])(?!\d)")
