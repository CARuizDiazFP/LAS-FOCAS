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


