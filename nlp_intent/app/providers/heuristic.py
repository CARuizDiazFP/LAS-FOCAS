# Nombre de archivo: heuristic.py
# Ubicación de archivo: nlp_intent/app/providers/heuristic.py
# Descripción: Clasificador basado en reglas simples para determinar la intención

from __future__ import annotations

import re
from typing import Tuple

ACTION_PATTERNS = re.compile(
    r"\b(generar|generá|crear|creá|enviar|enviá|ejecutar|ejecutá|calcular|calculá|correr|corré|iniciar|iniciá|preparar|prepará|procesar|procesá|arma|armar|armá|comparar|compará|actualizar|actualizá|migrar|migrá)\b"
)
CONSULTA_PATTERNS = re.compile(
    r"(\b(cómo|como|qué|que|cuándo|dónde|por\ qué|podés\ explicarme)\b|\?)"
)
OTROS_PATTERNS = re.compile(r"\b(hola|buen\s*día|gracias|qué\s*onda|buenas)\b")


def classify(text: str) -> Tuple[str, float]:
    """Clasifica texto usando reglas sencillas."""
    if ACTION_PATTERNS.search(text):
        return "Acción", 0.9
    if CONSULTA_PATTERNS.search(text):
        return "Consulta", 0.9
    if OTROS_PATTERNS.search(text):
        return "Otros", 0.8
    return "Otros", 0.5


def clarify_question(text: str, max_words: int = 6) -> str:
    """Genera una pregunta simple de aclaración basada en un fragmento inicial.

    No usa LLM; útil como fallback económico.
    """
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    fragment = " ".join(words[:max_words]) if words else "tu mensaje"
    return f"¿Podrías dar más detalles sobre '{fragment}'?"


