# Nombre de archivo: test_prov_rate_limiter.py
# Ubicación de archivo: tests/test_prov_rate_limiter.py
# Descripción: Verifica que el limitador de PROV no deje pasar más operaciones por segundo que la tasa configurada — tiempo real, sin mockear asyncio.sleep

from __future__ import annotations

import asyncio
import time

from core.services.prov.rate_limiter import AsyncRateLimiter


def test_rate_limiter_no_supera_la_tasa_configurada() -> None:
    async def _correr() -> float:
        limiter = AsyncRateLimiter(rate_per_second=5.0)
        inicio = time.monotonic()
        for _ in range(6):
            async with limiter:
                pass
        return time.monotonic() - inicio

    elapsed = asyncio.run(_correr())
    # 6 operaciones a 5/s: las primeras 5 caben en el primer segundo, la 6ta empuja al siguiente.
    assert elapsed >= 1.0


def test_rate_limiter_no_espera_si_las_llamadas_ya_vienen_espaciadas() -> None:
    async def _correr() -> float:
        limiter = AsyncRateLimiter(rate_per_second=5.0)
        inicio = time.monotonic()
        async with limiter:
            pass
        await asyncio.sleep(0.25)  # más que el intervalo mínimo entre turnos (0.2s a 5/s)
        async with limiter:
            pass
        return time.monotonic() - inicio

    elapsed = asyncio.run(_correr())
    assert elapsed < 0.4


def test_rate_limiter_rechaza_tasa_no_positiva() -> None:
    import pytest

    with pytest.raises(ValueError):
        AsyncRateLimiter(rate_per_second=0)
