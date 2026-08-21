# Nombre de archivo: test_cromo_repoblacion_service.py
# Ubicación de archivo: tests/test_cromo_repoblacion_service.py
# Descripción: Pruebas de detección/repoblación de cables Cromo con historial "ID dual" (hist[]/next_id), sin red ni DB real

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import pytest

from core.services.cromo import repoblacion_service as repo
from core.services.cromo.client import CromoClientError
from core.services.cromo.verificador import ObjetoNoEncontrado
from db.models.cromo import CromoBotella, CromoCable

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "cromo"


def _cargar(nombre: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / nombre).read_text())


BOTELLA_VIEJA = _cargar("botella_b2_fo_car_id_viejo.json")  # n_id=9057909 (por 'id'), tp vacío
BOTELLA_VIGENTE = _cargar("botella_b2_fo_car_next_id.json")  # n_id=9057909, id=9057952, tp con 6 cables
CABLES_DIRECTOS = _cargar("cables_b2_fo_car_directo.json")  # {n_id_str: objeto completo} x 6


class _NestedCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Escalares:
    def __init__(self, valores: list[Any]) -> None:
        self._valores = valores

    def all(self):
        return self._valores


class _ResultadoVacio:
    def scalars(self):
        return _Escalares([])


class _ClienteFake:
    """`respuestas`: n_id → objeto (se envuelve en {"st":0,"response":...} como responde Cromo
    real). `errores`: n_id → excepción a levantar en vez de responder."""

    def __init__(self, respuestas: dict[int, dict[str, Any]], errores: Optional[dict[int, Exception]] = None) -> None:
        self._respuestas = respuestas
        self._errores = errores or {}
        self.llamadas: list[int] = []

    async def get_objeto_con_topologia(self, n_id: int) -> dict[str, Any]:
        self.llamadas.append(n_id)
        if n_id in self._errores:
            raise self._errores[n_id]
        return {"st": 0, "response": self._respuestas[n_id]}


class _SesionFake:
    def __init__(self, existentes: Optional[dict[tuple[type, int], Any]] = None) -> None:
        self._existentes = existentes or {}
        self.agregados: list[Any] = []

    async def get(self, modelo_cls: type, pk: int) -> Any:
        return self._existentes.get((modelo_cls, pk))

    def add(self, obj: Any) -> None:
        self.agregados.append(obj)
        n_id = getattr(obj, "n_id", None)
        if n_id is not None:
            self._existentes[(type(obj), n_id)] = obj

    def begin_nested(self) -> _NestedCM:
        return _NestedCM()

    async def execute(self, stmt: Any) -> _ResultadoVacio:
        return _ResultadoVacio()  # sin alias cargados: cargar_alias_vigentes() devuelve {}

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = 1


def _botella_local(n_id: int = 9057909) -> CromoBotella:
    return CromoBotella(n_id=n_id, version_id=1, vmax=168149, nombre="B2-FO-CAR", clase=68, payload_raw={})


# ── Resolución de cadena hist[]/next_id ──────────────────────────────────────


@pytest.mark.asyncio
async def test_resolver_cadena_sin_hist_usa_el_objeto_tal_cual():
    obj = {"id": 1, "hist": [], "tp": [{"class": 51, "id_to": 5}]}
    cliente = _ClienteFake({})
    obj_vigente, ids_cadena = await repo._resolver_cadena_objetos(cliente, 1, obj)
    assert obj_vigente is obj
    assert ids_cadena == {1}
    assert cliente.llamadas == []  # no hizo falta ningún request adicional


@pytest.mark.asyncio
async def test_resolver_cadena_sigue_next_id_cuando_el_objeto_original_esta_vacio():
    cliente = _ClienteFake({9057952: BOTELLA_VIGENTE})
    obj_vigente, ids_cadena = await repo._resolver_cadena_objetos(cliente, 9057909, BOTELLA_VIEJA)
    assert obj_vigente is BOTELLA_VIGENTE
    assert ids_cadena == {9057909, 9057952}
    assert cliente.llamadas == [9057952]


@pytest.mark.asyncio
async def test_resolver_cadena_multi_hop():
    obj_a = {"id": 1, "hist": [{"id": 1, "next_id": 2}], "tp": []}
    obj_b = {"id": 2, "hist": [{"id": 1, "next_id": 2}, {"id": 2, "next_id": 3}], "tp": []}
    obj_c = {"id": 3, "hist": [{"id": 2, "next_id": 3}, {"id": 3, "next_id": 0}], "tp": [{"class": 51, "id_to": 99}]}
    cliente = _ClienteFake({2: obj_b, 3: obj_c})
    obj_vigente, ids_cadena = await repo._resolver_cadena_objetos(cliente, 1, obj_a)
    assert obj_vigente is obj_c
    assert ids_cadena == {1, 2, 3}
    assert cliente.llamadas == [2, 3]


@pytest.mark.asyncio
async def test_resolver_cadena_ciclo_no_cuelga():
    obj_a = {"id": 1, "hist": [{"id": 1, "next_id": 2}], "tp": []}
    obj_b = {"id": 2, "hist": [{"id": 2, "next_id": 1}], "tp": []}  # vuelve a 1: ciclo
    cliente = _ClienteFake({2: obj_b})
    obj_vigente, ids_cadena = await repo._resolver_cadena_objetos(cliente, 1, obj_a)
    assert obj_vigente is obj_b  # se detiene en el primer visitado repetido
    assert ids_cadena == {1, 2}
    assert cliente.llamadas == [2]  # nunca vuelve a pedir 1


@pytest.mark.asyncio
async def test_resolver_cadena_hop_intermedio_404_no_aborta():
    obj_a = {"id": 1, "hist": [{"id": 1, "next_id": 2}], "tp": []}
    cliente = _ClienteFake({}, errores={2: CromoClientError("no existe", status_code=404)})
    obj_vigente, ids_cadena = await repo._resolver_cadena_objetos(cliente, 1, obj_a)
    assert obj_vigente is obj_a  # devuelve lo último que tenía, sin tp
    assert ids_cadena == {1}


# ── Anclaje de extremo ────────────────────────────────────────────────────────


def test_anclar_extremo_normaliza_id_de_version_al_n_id_local():
    from core.services.cromo import parser as cromo_parser

    cable = cromo_parser.parse_cable(CABLES_DIRECTOS["9203453"])
    assert cable.extremo_b_n_id == 9057952  # crudo: id de versión, confirmado real
    repo._anclar_extremo_a_botella(cable, 9057909, {9057909, 9057952})
    assert cable.extremo_b_n_id == 9057909  # anclado al n_id estable local
    assert cable.extremo_a_n_id == 9158719  # extremo ajeno a la cadena: intacto


def test_anclar_extremo_no_toca_nada_fuera_de_la_cadena():
    from core.services.cromo import parser as cromo_parser

    cable = cromo_parser.parse_cable(CABLES_DIRECTOS["9203453"])
    original_a, original_b = cable.extremo_a_n_id, cable.extremo_b_n_id
    repo._anclar_extremo_a_botella(cable, 123456, {123456})  # ninguno de los extremos está en la cadena
    assert (cable.extremo_a_n_id, cable.extremo_b_n_id) == (original_a, original_b)


# ── Detección end-to-end con datos reales (caso B2-FO-CAR) ───────────────────


@pytest.mark.asyncio
async def test_detectar_cables_faltantes_caso_real_b2_fo_car():
    cliente = _ClienteFake(
        {
            9057909: BOTELLA_VIEJA,
            9057952: BOTELLA_VIGENTE,
            **{int(n_id): obj for n_id, obj in CABLES_DIRECTOS.items()},
        }
    )
    sesion = _SesionFake({(CromoBotella, 9057909): _botella_local()})

    resultado = await repo.detectar_cables_faltantes(cliente, sesion, 9057909)

    assert resultado.botella_n_id == 9057909
    assert set(resultado.ids_cadena) == {9057909, 9057952}
    assert {c.n_id for c in resultado.cables} == {9062238, 9062294, 9181799, 9155193, 9146318, 9134941}
    assert all(c.estado_local == "FALTA" for c in resultado.cables)  # confirmado: 0 filas locales hoy
    assert len(resultado.cables_pendientes) == 6
    # el anclaje corrigió el extremo que apuntaba al id de versión (9057952) al n_id local (9057909)
    for cable in resultado.cables:
        assert 9057909 in (cable.extremo_a_n_id, cable.extremo_b_n_id)


@pytest.mark.asyncio
async def test_detectar_cables_faltantes_botella_inexistente_local_404():
    cliente = _ClienteFake({})
    sesion = _SesionFake()
    with pytest.raises(ObjetoNoEncontrado):
        await repo.detectar_cables_faltantes(cliente, sesion, 9057909)
    assert cliente.llamadas == []  # no le pega a Cromo si ni existe localmente


@pytest.mark.asyncio
async def test_detectar_cables_faltantes_n_id_no_existe_en_cromo_404():
    cliente = _ClienteFake({}, errores={9057909: CromoClientError("no existe", status_code=404)})
    sesion = _SesionFake({(CromoBotella, 9057909): _botella_local()})
    with pytest.raises(ObjetoNoEncontrado):
        await repo.detectar_cables_faltantes(cliente, sesion, 9057909)


@pytest.mark.asyncio
async def test_detectar_cables_faltantes_cable_ya_vinculado_correctamente_es_ok():
    cable_obj = CABLES_DIRECTOS["9203453"]
    cliente = _ClienteFake({9057909: BOTELLA_VIEJA, 9057952: BOTELLA_VIGENTE, **{n_id: cable_obj for n_id in (9203453, 9216553, 9204260, 9205381, 9206644, 9203500)}})
    fila_existente = CromoCable(n_id=9062238, version_id=1, vmax=264912, extremo_a_n_id=9158719, extremo_b_n_id=9057909, payload_raw={})
    sesion = _SesionFake({(CromoBotella, 9057909): _botella_local(), (CromoCable, 9062238): fila_existente})

    resultado = await repo.detectar_cables_faltantes(cliente, sesion, 9057909)

    detectado = next(c for c in resultado.cables if c.n_id == 9062238)
    assert detectado.estado_local == "OK"


@pytest.mark.asyncio
async def test_detectar_cables_faltantes_cable_existente_con_extremo_viejo_es_desactualizado():
    cable_obj = CABLES_DIRECTOS["9203453"]
    cliente = _ClienteFake({9057909: BOTELLA_VIEJA, 9057952: BOTELLA_VIGENTE, **{n_id: cable_obj for n_id in (9203453, 9216553, 9204260, 9205381, 9206644, 9203500)}})
    # Fila local "como la deja hoy una ingesta regular sin anclaje": extremo_b apunta al id de
    # versión (9057952), no al n_id estable (9057909).
    fila_existente = CromoCable(n_id=9062238, version_id=1, vmax=264912, extremo_a_n_id=9158719, extremo_b_n_id=9057952, payload_raw={})
    sesion = _SesionFake({(CromoBotella, 9057909): _botella_local(), (CromoCable, 9062238): fila_existente})

    resultado = await repo.detectar_cables_faltantes(cliente, sesion, 9057909)

    detectado = next(c for c in resultado.cables if c.n_id == 9062238)
    assert detectado.estado_local == "DESACTUALIZADO"


# ── Repoblación ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repoblar_cables_sin_pendientes_no_crea_corrida():
    # Simplificación deliberada: los 6 `id_to` de BOTELLA_VIGENTE.tp[] resuelven al MISMO objeto de
    # fixture (n_id real 9062238) — sólo importa que, tras el anclaje, su único extremo relevante
    # ya coincida con la fila local (OK), para que `cables_pendientes` quede vacío.
    cable_obj = CABLES_DIRECTOS["9203453"]
    cliente = _ClienteFake({9057909: BOTELLA_VIEJA, 9057952: BOTELLA_VIGENTE, **{n_id: cable_obj for n_id in (9203453, 9216553, 9204260, 9205381, 9206644, 9203500)}})
    fila_ok = CromoCable(n_id=9062238, version_id=1, vmax=264912, extremo_a_n_id=9158719, extremo_b_n_id=9057909, payload_raw={})
    sesion = _SesionFake({(CromoBotella, 9057909): _botella_local(), (CromoCable, 9062238): fila_ok})

    resultado = await repo.repoblar_cables(cliente, sesion, botella_n_id=9057909, usuario="tester")

    assert resultado.corrida_id is None
    assert resultado.creados == resultado.actualizados == resultado.errores == 0


@pytest.mark.asyncio
async def test_repoblar_cables_crea_faltantes_via_upsert_versionado():
    cliente = _ClienteFake(
        {9057909: BOTELLA_VIEJA, 9057952: BOTELLA_VIGENTE, **{int(n_id): obj for n_id, obj in CABLES_DIRECTOS.items()}}
    )
    sesion = _SesionFake({(CromoBotella, 9057909): _botella_local()})

    resultado = await repo.repoblar_cables(cliente, sesion, botella_n_id=9057909, usuario="tester")

    assert resultado.corrida_id is not None
    assert resultado.creados == 6
    assert resultado.errores == 0
    cables_creados = [o for o in sesion.agregados if isinstance(o, CromoCable)]
    assert len(cables_creados) == 6
    assert all(9057909 in (c.extremo_a_n_id, c.extremo_b_n_id) for c in cables_creados)


@pytest.mark.asyncio
async def test_repoblar_cables_desactualizado_usa_upsert_forzado_pese_a_mismo_vmax():
    cable_obj = CABLES_DIRECTOS["9203453"]
    cliente = _ClienteFake({9057909: BOTELLA_VIEJA, 9057952: BOTELLA_VIGENTE, **{n_id: cable_obj for n_id in (9203453, 9216553, 9204260, 9205381, 9206644, 9203500)}})
    # Mismo vmax que el vigente (264912): un upsert_versionado normal lo clasificaría SIN_CAMBIOS
    # y nunca corregiría el extremo — este es exactamente el caso real confirmado (Paso 0).
    fila_existente = CromoCable(n_id=9062238, version_id=1, vmax=264912, extremo_a_n_id=9158719, extremo_b_n_id=9057952, payload_raw={})
    sesion = _SesionFake({(CromoBotella, 9057909): _botella_local(), (CromoCable, 9062238): fila_existente})

    resultado = await repo.repoblar_cables(cliente, sesion, botella_n_id=9057909, usuario="tester")

    item = next(i for i in resultado.detalle if i.n_id == 9062238)
    assert item.accion == "ACTUALIZADA"  # upsert_forzado, no SIN_CAMBIOS
    assert fila_existente.extremo_b_n_id == 9057909  # corregido


@pytest.mark.asyncio
async def test_repoblar_cables_fallo_parcial_no_aborta_el_resto(monkeypatch):
    import core.services.cromo.ingesta as ingesta_mod

    cliente = _ClienteFake(
        {9057909: BOTELLA_VIEJA, 9057952: BOTELLA_VIGENTE, **{int(n_id): obj for n_id, obj in CABLES_DIRECTOS.items()}}
    )
    sesion = _SesionFake({(CromoBotella, 9057909): _botella_local()})

    original_upsert_versionado = ingesta_mod.upsert_versionado

    async def upsert_versionado_que_rompe_un_cable(sesion_, modelo_cls, dominio_obj, campos):
        if modelo_cls is CromoCable and dominio_obj.n_id == 9062294:
            raise RuntimeError("boom")
        return await original_upsert_versionado(sesion_, modelo_cls, dominio_obj, campos)

    # repoblacion_service llama a través del módulo (`ingesta.upsert_versionado`), no de un import
    # directo del símbolo — parcheable así, sin tocar el fallo real de la fase de detección.
    monkeypatch.setattr(ingesta_mod, "upsert_versionado", upsert_versionado_que_rompe_un_cable)

    resultado = await repo.repoblar_cables(cliente, sesion, botella_n_id=9057909, usuario="tester")

    assert resultado.errores == 1
    assert resultado.creados == 5  # los otros 5 se procesaron igual
    item_roto = next(i for i in resultado.detalle if i.n_id == 9062294)
    assert item_roto.accion == "ERROR"


@pytest.mark.asyncio
async def test_repoblar_cables_doble_click_segunda_vez_sin_cambios():
    cliente = _ClienteFake(
        {9057909: BOTELLA_VIEJA, 9057952: BOTELLA_VIGENTE, **{int(n_id): obj for n_id, obj in CABLES_DIRECTOS.items()}}
    )
    sesion = _SesionFake({(CromoBotella, 9057909): _botella_local()})

    primero = await repo.repoblar_cables(cliente, sesion, botella_n_id=9057909, usuario="tester")
    assert primero.creados == 6

    segundo = await repo.repoblar_cables(cliente, sesion, botella_n_id=9057909, usuario="tester")
    assert segundo.corrida_id is None  # ya no quedan pendientes: no crea una segunda corrida
    assert segundo.creados == segundo.actualizados == segundo.errores == 0
