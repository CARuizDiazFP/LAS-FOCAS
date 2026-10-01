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
