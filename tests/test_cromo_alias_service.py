# Nombre de archivo: test_cromo_alias_service.py
# Ubicación de archivo: tests/test_cromo_alias_service.py
# Descripción: Pruebas de carga y resolución del aliasing manual de Botellas Cromo, sin DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo import alias_service
from core.services.cromo.alias_service import AliasBotella


class _FilaAliasFake:
    def __init__(self, id_cromo_origen: int, accion: str, id_cromo_destino: Optional[int] = None) -> None:
        self.id_cromo_origen = id_cromo_origen
        self.accion = accion
        self.id_cromo_destino = id_cromo_destino


class _Escalares:
    def __init__(self, valores: list[Any]) -> None:
        self._valores = valores

    def all(self) -> list[Any]:
        return self._valores


class _Resultado:
    def __init__(self, valores: list[Any]) -> None:
        self._valores = valores

    def scalars(self) -> _Escalares:
        return _Escalares(self._valores)


class _SesionFake:
    """Emula sólo `AsyncSession.execute(select(CromoBotellaAlias))` — una única query esperada."""

    def __init__(self, filas: Optional[list[Any]] = None) -> None:
        self._filas = filas or []

    async def execute(self, stmt: Any) -> _Resultado:
        return _Resultado(self._filas)


# ── cargar_alias_vigentes ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cargar_alias_vigentes_arma_dict_por_origen():
    filas = [
        _FilaAliasFake(id_cromo_origen=111, accion="fusionar", id_cromo_destino=999),
        _FilaAliasFake(id_cromo_origen=222, accion="ignorar", id_cromo_destino=None),
    ]
    sesion = _SesionFake(filas)

    alias_por_origen = await alias_service.cargar_alias_vigentes(sesion)

    assert alias_por_origen == {
        111: AliasBotella(accion="fusionar", id_cromo_destino=999),
        222: AliasBotella(accion="ignorar", id_cromo_destino=None),
    }


@pytest.mark.asyncio
async def test_cargar_alias_vigentes_sin_filas_devuelve_dict_vacio():
    sesion = _SesionFake([])

    alias_por_origen = await alias_service.cargar_alias_vigentes(sesion)

    assert alias_por_origen == {}


# ── resolver_referencia ──────────────────────────────────────────────────────


def test_resolver_referencia_sin_alias_devuelve_n_id_sin_cambios():
    assert alias_service.resolver_referencia(555, {}) == 555


def test_resolver_referencia_none_devuelve_none():
    alias_por_origen = {111: AliasBotella(accion="fusionar", id_cromo_destino=999)}
    assert alias_service.resolver_referencia(None, alias_por_origen) is None


def test_resolver_referencia_fusionar_devuelve_destino():
    alias_por_origen = {111: AliasBotella(accion="fusionar", id_cromo_destino=999)}
    assert alias_service.resolver_referencia(111, alias_por_origen) == 999


def test_resolver_referencia_ignorar_devuelve_none():
    alias_por_origen = {222: AliasBotella(accion="ignorar", id_cromo_destino=None)}
    assert alias_service.resolver_referencia(222, alias_por_origen) is None


def test_resolver_referencia_no_persigue_cadenas():
    # A(111) -> B(222) -> C(333), ambas filas 'fusionar'. resolver_referencia(111) debe devolver
    # 222 (un solo salto), nunca perseguir hasta 333 — evita loops por una fila mal cargada a mano.
    alias_por_origen = {
        111: AliasBotella(accion="fusionar", id_cromo_destino=222),
        222: AliasBotella(accion="fusionar", id_cromo_destino=333),
    }
    assert alias_service.resolver_referencia(111, alias_por_origen) == 222
