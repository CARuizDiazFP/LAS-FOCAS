# Nombre de archivo: runner.py
# Ubicación de archivo: modules/comparador_fo/runner.py
# Descripción: Compara trazas FO mediante hash SHA256 para verificar diferencias

import hashlib
import logging
from typing import Dict

logger = logging.getLogger(__name__)


def run(traza_a: str, traza_b: str) -> Dict[str, object]:
    """Compara dos archivos de trazas FO.

    Calcula el hash SHA256 de cada archivo y determina si son idénticos.
    """
    with open(traza_a, "rb") as file_a:
        data_a = file_a.read()
    with open(traza_b, "rb") as file_b:
        data_b = file_b.read()

    hash_a = hashlib.sha256(data_a).hexdigest()
    hash_b = hashlib.sha256(data_b).hexdigest()
    iguales = hash_a == hash_b

    logger.info(
        "action=run hash_a=%s hash_b=%s iguales=%s", hash_a, hash_b, iguales
    )

    return {"hash_a": hash_a, "hash_b": hash_b, "iguales": iguales}
