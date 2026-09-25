# Nombre de archivo: config.py
# Ubicación de archivo: core/services/cromo/config.py
# Descripción: Configuración desde entorno para el acceso de sólo lectura a la API de Cromo Red, con validación al arranque

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from core.config import get_secret

logger = logging.getLogger(__name__)

_RUTA_SERVIDOR_DEFAULT = "/cromo-api/v1/server"
_TIMEOUT_DEFAULT = 30.0
_PSIZE_DEFAULT = 5
# Valores permitidos para psize, decididos por el dueño del producto tras medir peso de
# página real contra Cromo (ver docs/Doc Privada/ingesta_cromo.md capítulo 12.2): psize=5
# es el default de producción; el resto queda disponible para ajustar por corrida en las
# etapas siguientes (servicio de ingesta, API, interfaz).
PSIZE_PERMITIDOS = frozenset({1, 5, 10, 20, 50})
_OAUTH_PUERTO_DEFAULT = 9999
_OAUTH_PATH_DEFAULT = "/oauth2/oauth/token"
# Valores por defecto de fábrica documentados en el manual de la API (OAUTH_CLIENT_DETAILS).
# Sólo aplican si Metrotel no los rotó al desplegar Cromo Red — ver docs/modulo_ingesta_cromo.md.
_CLIENT_ID_DEFAULT = "clientId"
_CLIENT_SECRET_DEFAULT = "secret"
# Parámetros propios de `GET /network/fo/{id}/path` (camino óptico), separados de los generales
# porque ese endpoint resuelve el grafo de la fibra en memoria del lado de Cromo y no se parece a
# ninguna otra llamada del cliente (ver docs/Doc Privada/Relevamiento_Arquitectura_Datos_Cromo.md
# §5.2 punto 4: "on-demand o en batch diferido, nunca dentro del barrido masivo").
#
# `_CAMINO_TIMEOUT_DEFAULT` es el doble del general: con 30 s una llamada larga falla y encima
# `_get` la reintenta 3 veces con backoff, o sea 4 grafos resueltos en Cromo por cada click.
# Es un valor puesto sin medición de latencia real todavía — se ajusta por entorno.
_CAMINO_TIMEOUT_DEFAULT = 60.0
# 1 req/s (no 5 como PROV, que es una API de consulta liviana): un operador que hace un click
# nunca espera, dos clicks seguidos cuestan 1 s de pacing, y un futuro batch de las 663 semillas
# reales termina en ~11 minutos sin sostenerle a Cromo varias resoluciones de grafo por segundo.
_CAMINO_RATE_LIMIT_DEFAULT = 1.0


class CromoConfigError(RuntimeError):
    """Configuración de Cromo incompleta o inválida."""


@dataclass(slots=True)
class CromoConfig:
    """Configuración validada de acceso a Cromo Red, incluyendo el flujo OAuth2 del api-gateway."""

    base_url: str
    user: str
    password: str
    timeout: float
    psize_default: int
    oauth_url: str
    client_id: str
    client_secret: str
    ruta_servidor: str = _RUTA_SERVIDOR_DEFAULT
    camino_rate_limit_per_second: float = _CAMINO_RATE_LIMIT_DEFAULT
    camino_timeout: float = _CAMINO_TIMEOUT_DEFAULT

    @property
    def url_servidor(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.ruta_servidor}"


def enmascarar(valor: str, visibles: int = 4, max_asteriscos: int = 20) -> str:
    """Devuelve un secreto enmascarado, mostrando sólo los últimos `visibles` caracteres.

    Acota la cantidad de asteriscos (no 1:1 con la longitud real): un JWT de OAuth2 puede tener
    miles de caracteres, y sin este tope una sola línea de log queda inutilizable (hallazgo real
    al loguear el access_token de Cromo — ver `client.py::_obtener_token`).
    """
    if not valor:
        return ""
    if len(valor) <= visibles:
        return "*" * len(valor)
    asteriscos = min(len(valor) - visibles, max_asteriscos)
    return "*" * asteriscos + valor[-visibles:]


def _derivar_oauth_url(base_url: str) -> str:
    """El manual indica que el microservicio server-oauth2 corre en el mismo host, puerto 9999 por defecto."""
    partes = urlsplit(base_url)
    return urlunsplit((partes.scheme, f"{partes.hostname}:{_OAUTH_PUERTO_DEFAULT}", _OAUTH_PATH_DEFAULT, "", ""))


def _float_positivo_de_entorno(variable: str, default: float) -> float:
    """Lee un float estrictamente positivo del entorno, o falla con `CromoConfigError`."""
    crudo = os.getenv(variable, "").strip() or str(default)
    try:
        valor = float(crudo)
    except ValueError as exc:
        raise CromoConfigError(f"{variable} debe ser numérico (recibido {crudo!r})") from exc
    if valor <= 0:
        raise CromoConfigError(f"{variable} debe ser mayor a 0 (recibido {valor})")
    return valor


def _construir_config() -> CromoConfig:
    base_url = os.getenv("CROMO_BASE_URL", "").strip()
    user = os.getenv("CROMO_USER", "").strip()
    password = get_secret("cromo_password_v1", "CROMO_PASSWORD").strip()

    faltantes = [
        nombre
        for nombre, valor in (
            ("CROMO_BASE_URL", base_url),
            ("CROMO_USER", user),
            ("CROMO_PASSWORD (o secreto cromo_password_v1)", password),
        )
        if not valor
    ]
    if faltantes:
        raise CromoConfigError(
            "Configuración de Cromo incompleta. Definir en el entorno: " + ", ".join(faltantes)
        )

    if "{{" in base_url or "}}" in base_url:
        raise CromoConfigError(
            "CROMO_BASE_URL contiene una variable de plantilla sin resolver "
            f"(p.ej. de un environment de Postman): {base_url!r}. Usar la URL final."
        )

    try:
        timeout = float(os.getenv("CROMO_TIMEOUT", str(_TIMEOUT_DEFAULT)))
    except ValueError as exc:
        raise CromoConfigError("CROMO_TIMEOUT debe ser numérico") from exc

    try:
        psize_default = int(os.getenv("CROMO_PSIZE_DEFAULT", str(_PSIZE_DEFAULT)))
    except ValueError as exc:
        raise CromoConfigError("CROMO_PSIZE_DEFAULT debe ser entero") from exc
    if psize_default not in PSIZE_PERMITIDOS:
        raise CromoConfigError(
            f"CROMO_PSIZE_DEFAULT={psize_default} no es válido. "
            f"Valores permitidos: {sorted(PSIZE_PERMITIDOS)}"
        )

    # Se validan al arrancar y no en el primer request: un rate inválido explotaría con un
    # `ValueError` crudo de `AsyncRateLimiter` recién cuando un operador hace click.
    camino_timeout = _float_positivo_de_entorno("CROMO_CAMINO_TIMEOUT", _CAMINO_TIMEOUT_DEFAULT)
    camino_rate_limit_per_second = _float_positivo_de_entorno(
        "CROMO_CAMINO_RATE_LIMIT_PER_SECOND", _CAMINO_RATE_LIMIT_DEFAULT
    )

    oauth_url = os.getenv("CROMO_OAUTH_URL", "").strip() or _derivar_oauth_url(base_url)
    client_id = os.getenv("CROMO_CLIENT_ID", "").strip() or _CLIENT_ID_DEFAULT
    client_secret = get_secret("cromo_client_secret_v1", "CROMO_CLIENT_SECRET").strip() or _CLIENT_SECRET_DEFAULT

    if client_id == _CLIENT_ID_DEFAULT and client_secret == _CLIENT_SECRET_DEFAULT:
        logger.warning(
            "action=cromo_config evento=oauth_client_default "
            "detalle=usando client_id/client_secret por defecto del manual; confirmar con el administrador de Cromo si Metrotel los rotó"
        )

    return CromoConfig(
        base_url=base_url,
        user=user,
        password=password,
        timeout=timeout,
        psize_default=psize_default,
        oauth_url=oauth_url,
        client_id=client_id,
        client_secret=client_secret,
        camino_rate_limit_per_second=camino_rate_limit_per_second,
        camino_timeout=camino_timeout,
    )


@lru_cache(maxsize=1)
def get_cromo_config() -> CromoConfig:
    """Lee y valida la configuración de Cromo desde variables de entorno (cacheada)."""
    return _construir_config()


__all__ = ["CromoConfig", "CromoConfigError", "get_cromo_config", "enmascarar", "PSIZE_PERMITIDOS"]
