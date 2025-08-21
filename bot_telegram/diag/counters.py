# Nombre de archivo: counters.py
# Ubicación de archivo: bot_telegram/diag/counters.py
# Descripción: Contadores en memoria para diagnóstico del bot

from collections import defaultdict
from typing import Dict

_COUNTERS: Dict[str, int] = defaultdict(int)


def inc(name: str) -> None:
    """Incrementa el contador indicado."""
    _COUNTERS[name] += 1


def snapshot() -> Dict[str, int]:
    """Devuelve una copia de los contadores actuales."""
    return dict(_COUNTERS)
