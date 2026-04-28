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
from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from db.models.infra import Camara

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
# Regex fallback: campo libre "Cámara: [valor]"
_RE_CAMPO_CAMARA = re.compile(r"(?i)c[aá]maras?\s*:\s*(.+?)(?:\n|$)")

# Detecta menciones del tipo "Botella 1 y 2", "Bot 1 y 2", "botellas 2 y 3", etc.
# Captura los dos números para expandirlos en búsquedas independientes.
_RE_MULTI_BOT = re.compile(
    r"(?i)\bbot(?:ella)?s?\s+(\d+)\s+(?:y|&)\s+(\d+)\b"
)


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
    # Eliminar puntuación sobrante (comas, puntos aislados, punto y coma)
    base = re.sub(r"[,;]", " ", base)
    base = re.sub(r"(?<!\d)\.(?!\d)", " ", base)
    base = re.sub(r"\s+", " ", base).strip().strip(".")

    nombres: list[str] = []
    for n in sorted({n1, n2}):
        if n == 1:
            # Botella 1 = cámara principal sin prefijo Bot
            nombres.append(base)
        else:
            nombres.append(f"Bot {n} {base}")
    return nombres


def _limpiar_puntuacion(texto: str) -> str:
    """Elimina signos de puntuación irrelevantes antes de normalizar.

    - Comas, punto y coma, puntos NO precedidos de dígitos (para preservar
      decimales como "7.06 dB").
    - Guiones rodeados de espacios (" - ") → espacio simple.
    - Normaliza espacios múltiples resultantes.
    """
    # Punto y coma y comas → espacio
    texto = re.sub(r"[,;]", " ", texto)
    # Punto al final de palabra (no entre dígitos) → espacio
    texto = re.sub(r"(?<!\d)\.(?!\d)", " ", texto)
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


def extraer_nombre_camara(mensaje: str) -> str:
    """Extrae el nombre de cámara del mensaje.

    Prioridad:
      1. Formato Workflow: ``*Nombre: Nodo/Camara/botella*\\n[valor]``
      2. Campo libre: ``Cámara: [valor]``
      3. Fallback: primera línea del mensaje.
    """
    match = _RE_NOMBRE_WORKFLOW.search(mensaje)
    if match:
        return match.group(1).strip()
    match = _RE_CAMPO_CAMARA.search(mensaje)
    if match:
        return match.group(1).strip()
    # Fallback: usar solo la primera línea del mensaje
    return mensaje.split("\n")[0].strip()


def buscar_camara(nombre_raw: str, session: Session) -> tuple["Camara | None", str]:
    """Busca una cámara en DB tolerando abreviaturas, sinónimos y variaciones ortográficas.

    Preprocesamiento:
      - Limpieza de puntuación (comas, puntos, guiones separadores)
      - Expansión de abreviaturas viales (av→avenida, clle→calle, etc.)
      - Normalización (unidecode + lowercase)
      - Aplicación de sinónimos (botella→bot, camara→cra)

    Regla de numeración:
      Si el input contiene números, solo se aceptan cámaras cuyo nombre los
      contenga exactamente (como palabras completas).  El Intento 3 (búsqueda
      sin números) se omite para evitar falsos positivos (ej: 440 ≠ 399).

    Regla de Botella/Bot:
      Si el input NO menciona explícitamente "bot" o "botella", se excluyen
      resultados de cámaras secundarias tipo "Bot 2", "Bot 3", etc.

    Estrategia en cascada:
      1. ILIKE '%nombre_norm%' en Camara.nombre y CamaraAlias.alias_nombre
      2. Todos los tokens (≥3 chars) presentes — AND ILIKE
      3. Reintentar sin números (SOLO si el input no tenía números)
      4. Fallback con nombre raw normalizado SIN expansión (para abreviaturas
         almacenadas literalmente en DB, p.ej. "Cra")

    Args:
        nombre_raw: Nombre extraído del mensaje (sin normalizar).
        session:    Sesión SQLAlchemy activa.

    Returns:
        Tupla ``(camara_o_None, nombre_normalizado_usado)``.
        Si hay múltiples candidatos se retorna el de nombre más corto.
    """
    # ── Pre-proceso ──────────────────────────────────────────────────────
    nombre_limpio = _limpiar_puntuacion(nombre_raw)
    nombre_expandido = _expandir_abreviaturas(nombre_limpio)
    nombre_norm_base = _normalizar(nombre_expandido)
    nombre_norm = _aplicar_sinonimos(nombre_norm_base)

    # ── Restricciones extraídas del input original ───────────────────────
    # Números requeridos: si el input tiene "440", solo aceptamos cámaras con "440"
    numeros_requeridos: set[str] = set(re.findall(r"\d+", nombre_norm))
    # Bot/Botella: si el técnico lo menciona explícitamente, permitimos bots secundarios
    tiene_bot: bool = bool(re.search(r"\bbot(ella)?\b", nombre_raw, re.IGNORECASE))

    def _buscar_filtrado_ilike(patron: str) -> "Camara | None":
        candidatos = _buscar_ilike_lista(patron, session)
        candidatos = _filtrar_por_numeros(candidatos, numeros_requeridos)
        candidatos = _filtrar_bots_secundarios(candidatos, tiene_bot)
        return _mejor_candidato(candidatos)

    def _buscar_filtrado_tokens(tokens: list[str]) -> "Camara | None":
        candidatos = _buscar_tokens_lista(tokens, session)
        candidatos = _filtrar_por_numeros(candidatos, numeros_requeridos)
        candidatos = _filtrar_bots_secundarios(candidatos, tiene_bot)
        return _mejor_candidato(candidatos)

    # ── Intento 1: coincidencia parcial normalizada ──────────────────────
    resultado = _buscar_filtrado_ilike(nombre_norm)
    if resultado:
        return resultado, nombre_norm

    # ── Intento 2: todos los tokens presentes ────────────────────────────
    tokens = [t for t in nombre_norm.split() if len(t) >= 3]
    if len(tokens) >= 2:
        resultado = _buscar_filtrado_tokens(tokens)
        if resultado:
            return resultado, nombre_norm

    # ── Intento 3: sin números (OMITIDO si el input tenía números) ───────
    # Si el input tiene números, no ampliar la búsqueda sin ellos para evitar
    # emparejar "Cra Mitre 440" con "Cra Mitre 399".
    if not numeros_requeridos:
        nombre_sin_num = re.sub(r"\d+", "", nombre_norm).strip()
        nombre_sin_num = re.sub(r"\s+", " ", nombre_sin_num).strip()
        if nombre_sin_num and nombre_sin_num != nombre_norm:
            resultado = _buscar_filtrado_ilike(nombre_sin_num)
            if resultado:
                return resultado, nombre_sin_num
            tokens_sin_num = [t for t in nombre_sin_num.split() if len(t) >= 3]
            if len(tokens_sin_num) >= 2:
                resultado = _buscar_filtrado_tokens(tokens_sin_num)
                if resultado:
                    return resultado, nombre_sin_num

    # ── Intento 4: sin expansión de abreviaturas (nombre raw normalizado) ─
    # Cubre el caso en que la DB almacena el nombre con abreviaturas literales.
    nombre_raw_norm = _aplicar_sinonimos(_normalizar(_limpiar_puntuacion(nombre_raw)))
    if nombre_raw_norm != nombre_norm:
        resultado = _buscar_filtrado_ilike(nombre_raw_norm)
        if resultado:
            return resultado, nombre_raw_norm
        tokens_raw = [t for t in nombre_raw_norm.split() if len(t) >= 3]
        if len(tokens_raw) >= 2:
            resultado = _buscar_filtrado_tokens(tokens_raw)
            if resultado:
                return resultado, nombre_raw_norm

    return None, nombre_norm


def _filtrar_por_numeros(
    candidatos: list["Camara"], numeros_requeridos: set[str]
) -> list["Camara"]:
    """Descarta candidatos cuyo nombre no contenga todos los números requeridos.

    Usa coincidencia de palabra completa (``\\b<n>\\b``) sobre el nombre
    normalizado.  Si ``numeros_requeridos`` está vacío, retorna la lista sin
    cambios.
    """
    if not numeros_requeridos:
        return candidatos
    resultado: list["Camara"] = []
    for cam in candidatos:
        nombre_norm = _normalizar(cam.nombre or "")
        if all(re.search(rf"\b{re.escape(n)}\b", nombre_norm) for n in numeros_requeridos):
            resultado.append(cam)
    return resultado


def _filtrar_bots_secundarios(
    candidatos: list["Camara"], tiene_bot: bool
) -> list["Camara"]:
    """Si el usuario NO mencionó 'bot'/'botella', excluye cámaras tipo 'Bot 2', 'Bot 3', etc.

    Esto evita que "Cra Mitre 440" empareje "Bot 2 Cra Mitre 440" cuando el
    técnico claramente se refiere a la cámara principal.
    """
    if tiene_bot:
        return candidatos
    _re_bot_sec = re.compile(r"\bbot\s+[2-9]\b", re.IGNORECASE)
    return [c for c in candidatos if not _re_bot_sec.search(c.nombre or "")]


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
