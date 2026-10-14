# Nombre de archivo: test_servicios_alta_prov_desde_cromo.py
# Ubicación de archivo: tests/test_servicios_alta_prov_desde_cromo.py
# Descripción: Reglas del alta desde PROV de servicios declarados por Cromo: OST REALIZADA no es servicio, bajas sin nro_servicio

from __future__ import annotations

import asyncio

from scripts import servicios_alta_prov_desde_cromo as alta


class _SesionSinServicios:
    async def execute(self, *_a, **_k):
        class _R:
            def first(self_inner):
                return None

        return _R()


class _ClienteProv:
    def __init__(self, contexto):
        self.contexto = contexto

    async def obtener_contexto_servicio(self, numero):
        return self.contexto


def test_ost_realizada_no_se_da_de_alta():
    contexto = {"subproducto": None, "nro_servicio_original": "32200", "estado_comercial": "OST REALIZADA"}
    resultado = asyncio.run(alta.procesar_numero(_SesionSinServicios(), _ClienteProv(contexto), "32200"))
    assert resultado == ("omitido_no_es_servicio", None)


def test_baja_sin_nro_servicio_usa_el_original_como_vigente():
    contexto = {"subproducto": "ISI", "nro_servicio_original": "99861", "estado_comercial": "DADO BAJA"}
    assert alta._normalizar_contexto(contexto, "99861")["nro_servicio"] == "99861"
    assert alta._normalizar_contexto({"nro_servicio": "120893"}, "120893")["nro_servicio"] == "120893"


# ─── Sync global de categorías de clientes al final de la corrida (Task 5) ──────────────────────

import argparse  # noqa: E402

import pytest  # noqa: E402


class _SesionFalsa:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def execute(self, *_a, **_k):
        class _R:
            def all(self_inner):
                class _F:
                    servicio_numero = "1"
                    vinculos = 1

                return [_F()]

        return _R()

    async def commit(self):
        return None

    async def rollback(self):
        return None


class _ProvFalso:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None


@pytest.fixture
def corrida(monkeypatch):
    llamadas: list = []
    monkeypatch.setattr(alta, "AsyncSessionLocal", lambda: _SesionFalsa())
    monkeypatch.setattr(alta, "ProvClient", _ProvFalso)
    monkeypatch.setattr(
        alta, "sincronizar_clientes_en_sesion_propia", lambda claves, *, origen: llamadas.append((claves, origen))
    )

    def correr(resultado: str, apply: bool) -> list:
        async def procesar(_s, _c, _n):
            return resultado, "Activo"

        monkeypatch.setattr(alta, "procesar_numero", procesar)
        asyncio.run(alta.main(argparse.Namespace(apply=apply, limite=None)))
        return llamadas

    return correr


def test_apply_con_altas_sincroniza_todos_los_clientes_una_vez(corrida):
    assert corrida("creado", True) == [(None, "alta_prov_desde_cromo")]


def test_dry_run_no_sincroniza_clientes(corrida):
    assert corrida("creado", False) == []


def test_apply_sin_cambios_no_sincroniza_clientes(corrida):
    assert corrida("ya_existia", True) == []
