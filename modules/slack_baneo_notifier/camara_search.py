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
_ABREVIATURAS: dict[str, str] = {
    r"\bcra\b": "carrera",
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

# Regex para extraer nombre de cámara del mensaje estructurado del Workflow
_RE_CAMPO_CAMARA = re.compile(r"(?i)c[aá]maras?\s*:\s*(.+?)(?:\n|$)")


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


def _expandir_abreviaturas(texto: str) -> str:
    """Reemplaza abreviaturas comunes por su forma completa."""
    for patron, reemplazo in _ABREVIATURAS.items():
        texto = re.sub(patron, reemplazo, texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def extraer_nombre_camara(mensaje: str) -> str:
    """Extrae el nombre de cámara del mensaje del Workflow.

    Si el mensaje tiene el campo "Cámara: [valor]" lo extrae;
    si no, devuelve el mensaje completo como fallback.
    """
    match = _RE_CAMPO_CAMARA.search(mensaje)
    if match:
        return match.group(1).strip()
    # Fallback: usar solo la primera línea del mensaje
    return mensaje.split("\n")[0].strip()


def buscar_camara(nombre_raw: str, session: Session) -> tuple["Camara | None", str]:
    """Busca una cámara en DB tolerando abreviaturas y variaciones ortográficas.

    Estrategia en cascada:
      1. ILIKE exacto sobre el nombre normalizado
      2. Cada token del query presente en el nombre (AND ILIKE)
      3. Reintentar sin números si el query tenía números

    Args:
        nombre_raw: Nombre extraído del mensaje (sin normalizar).
        session:    Sesión SQLAlchemy activa.

    Returns:
        Tupla ``(camara_o_None, nombre_normalizado_usado)``.
        Si hay múltiples candidatos se retorna el de nombre más corto.
    """
    from db.models.infra import Camara

    nombre_expandido = _expandir_abreviaturas(nombre_raw)
    nombre_norm = _normalizar(nombre_expandido)

    # ── Intento 1: coincidencia parcial normalizada ──────────────────────
    resultado = _buscar_ilike(nombre_norm, session)
    if resultado:
        return resultado, nombre_norm

    # ── Intento 2: todos los tokens presentes ────────────────────────────
    tokens = [t for t in nombre_norm.split() if len(t) >= 3]
    if len(tokens) >= 2:
        resultado = _buscar_tokens(tokens, session)
        if resultado:
            return resultado, nombre_norm

    # ── Intento 3: sin números ───────────────────────────────────────────
    nombre_sin_num = re.sub(r"\d+", "", nombre_norm).strip()
    nombre_sin_num = re.sub(r"\s+", " ", nombre_sin_num).strip()
    if nombre_sin_num and nombre_sin_num != nombre_norm:
        resultado = _buscar_ilike(nombre_sin_num, session)
        if resultado:
            return resultado, nombre_sin_num
        tokens_sin_num = [t for t in nombre_sin_num.split() if len(t) >= 3]
        if len(tokens_sin_num) >= 2:
            resultado = _buscar_tokens(tokens_sin_num, session)
            if resultado:
                return resultado, nombre_sin_num

    return None, nombre_norm


def _buscar_ilike(patron: str, session: Session) -> "Camara | None":
    """Query ILIKE '%patron%' sobre Camara.nombre normalizado."""
    from db.models.infra import Camara

    candidatos = (
        session.query(Camara)
        .filter(func.unaccent(func.lower(Camara.nombre)).ilike(f"%{patron}%"))
        .all()
    )
    return _mejor_candidato(candidatos)


def _buscar_tokens(tokens: list[str], session: Session) -> "Camara | None":
    """Busca cámaras cuyo nombre contenga TODOS los tokens dados."""
    from db.models.infra import Camara
    from sqlalchemy import and_

    condiciones = [
        func.unaccent(func.lower(Camara.nombre)).ilike(f"%{token}%")
        for token in tokens
    ]
    candidatos = session.query(Camara).filter(and_(*condiciones)).all()
    return _mejor_candidato(candidatos)


def _mejor_candidato(candidatos: list["Camara"]) -> "Camara | None":
    """De una lista de candidatos retorna el de nombre más corto (mejor match)."""
    if not candidatos:
        return None
    return min(candidatos, key=lambda c: len(c.nombre))
