# Nombre de archivo: client.py
# Ubicación de archivo: core/services/cromo/client.py
# Descripción: Cliente HTTP asíncrono de sólo lectura para la API de Cromo Red, con autenticación OAuth2, paginación y reintentos

from __future__ import annotations

import asyncio
import json
import logging
from types import TracebackType
from typing import Any, AsyncIterator, Iterable, Mapping, Optional

import httpx
import json5

from core.services.cromo.config import CromoConfig, enmascarar, get_cromo_config

# Se importa el limitador de PROV en su lugar en vez de mudarlo a `core/services/`: el archivo no
# tiene ningún acoplamiento a PROV en código (sólo `asyncio`/`time`/`typing`), y mudarlo metería a
# PROV en el diff de un feature de Cromo. Si hace falta compartirlo más, la mudanza es un commit
# aparte de 3 líneas.
from core.services.prov.rate_limiter import AsyncRateLimiter

logger = logging.getLogger(__name__)

_REINTENTOS_MAX = 3
_BACKOFF_BASE_SEGUNDOS = 1.0
_RUTA_CAMINO_FO = "/network/fo/{id}/path"

# Limitador compartido de proceso para `/path`, módulo-level y NO por instancia: el patrón
# establecido en la web (`web/app/main.py`, endpoint `/vivo`) construye un `CromoClient` nuevo por
# request, así que un limiter por instancia no limitaría nada. Vale para este uso porque el proceso
# web corre con un solo worker uvicorn (`web/Dockerfile`, sin `--workers`).
_limiter_camino_compartido: Optional[AsyncRateLimiter] = None


def _limiter_camino_de_proceso(rate_per_second: float) -> AsyncRateLimiter:
    """Instancia perezosa: se crea dentro del primer `await`, no al importar el módulo.

    No hay carrera posible: entre el chequeo y la asignación no hay ningún `await`.
    """
    global _limiter_camino_compartido
    if _limiter_camino_compartido is None:
        _limiter_camino_compartido = AsyncRateLimiter(rate_per_second)
    return _limiter_camino_compartido


def reiniciar_limiter_camino() -> None:
    """Descarta el limiter de proceso. Sólo para tests — en producción el pacing es global."""
    global _limiter_camino_compartido
    _limiter_camino_compartido = None


class CromoClientError(RuntimeError):
    """Error de comunicación con la API de Cromo tras agotar los reintentos, o respuesta 4xx."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _parsear_cuerpo(texto: str) -> dict[str, Any]:
    """Cromo v1 (vía api-gateway) responde "pseudo-JSON": claves sin comillas.

    El manual oficial lo documenta como comportamiento normal de la API v1 ("JSON sin
    comillas en los identificadores"), contra lo que asumía docs/ingesta_cromo.md
    ("la respuesta HTTP real es JSON válido"). Se intenta JSON estricto primero (rápido,
    y cubre el endpoint OAuth2 y cualquier respuesta ya bien formada) y se cae a un
    parser tolerante (superset de JSON) sólo si hace falta.
    """
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return json5.loads(texto)


class CromoClient:
    """Cliente de sólo lectura contra la API de Cromo Red.

    Los métodos `/cromo-api/v1/...` se acceden a través del microservicio api-gateway,
    que exige un token OAuth2 (`Authorization: Bearer <token>`) en cada request, no
    Basic Auth directo. El token se obtiene con `grant_type=password` contra
    `/oauth2/oauth/token` y se renueva sola una vez si una llamada responde 401.

    Por diseño no implementa POST/PUT/PATCH/DELETE contra `/db/...`: Cromo es el
    sistema de inventario de planta externa de FO de Metrotel y este cliente sólo lo consulta.
    """

    def __init__(
        self,
        config: Optional[CromoConfig] = None,
        cliente_http: Optional[httpx.AsyncClient] = None,
        limiter: Optional[AsyncRateLimiter] = None,
    ) -> None:
        # `limiter` sólo afecta a `get_camino_optico` (ver su docstring). Se acepta inyectado para
        # que los tests usen un doble sin dormir ni ensuciar el limiter de proceso.
        self._limiter_camino_inyectado = limiter
        self._config = config or get_cromo_config()
        self._cliente_propio = cliente_http is None
        self._cliente = cliente_http or httpx.AsyncClient(
            base_url=self._config.url_servidor,
            timeout=httpx.Timeout(self._config.timeout),
        )
        self._token: Optional[str] = None
        logger.info(
            "action=cromo_client_init evento=inicializado url_servidor=%s usuario=%s",
            self._config.url_servidor,
            self._config.user,
        )

    async def cerrar(self) -> None:
        if self._cliente_propio:
            await self._cliente.aclose()

    async def __aenter__(self) -> "CromoClient":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.cerrar()

    async def _obtener_token(self) -> str:
        """`POST /oauth2/oauth/token` con `grant_type=password`. Ver manual oficial, capítulo de autenticación."""
        respuesta = await self._cliente.post(
            self._config.oauth_url,
            data={
                "grant_type": "password",
                "username": self._config.user,
                "password": self._config.password,
            },
            auth=httpx.BasicAuth(self._config.client_id, self._config.client_secret),
        )
        if respuesta.status_code >= 400:
            logger.error("action=cromo_oauth evento=token_rechazado status=%d", respuesta.status_code)
            raise CromoClientError(
                f"No se pudo obtener token OAuth2 de Cromo ({respuesta.status_code}): {respuesta.text}"
            )
        cuerpo = respuesta.json()
        token = cuerpo.get("access_token")
        if not token:
            raise CromoClientError("La respuesta de autenticación de Cromo no incluyó access_token")
        logger.info("action=cromo_oauth evento=token_obtenido token_sufijo=%s", enmascarar(token))
        return token

    async def _asegurar_token(self) -> str:
        if self._token is None:
            self._token = await self._obtener_token()
        return self._token

    async def token_bearer(self) -> str:
        """Expone el token OAuth2 vigente (lo obtiene si todavía no existe).

        Pensado para diagnósticos puntuales (p.ej. `scripts/cromo_sonda.py`) que necesiten
        armar un request crudo fuera de `_get`. No usar como atajo para nuevos métodos: agregar
        el método correspondiente a esta clase en su lugar.
        """
        return await self._asegurar_token()

    def _limiter_camino(self) -> AsyncRateLimiter:
        return self._limiter_camino_inyectado or _limiter_camino_de_proceso(
            self._config.camino_rate_limit_per_second
        )

    async def _get(
        self,
        ruta: str,
        params: Optional[Mapping[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        """`timeout` sobreescribe el del cliente HTTP sólo para esta llamada.

        Se pasa condicionalmente (no como `timeout=None` explícito) para no pisar el
        `httpx.Timeout` del cliente en las rutas que no lo necesitan.
        """
        intento = 0
        reautenticado = False
        extra: dict[str, Any] = {} if timeout is None else {"timeout": timeout}
        while True:
            intento += 1
            token = await self._asegurar_token()
            try:
                respuesta = await self._cliente.get(
                    ruta, params=params, headers={"Authorization": f"Bearer {token}"}, **extra
                )
            except httpx.TransportError as exc:
                if intento > _REINTENTOS_MAX:
                    logger.error(
                        "action=cromo_get ruta=%s intento=%d resultado=agotado error=%s", ruta, intento, exc
                    )
                    raise CromoClientError(f"No se pudo contactar a Cromo en {ruta}: {exc}") from exc
                espera = _BACKOFF_BASE_SEGUNDOS * (2 ** (intento - 1))
                logger.warning(
                    "action=cromo_get ruta=%s intento=%d resultado=reintento_red espera=%.1f", ruta, intento, espera
                )
                await asyncio.sleep(espera)
                continue

            if respuesta.status_code == 401 and not reautenticado:
                logger.warning("action=cromo_get ruta=%s resultado=token_vencido_renovando", ruta)
                reautenticado = True
                self._token = None
                intento -= 1  # no consume presupuesto de reintentos de red/5xx
                continue

            if respuesta.status_code >= 500:
                if intento > _REINTENTOS_MAX:
                    logger.error(
                        "action=cromo_get ruta=%s intento=%d resultado=agotado status=%d",
                        ruta,
                        intento,
                        respuesta.status_code,
                    )
                    raise CromoClientError(
                        f"Cromo respondió {respuesta.status_code} en {ruta} tras {intento} intentos"
                    )
                espera = _BACKOFF_BASE_SEGUNDOS * (2 ** (intento - 1))
                logger.warning(
                    "action=cromo_get ruta=%s intento=%d resultado=reintento_5xx status=%d espera=%.1f",
                    ruta,
                    intento,
                    respuesta.status_code,
                    espera,
                )
                await asyncio.sleep(espera)
                continue

            if respuesta.status_code >= 400:
                logger.error(
                    "action=cromo_get ruta=%s resultado=error_4xx status=%d", ruta, respuesta.status_code
                )
                raise CromoClientError(
                    f"Cromo respondió {respuesta.status_code} en {ruta}: {respuesta.text}",
                    status_code=respuesta.status_code,
                )

            try:
                return _parsear_cuerpo(respuesta.text)
            except ValueError as exc:
                raise CromoClientError(f"Respuesta de Cromo en {ruta} no es JSON ni pseudo-JSON válido: {exc}") from exc

    async def get_objeto(self, n_id_o_id: int) -> dict[str, Any]:
        """`GET /db/objects/{id}`."""
        return await self._get(f"/db/objects/{n_id_o_id}")

    async def get_inner(self, n_id_o_id: int) -> dict[str, Any]:
        """`GET /db/objects/{id}/inner`."""
        return await self._get(f"/db/objects/{n_id_o_id}/inner")

    async def get_container(self, n_id_o_id: int) -> dict[str, Any]:
        """`GET /db/objects/{id}/container`."""
        return await self._get(f"/db/objects/{n_id_o_id}/container")

    async def get_objeto_con_topologia(self, n_id_o_id: int) -> dict[str, Any]:
        """`GET /db/objects/{id}?show=TOPOLOGIES&show=REL_ATTRIBUTE` — params REPETIDOS (no
        coma-separados como `get_coleccion`, que pega a `/db/select/model`, un endpoint distinto).
        Resuelve la topología conectada vigente de un objeto e incluye `hist[]` para seguir
        `next_id` en casos de "ID dual" (un objeto queda vacío y su topología pasa a otro id)."""
        return await self._get(f"/db/objects/{n_id_o_id}", params={"show": ["TOPOLOGIES", "REL_ATTRIBUTE"]})

    async def get_camino_optico(self, pelo_id: int) -> dict[str, Any]:
        """`GET /network/fo/{pelo_id}/path` — camino óptico completo resuelto por Cromo.

        Devuelve el recorrido de la luz atravesando fusiones y empalmes, como un diccionario
        indexado por id de objeto (`a[]`/`b[]` del nodo raíz dan el orden hacia cada extremo).
        **No pagina.** Es el único método de esta clase con rate limiting y con timeout propio:
        resuelve el grafo en memoria del lado del proveedor, por lo que el relevamiento lo
        prescribe "on-demand o en batch diferido, nunca dentro del barrido masivo"
        (docs/Doc Privada/Relevamiento_Arquitectura_Datos_Cromo.md §5.2 punto 4).

        El limiter NO se aplica en `_get`: la ingesta masiva pagina con `psize=5` sobre más de
        1,2M de pelos y limitarla a la tasa de `/path` la volvería una corrida de días.

        `pelo_id` puede ser un `n_id` de linaje o un `id` de versión — cuál acepta Cromo es una
        pregunta empírica todavía abierta, y este método no la decide: pasa el entero tal cual y
        devuelve el cuerpo **sin desenvolver** (hay tres formas posibles de envoltura, y elegir
        entre ellas es del servicio, en un solo lugar testeable sin red).
        """
        await self._limiter_camino().esperar_turno()
        return await self._get(
            _RUTA_CAMINO_FO.format(id=pelo_id), timeout=self._config.camino_timeout
        )

    async def get_coleccion(
        self,
        filtro: str,
        *,
        psize: Optional[int] = None,
        show: Optional[Iterable[str]] = None,
        next_cursor: Optional[int] = None,
    ) -> dict[str, Any]:
        """`GET /db/select/model`. El total por clase viene en `stats[].count`, no en un campo `total`."""
        params: dict[str, Any] = {
            "filter": filtro,
            "psize": psize if psize is not None else self._config.psize_default,
        }
        if show:
            params["show"] = ",".join(show)
        if next_cursor:
            params["next"] = next_cursor
        return await self._get("/db/select/model", params=params)

    async def iterar_coleccion(
        self,
        filtro: str,
        *,
        psize: Optional[int] = None,
        show: Optional[Iterable[str]] = None,
        max_paginas: Optional[int] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Pagina sola usando el cursor `next` de la respuesta. `next == 0` es la última página."""
        cursor: Optional[int] = None
        paginas_leidas = 0
        while True:
            pagina = await self.get_coleccion(filtro, psize=psize, show=show, next_cursor=cursor)
            yield pagina
            paginas_leidas += 1
            if max_paginas is not None and paginas_leidas >= max_paginas:
                break
            cursor = pagina.get("next")
            if not cursor:
                break


__all__ = ["CromoClient", "CromoClientError"]
