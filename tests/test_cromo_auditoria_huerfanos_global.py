# Nombre de archivo: test_cromo_auditoria_huerfanos_global.py
# Ubicación de archivo: tests/test_cromo_auditoria_huerfanos_global.py
# Descripción: Pruebas de la corrida global de auditoría de huérfanos — un evento por Servicio,
# tope configurable, cancelación, corte por Cromo caído y cierre de la corrida

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from core.services.cromo import auditoria_huerfanos_global as glob
from core.services.cromo import ingesta
from core.services.cromo.auditoria_huerfanos import ResumenAuditoria
from core.services.cromo.client import CromoClientError


@dataclass
class _Corrida:
    id: int
    estado: str = "EN_CURSO"
    total_objetivo: Optional[int] = None
    leidas: int = 0
    actualizadas: int = 0
    errores: int = 0
    finalizada_at: Any = None


@dataclass
class _Sesion:
    corrida: _Corrida
    eventos: list = field(default_factory=list)
    commits: int = 0
    rollbacks: int = 0

    async def get(self, _modelo, _pk):
        return self.corrida

    def add(self, obj) -> None:
        self.eventos.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@dataclass
class _Resultado:
    tramos: list
    residuales: list
    completo: bool = True
    auditoria: Optional[ResumenAuditoria] = None
    auditoria_omitida: Optional[str] = None


def _eventos(sesion: _Sesion, accion: str) -> list[dict]:
    salida = []
    for e in sesion.eventos:
        if e.accion != accion:
            continue
        try:
            salida.append(json.loads(e.detalle))
        except (TypeError, ValueError):
            salida.append({"texto": e.detalle})
    return salida


@pytest.fixture
def entorno(monkeypatch):
    estado = {"servicios": [(11, 300), (22, 200), (33, 100)], "cancelar_en": None, "fallas": {}}
    llamadas: list[dict] = []

    async def _servicios(_sesion, limite):
        estado["limite"] = limite
        return estado["servicios"][:limite]

    async def _cancelada(_sesion, _corrida_id):
        return estado["cancelar_en"] is not None and len(llamadas) >= estado["cancelar_en"]

    async def _trackings(_cliente, _sesion, servicio_id, *, corrida_id=None, fuente_evidencia="WEB"):
        llamadas.append({"servicio_id": servicio_id, "corrida_id": corrida_id})
        falla = estado["fallas"].get(servicio_id)
        if falla is not None:
            raise falla
        if servicio_id in estado.get("incompletos", ()):
            return _Resultado(tramos=[1], residuales=[3], completo=False, auditoria_omitida="INCOMPLETO")
        if servicio_id in estado.get("con_fallidas", ()):
            # completo=True pero con semillas fallidas: trackings_del_servicio no auditó.
            return _Resultado(tramos=[1], residuales=[3], completo=True, auditoria_omitida="INCOMPLETO")
        return _Resultado(
            tramos=[1, 2],
            residuales=[3],
            auditoria=ResumenAuditoria(nuevos=2, actualizados=1, por_causa={"CABLE_DESUSO": 3}),
        )

    monkeypatch.setattr(glob, "servicios_por_pelos", _servicios)
    monkeypatch.setattr(ingesta, "_fue_cancelada_externamente", _cancelada)
    monkeypatch.setattr(
        "core.services.cromo.tracking_service.trackings_del_servicio", _trackings
    )
    monkeypatch.delenv("CROMO_AUDITORIA_MAX_SERVICIOS", raising=False)
    return estado, llamadas


@pytest.mark.asyncio
async def test_un_evento_por_servicio_en_orden_y_cierra_ok(entorno):
    _estado, llamadas = entorno
    sesion = _Sesion(_Corrida(id=5))

    estado_final = await glob.auditar_global(object(), sesion, 5)

    assert estado_final == "OK"
    assert [x["servicio_id"] for x in llamadas] == [11, 22, 33]
    assert all(x["corrida_id"] == 5 for x in llamadas)
    paginas = _eventos(sesion, "PAGINA")
    assert [p["servicio_id"] for p in paginas] == [11, 22, 33]
    assert paginas[-1]["leidas"] == 3 and paginas[-1]["total"] == 3
    assert paginas[0]["por_causa"] == {"CABLE_DESUSO": 3}
    assert _eventos(sesion, "INICIO")[0]["total_objetivo"] == 3
    assert _eventos(sesion, "RESUMEN")[0]["estado"] == "OK"
    assert sesion.corrida.estado == "OK" and sesion.corrida.finalizada_at is not None
    assert sesion.corrida.leidas == 3 and sesion.corrida.actualizadas == 9
    assert all(len(e.accion) <= 32 for e in sesion.eventos)


@pytest.mark.asyncio
async def test_tope_explicito_y_del_entorno(entorno, monkeypatch):
    estado, llamadas = entorno
    await glob.auditar_global(object(), _Sesion(_Corrida(id=1)), 1, max_servicios=2)
    assert estado["limite"] == 2 and len(llamadas) == 2

    monkeypatch.setenv("CROMO_AUDITORIA_MAX_SERVICIOS", "1")
    await glob.auditar_global(object(), _Sesion(_Corrida(id=2)), 2)
    assert estado["limite"] == 1


@pytest.mark.parametrize("valor, esperado", [(None, 50), ("7", 7), ("0", 50), ("x", 50)])
def test_max_servicios_configurado(monkeypatch, valor, esperado):
    if valor is None:
        monkeypatch.delenv("CROMO_AUDITORIA_MAX_SERVICIOS", raising=False)
    else:
        monkeypatch.setenv("CROMO_AUDITORIA_MAX_SERVICIOS", valor)
    assert glob.max_servicios_configurado() == esperado


@pytest.mark.asyncio
async def test_un_servicio_que_falla_no_corta_la_corrida(entorno):
    estado, llamadas = entorno
    estado["fallas"] = {22: RuntimeError("boom")}
    sesion = _Sesion(_Corrida(id=5))

    assert await glob.auditar_global(object(), sesion, 5) == "OK_CON_ERRORES"
    assert [x["servicio_id"] for x in llamadas] == [11, 22, 33]
    assert sesion.corrida.errores == 1 and sesion.rollbacks == 1
    assert any("Servicio 22" in e["texto"] for e in _eventos(sesion, "ERROR"))


@pytest.mark.asyncio
async def test_cromo_caido_corta_tras_tres_fallos_seguidos(entorno):
    estado, llamadas = entorno
    estado["servicios"] = [(i, 10) for i in range(1, 10)]
    estado["fallas"] = {i: CromoClientError("timeout") for i in range(1, 10)}
    sesion = _Sesion(_Corrida(id=5))

    assert await glob.auditar_global(object(), sesion, 5) == "FALLIDA"
    assert len(llamadas) == 3


@pytest.mark.asyncio
async def test_cancelacion_cooperativa_entre_servicios(entorno):
    estado, llamadas = entorno
    estado["cancelar_en"] = 1
    sesion = _Sesion(_Corrida(id=5))

    assert await glob.auditar_global(object(), sesion, 5) == "CANCELADA"
    assert len(llamadas) == 1
    assert sesion.corrida.estado == "CANCELADA"


@pytest.mark.asyncio
async def test_servicio_incompleto_se_registra_omitido_y_no_es_error(entorno):
    estado, _llamadas = entorno
    estado["incompletos"] = {22}
    sesion = _Sesion(_Corrida(id=5))

    assert await glob.auditar_global(object(), sesion, 5) == "OK"
    paginas = {p["servicio_id"]: p for p in _eventos(sesion, "PAGINA")}
    assert paginas[22]["auditoria"] == "OMITIDA_INCOMPLETO"
    assert paginas[11]["auditoria"] == "OK"
    assert paginas[33]["omitidos"] == 1 and sesion.corrida.errores == 0
    assert _eventos(sesion, "RESUMEN")[0]["omitidos_incompletos"] == 1


@pytest.mark.asyncio
async def test_servicio_con_semillas_fallidas_tambien_se_omite(entorno):
    estado, _llamadas = entorno
    estado["con_fallidas"] = {33}
    sesion = _Sesion(_Corrida(id=5))

    assert await glob.auditar_global(object(), sesion, 5) == "OK"
    paginas = {p["servicio_id"]: p for p in _eventos(sesion, "PAGINA")}
    assert paginas[33]["auditoria"] == "OMITIDA_INCOMPLETO"
    assert sesion.corrida.errores == 0
