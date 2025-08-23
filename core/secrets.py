# Nombre de archivo: secrets.py
# Ubicación de archivo: core/secrets.py
# Descripción: Utilidades para cargar secretos desde variables de entorno o Docker secrets

"""Funciones para leer secretos de variables de entorno o archivos en `/run/secrets`.

Estas utilidades permiten que los servicios utilicen Docker Secrets sin cambiar
las variables de entorno existentes. Si la variable no está definida, se busca
un archivo con el mismo nombre (en minúsculas) dentro de `/run/secrets`.
"""

from pathlib import Path
from typing import Optional
import os


def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Obtiene el secreto `name` desde variables de entorno o `/run/secrets`.

    Parameters
    ----------
    name:
        Nombre de la variable de entorno a buscar.
    default:
        Valor a retornar si no se encuentra el secreto.

    Returns
    -------
    Optional[str]
        Valor del secreto o `default` si no está disponible.
    """

    value = os.getenv(name)
    if value:
        return value

    secret_file = Path("/run/secrets") / name.lower()
    try:
        return secret_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return default
