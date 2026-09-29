# Nombre de archivo: test_cable_consultas.py
# Ubicación de archivo: tests/test_cable_consultas.py
# Descripción: Tests unitarios de core/services/cable_consultas.py: resolución de cable, buffers por servicio y pelos por buffer

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from core.services import cable_consultas as cc
from core.services.cromo.detalle import DetalleCable, PeloDetalle, TuboDetalle
from core.services.cromo.verificador import ResultadoServiciosUnicos, ServicioEncontrado, ServicioUnico


class _Sesion:
    def __init__(self, filas):
        self.filas = filas
        self.params = []

    async def execute(self, stmt, params):
        self.params.append(params)
        filas = self.filas

        class _R:
            def all(self_inner):
                return filas

        return _R()


def test_resolver_cable_numerico_busca_por_n_id_y_texto_por_nombre() -> None:
    s = _Sesion([(1, "F-X", "48", "A", "B")])
    assert asyncio.run(cc.resolver_cable(s, " 6605471 "))[0].n_id == 1
    assert s.params[-1] == {"n_id": 6605471}
    asyncio.run(cc.resolver_cable(s, "f-mrt-001"))
    assert s.params[-1] == {"nombre": "f-mrt-001"}


def test_resolver_cable_numerico_sin_ese_id_cae_a_nombre() -> None:
    class _SesionNombreNumerico(_Sesion):
        async def execute(self, stmt, params):
            self.params.append(params)
            filas = [] if "n_id" in params else [(5, "12345", None, None, None)]

            class _R:
                def all(self_inner):
                    return filas

            return _R()

    s = _SesionNombreNumerico([])
    assert [c.nombre for c in asyncio.run(cc.resolver_cable(s, "12345"))] == ["12345"]
    assert s.params == [{"n_id": 12345}, {"nombre": "12345"}]


def test_resolver_cable_vacio_no_consulta() -> None:
    s = _Sesion([])
    assert asyncio.run(cc.resolver_cable(s, "   ")) == []
    assert s.params == []


def _unico(sid: str, pelos: list[int]) -> ServicioUnico:
    return ServicioUnico(
        servicio_id=1,
        servicio_id_externo=sid,
        numero_primer_servicio=sid,
        nombre_cliente="Cliente " + sid,
        cliente=None,
        estado_servicio="Activo",
        tipo_servicio="TLS",
        pelos_n_ids=pelos,
        cantidad_pelos=len(pelos),
        numeros_en_pelo=[sid],
        metodos=["regex"],
    )


def test_servicios_de_cable_calcula_buffers_1_indexados_y_ordena() -> None:
    unicos = ResultadoServiciosUnicos(cable_n_id=9, tubo_n_id=None, servicios=[_unico("200", [3]), _unico("100", [1, 2])])
    sesion = _Sesion([(1, 0), (2, 1), (3, 0)])
    with patch.object(cc, "servicios_unicos_por_cable", AsyncMock(return_value=unicos)):
        resultado = asyncio.run(cc.servicios_de_cable(sesion, 9))

    assert [(s.servicio_id, s.buffers) for s in resultado] == [("100", [1, 2]), ("200", [1])]
    assert resultado[0].cliente == "Cliente 100"


def _pelo(n_id: int, orden: int, *, vigente: bool = True, servicio: str | None = None) -> PeloDetalle:
    pelo = PeloDetalle(n_id, 1, str(orden + 1), orden, "AZ", "SERVICIO", f"desc {n_id}", servicio, vigente)
    if servicio:
        pelo.servicios.append(ServicioEncontrado(1, servicio, servicio, "Cli", None, "Activo", 6, "TLS", n_id, servicio, "regex"))
    return pelo


def _detalle() -> DetalleCable:
    tubos = [
        TuboDetalle(1, 0, "AZ", True, True, [_pelo(12, 1, servicio="93154"), _pelo(11, 0), _pelo(13, 2, vigente=False)]),
        TuboDetalle(2, 1, "NR", True, True, [_pelo(21, 0)]),
        TuboDetalle(3, 2, "VR", False, True, [_pelo(31, 0)]),
    ]
    campos = {f: None for f in DetalleCable.__dataclass_fields__ if f not in ("n_id", "vigente", "tubos")}
    return DetalleCable(n_id=9, vigente=True, tubos=tubos, **campos)


def test_pelos_por_buffer_ordena_filtra_no_vigentes_y_marca_ocupados() -> None:
    with patch.object(cc, "obtener_detalle_cable", AsyncMock(return_value=_detalle())):
        buffers = asyncio.run(cc.pelos_por_buffer(object(), 9))

    assert [b.numero for b in buffers] == [1, 2]
    primero = buffers[0].pelos
    assert [p.numero for p in primero] == ["1", "2"]
    assert (primero[0].estado, primero[0].servicio_id) == ("libre", None)
    assert (primero[1].estado, primero[1].servicio_id, primero[1].cliente) == ("ocupado", "93154", "Cli")


def test_pelos_por_buffer_filtra_un_buffer() -> None:
    with patch.object(cc, "obtener_detalle_cable", AsyncMock(return_value=_detalle())):
        assert [b.numero for b in asyncio.run(cc.pelos_por_buffer(object(), 9, buffer=2))] == [2]
        assert asyncio.run(cc.pelos_por_buffer(object(), 9, buffer=7)) == []
