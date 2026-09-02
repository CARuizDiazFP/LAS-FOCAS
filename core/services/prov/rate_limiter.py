# Nombre de archivo: rate_limiter.py
# Ubicación de archivo: core/services/prov/rate_limiter.py
# Descripción: Limitador de tasa en memoria de proceso (pacing uniforme) para no superar N operaciones por segundo

from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import Optional


class AsyncRateLimiter:
    """Limita a `rate_per_second` operaciones por segundo, compartido entre corrutinas del mismo
    proceso vía `asyncio.Lock`. Implementación de pacing uniforme (cada turno se espacia
    `1/rate_per_second` segundos del anterior) — no permite ráfagas por encima de la tasa, lo cual
    hace la garantía más simple de verificar que un token bucket con capacidad.

    No coordina entre procesos distintos (ver nota operativa en
    docs/superpowers/specs/2026-09-02-servicios-prov-integracion-design.md) — alcanza para este uso
    porque el proceso de la API corre con un solo worker uvicorn (`api/Dockerfile`, sin
    `--workers`).
    """

    def __init__(self, rate_per_second: float) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second debe ser mayor a 0")
        self._intervalo = 1.0 / rate_per_second
        self._lock = asyncio.Lock()
        self._proximo_turno: Optional[float] = None

    async def esperar_turno(self) -> None:
        async with self._lock:
            ahora = time.monotonic()
            inicio = ahora if self._proximo_turno is None else max(ahora, self._proximo_turno)
            espera = inicio - ahora
            self._proximo_turno = inicio + self._intervalo
            if espera > 0:
                await asyncio.sleep(espera)

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self.esperar_turno()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        return None


__all__ = ["AsyncRateLimiter"]
