# Nombre de archivo: action_classifier.py
# Ubicación de archivo: nlp_intent/app/action_classifier.py
# Descripción: Sub-clasificador de acciones solicitadas (fase 2)

from __future__ import annotations

import re
from dataclasses import dataclass
from .config import settings

RE_REPETITIVIDAD = re.compile(r"(repetitiv|repetitivi|repetitidad|repetitividad)")
RE_VERB = re.compile(r"\b(gener(ar|á)|arm(ar|á)|crear|creá|producir|emitir|sacar|obtener)\b")

@dataclass
class ActionResult:
    action_code: str
    confidence: float
    reason: str


def classify_action(text: str) -> ActionResult:
    """Clasifica una acción a un action_code.

    Heurística inicial: sólo soportamos repetitividad.
    """
    score = 0.0
    reasons: list[str] = []
    if RE_REPETITIVIDAD.search(text):
        score += 0.6
        reasons.append("keyword:repetitividad")
    if RE_VERB.search(text):
        score += 0.3
        reasons.append("verb:accion")
    if score >= 0.75:
        return ActionResult("repetitividad_report", min(score, 0.99), ",".join(reasons))
    return ActionResult("unsupported", score, ",".join(reasons) or "no_match")
