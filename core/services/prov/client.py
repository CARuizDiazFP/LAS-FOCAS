# Nombre de archivo: client.py
# Ubicación de archivo: core/services/prov/client.py
# Descripción: Cliente HTTP asíncrono para la API interna PROV (contexto de servicio), con Basic Auth, reintentos y rate limiting

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from types import TracebackType
from typing import Any, Optional

import httpx

from core.services.prov.config import ProvConfig, get_prov_config
from core.services.prov.rate_limiter import AsyncRateLimiter

logger = logging.getLogger(__name__)

_REINTENTOS_MAX = 3
_BACKOFF_BASE_SEGUNDOS = 1.0
_RUTA_CONTEXTO_SERVICIO = "/API_Contexto_Servicio"


class ProvClientError(RuntimeError):
    """Error de comunicación con PROV tras agotar los reintentos, o respuesta 4xx."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProvServicioNoEncontradoError(RuntimeError):
    """PROV respondió HTTP 200 pero sin contexto para el número de servicio consultado (payload
    `Resultado:` es un string, no un objeto)."""

    def __init__(self, nro_servicio: str, mensaje_prov: str) -> None:
        super().__init__(f"PROV no tiene contexto para el servicio {nro_servicio}: {mensaje_prov}")
        self.nro_servicio = nro_servicio
        self.mensaje_prov = mensaje_prov


class ProvClient:
    """Cliente de sólo lectura contra `API_Contexto_Servicio` de PROV. Basic Auth por request (sin
    token OAuth, a diferencia de `CromoClient`) y throttling compartido a
    `config.rate_limit_per_second`.
    """

    def __init__(
        self,
        config: Optional[ProvConfig] = None,
        cliente_http: Optional[httpx.AsyncClient] = None,
        limiter: Optional[AsyncRateLimiter] = None,
    ) -> None:
        self._config = config or get_prov_config()
        self._cliente_propio = cliente_http is None
        self._cliente = cliente_http or httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=httpx.Timeout(self._config.timeout),
        )
        # Auth aplicado por-request (no en el constructor del cliente httpx): así funciona tanto
        # con el cliente propio como con uno inyectado (p.ej. en tests con `httpx.MockTransport`,
        # que no lleva auth configurado al construirse).
        self._auth = httpx.BasicAuth(self._config.user, self._config.password)
        self._limiter = limiter or AsyncRateLimiter(self._config.rate_limit_per_second)
        logger.info("action=prov_client_init evento=inicializado base_url=%s", self._config.base_url)

    async def cerrar(self) -> None:
        if self._cliente_propio:
            await self._cliente.aclose()

    async def __aenter__(self) -> "ProvClient":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.cerrar()

    async def obtener_contexto_servicio(self, nro_servicio: str) -> dict[str, Any]:
        """`GET /API_Contexto_Servicio?nro_servicio=...`.

        Lanza `ProvServicioNoEncontradoError` si PROV responde 200 con el payload de "sin
        contexto" (``Resultado:`` es un string en vez de un objeto). Devuelve el dict de
        ``Resultado:`` en el caso de éxito.
        """
        cuerpo = await self._get({"nro_servicio": nro_servicio})
        resultado = cuerpo.get("Resultado:")
        if isinstance(resultado, dict):
            return resultado
        mensaje = resultado if isinstance(resultado, str) else "respuesta de PROV sin campo 'Resultado:' reconocible"
        raise ProvServicioNoEncontradoError(nro_servicio, mensaje)

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        intento = 0
        while True:
            intento += 1
            await self._limiter.esperar_turno()
            try:
                respuesta = await self._cliente.get(_RUTA_CONTEXTO_SERVICIO, params=params, auth=self._auth)
            except httpx.TransportError as exc:
                if intento > _REINTENTOS_MAX:
                    logger.error(
                        "action=prov_get params=%s intento=%d resultado=agotado error=%s", params, intento, exc
                    )
                    raise ProvClientError(f"No se pudo contactar a PROV: {exc}") from exc
                espera = _BACKOFF_BASE_SEGUNDOS * (2 ** (intento - 1))
                logger.warning(
                    "action=prov_get params=%s intento=%d resultado=reintento_red espera=%.1f",
                    params, intento, espera,
                )
                await asyncio.sleep(espera)
                continue

            if respuesta.status_code >= 500:
                if intento > _REINTENTOS_MAX:
                    logger.error(
                        "action=prov_get params=%s intento=%d resultado=agotado status=%d",
                        params, intento, respuesta.status_code,
                    )
                    raise ProvClientError(f"PROV respondió {respuesta.status_code} tras {intento} intentos")
                espera = _BACKOFF_BASE_SEGUNDOS * (2 ** (intento - 1))
                logger.warning(
                    "action=prov_get params=%s intento=%d resultado=reintento_5xx status=%d espera=%.1f",
                    params, intento, respuesta.status_code, espera,
                )
                await asyncio.sleep(espera)
                continue

            if respuesta.status_code >= 400:
                # El cuerpo crudo de PROV (`respuesta.text`) se loguea acá pero no viaja en el
                # mensaje de la excepción: ese mensaje llega tal cual hasta el usuario final como
                # `detail` del 502 (`api/app/routes/servicios.py::refrescar_servicio_desde_prov`).
                logger.error(
                    "action=prov_get params=%s resultado=error_4xx status=%d cuerpo=%s",
                    params, respuesta.status_code, respuesta.text,
                )
                raise ProvClientError(
                    f"PROV respondió {respuesta.status_code} para la consulta",
                    status_code=respuesta.status_code,
                )

            try:
                return respuesta.json()
            except ValueError as exc:
                raise ProvClientError(f"Respuesta de PROV no es JSON válido: {exc}") from exc


@lru_cache(maxsize=1)
def get_prov_client() -> ProvClient:
    """Instancia única de proceso — comparte el rate limiter entre todas las llamadas del mismo
    worker uvicorn (ver nota en `AsyncRateLimiter`)."""
    return ProvClient()


__all__ = ["ProvClient", "ProvClientError", "ProvServicioNoEncontradoError", "get_prov_client"]
