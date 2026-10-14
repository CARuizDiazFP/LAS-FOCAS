# Nombre de archivo: test_clientes_categoria_hooks.py
# Ubicación de archivo: tests/test_clientes_categoria_hooks.py
# Descripción: Tests unitarios (sin DB) del hook resiliente que sincroniza categorías de clientes después de una ingesta

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

import core.services.clientes_categoria_hooks as hooks
from core.services.clientes_categoria_service import ResumenSync


class _SesionFalsa:
    def __init__(self) -> None:
        self.commits = 0

    def __enter__(self) -> "_SesionFalsa":
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def sesion(monkeypatch: pytest.MonkeyPatch) -> _SesionFalsa:
    s = _SesionFalsa()
    monkeypatch.setattr(hooks, "SessionLocal", lambda: s)
    return s


def test_sin_claves_no_abre_sesion_ni_sincroniza(monkeypatch: pytest.MonkeyPatch) -> None:
    abrir = MagicMock()
    monkeypatch.setattr(hooks, "SessionLocal", abrir)
    assert hooks.sincronizar_clientes_en_sesion_propia(set(), origen="test") == hooks.ResultadoSyncClientes()
    abrir.assert_not_called()


def test_con_claves_sincroniza_esas_claves_y_hace_commit(sesion: _SesionFalsa, monkeypatch) -> None:
    llamadas: list = []

    def falso(session, claves=None):
        llamadas.append((session, claves))
        return ResumenSync(clientes_creados=1, clientes_recalculados=2, servicios_actualizados=3)

    monkeypatch.setattr(hooks, "sincronizar_categorias", falso)
    resultado = hooks.sincronizar_clientes_en_sesion_propia({"ACME"}, origen="test")

    assert llamadas == [(sesion, {"ACME"})]
    assert sesion.commits == 1
    assert resultado == hooks.ResultadoSyncClientes(
        resumen={"clientes_creados": 1, "clientes_recalculados": 2, "servicios_actualizados": 3}
    )


def test_global_pasa_claves_none(sesion: _SesionFalsa, monkeypatch) -> None:
    llamadas: list = []
    monkeypatch.setattr(
        hooks, "sincronizar_categorias", lambda session, claves=None: llamadas.append(claves) or ResumenSync()
    )
    hooks.sincronizar_clientes_en_sesion_propia(None, origen="script")
    assert llamadas == [None]
    assert sesion.commits == 1


def test_fallo_de_la_sync_no_se_propaga_y_se_loguea(sesion: _SesionFalsa, monkeypatch, caplog) -> None:
    def explota(session, claves=None):
        raise RuntimeError("db caída")

    monkeypatch.setattr(hooks, "sincronizar_categorias", explota)
    with caplog.at_level(logging.ERROR, logger=hooks.logger.name):
        resultado = hooks.sincronizar_clientes_en_sesion_propia({"ACME"}, origen="excel")

    assert resultado == hooks.ResultadoSyncClientes(error=True)
    assert sesion.commits == 0
    assert any("action=clientes_sync_error" in r.getMessage() and "origen=excel" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_post_ingesta_calcula_claves_de_los_nombres(monkeypatch) -> None:
    recibidas: list = []

    def falso(claves, *, origen):
        recibidas.append((claves, origen))
        return hooks.ResultadoSyncClientes(resumen={"ok": 1})

    monkeypatch.setattr(hooks, "sincronizar_clientes_en_sesion_propia", falso)
    resultado = await hooks.sincronizar_clientes_post_ingesta(
        ["Acme S.A.", "ACME SA", None, "  ", "Otro SRL"], origen="prov"
    )
    assert recibidas == [({"ACME", "OTRO"}, "prov")]
    assert resultado == hooks.ResultadoSyncClientes(resumen={"ok": 1})


@pytest.mark.asyncio
async def test_post_ingesta_sin_nombres_validos_no_sincroniza(monkeypatch) -> None:
    falso = MagicMock()
    monkeypatch.setattr(hooks, "sincronizar_clientes_en_sesion_propia", falso)
    assert await hooks.sincronizar_clientes_post_ingesta([None, ""], origen="prov") == hooks.ResultadoSyncClientes()
    falso.assert_not_called()


@pytest.mark.asyncio
async def test_post_ingesta_nunca_lanza(monkeypatch) -> None:
    def explota(claves, *, origen):
        raise RuntimeError("thread roto")

    monkeypatch.setattr(hooks, "sincronizar_clientes_en_sesion_propia", explota)
    assert await hooks.sincronizar_clientes_post_ingesta(["Acme"], origen="prov") == hooks.ResultadoSyncClientes(
        error=True
    )
