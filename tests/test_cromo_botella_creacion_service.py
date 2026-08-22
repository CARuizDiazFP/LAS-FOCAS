# Nombre de archivo: test_cromo_botella_creacion_service.py
# Ubicación de archivo: tests/test_cromo_botella_creacion_service.py
# Descripción: Pruebas de creación puntual de una Botella Cromo desde Cromo en vivo ("ID dual"), sin red ni DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo import botella_creacion_service as servicio
from core.services.cromo.client import CromoClientError
from core.services.cromo.parser import ClaseExcluidaError
from core.services.cromo.verificador import ObjetoNoEncontrado
from db.models.cromo import CromoBotella

BOTELLA_N_ID = 9936406

OBJ_SIMPLE = {
    "id": BOTELLA_N_ID,
    "n_id": BOTELLA_N_ID,
    "class": 68,
    "hist": [],
    "tp": [{"type": 0, "nfrom": 0, "id_to": 111, "class": 51}],
    "at": [{"id": 34, "value": "B-NUEVA"}],
}

# Objeto vacío (sin tp): reporta el n_id solicitado por 'id', pero su hist[] apunta a la versión
# vigente con los datos completos (mismo patrón "ID dual" que BOTELLA_VIEJA/BOTELLA_VIGENTE en
# test_cromo_repoblacion_service.py).
OBJ_VACIO = {
    "id": BOTELLA_N_ID,
    "hist": [{"id": BOTELLA_N_ID, "next_id": 9936500}, {"id": 9936500, "next_id": 0}],
    "tp": [],
    "at": [],
}
OBJ_VIGENTE = {
    "id": 9936500,
    "n_id": 9936500,
    "class": 68,
    "hist": [{"id": BOTELLA_N_ID, "next_id": 9936500}, {"id": 9936500, "next_id": 0}],
    "tp": [{"type": 0, "nfrom": 0, "id_to": 111, "class": 51}],
    "at": [{"id": 34, "value": "B-VIGENTE"}],
}


class _NestedCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


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

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = 1


@pytest.mark.asyncio
async def test_crear_botella_caso_simple_sin_hist():
    cliente = _ClienteFake({BOTELLA_N_ID: OBJ_SIMPLE})
    sesion = _SesionFake()

    resultado = await servicio.crear_o_actualizar_botella_desde_vivo(
        cliente, sesion, n_id=BOTELLA_N_ID, usuario="tester"
    )

    assert resultado.accion == "CREADA"
    assert resultado.n_id == BOTELLA_N_ID
    assert resultado.nombre == "B-NUEVA"
    assert resultado.ids_cadena == [BOTELLA_N_ID]
    assert resultado.corrida_id is not None

    fila = sesion._existentes[(CromoBotella, BOTELLA_N_ID)]
    assert fila.n_id == BOTELLA_N_ID  # acá el reportado por Cromo coincide con el solicitado
    assert fila.nombre == "B-NUEVA"


@pytest.mark.asyncio
async def test_crear_botella_sigue_next_id_cuando_objeto_esta_vacio():
    """El n_id solicitado es un id de VERSIÓN: la cadena hist[]/next_id resuelve a 9936500, que es la
    identidad de linaje real que reporta Cromo. La fila local tiene que quedar bajo ESE n_id — si se
    la anclara al solicitado, la próxima corrida de ingesta traería el objeto bajo 9936500 y crearía
    una SEGUNDA fila: exactamente el duplicado "ID dual" que este plan busca evitar (hallazgo I1 de
    la revisión final, 2026-08-22)."""
    cliente = _ClienteFake({BOTELLA_N_ID: OBJ_VACIO, 9936500: OBJ_VIGENTE})
    sesion = _SesionFake()

    resultado = await servicio.crear_o_actualizar_botella_desde_vivo(
        cliente, sesion, n_id=BOTELLA_N_ID, usuario="tester"
    )

    assert resultado.accion == "CREADA"
    assert resultado.nombre == "B-VIGENTE"  # datos del objeto vigente
    assert set(resultado.ids_cadena) == {BOTELLA_N_ID, 9936500}
    assert resultado.n_id == 9936500  # el resultado expone la identidad FINAL, no la solicitada

    fila = sesion._existentes[(CromoBotella, 9936500)]
    assert fila.n_id == 9936500  # identidad de linaje que reportó Cromo
    assert fila.nombre == "B-VIGENTE"
    # nunca se crea una fila bajo el id de versión solicitado: sería la fila huérfana que ninguna
    # corrida futura vuelve a tocar, porque Cromo nunca reporta ese id como n_id de nada
    assert (CromoBotella, BOTELLA_N_ID) not in sesion._existentes


# Caso degenerado: Cromo devuelve el objeto vigente SIN `n_id` ni `id` propios (sin identidad
# utilizable). Es el único caso en que se cae al n_id solicitado como último recurso.
OBJ_SIN_IDENTIDAD = {
    "class": 68,
    "hist": [],
    "tp": [{"type": 0, "nfrom": 0, "id_to": 111, "class": 51}],
    "at": [{"id": 34, "value": "B-SIN-ID"}],
}


@pytest.mark.asyncio
async def test_crear_botella_cae_al_n_id_solicitado_si_cromo_no_reporta_identidad():
    cliente = _ClienteFake({BOTELLA_N_ID: OBJ_SIN_IDENTIDAD})
    sesion = _SesionFake()

    resultado = await servicio.crear_o_actualizar_botella_desde_vivo(
        cliente, sesion, n_id=BOTELLA_N_ID, usuario="tester"
    )

    assert resultado.accion == "CREADA"
    assert resultado.n_id == BOTELLA_N_ID  # sin mejor información, el solicitado es la identidad
    fila = sesion._existentes[(CromoBotella, BOTELLA_N_ID)]
    assert fila.n_id == BOTELLA_N_ID
    assert fila.nombre == "B-SIN-ID"


@pytest.mark.asyncio
async def test_crear_botella_404_si_no_existe_en_cromo():
    cliente = _ClienteFake({}, errores={BOTELLA_N_ID: CromoClientError("no existe", status_code=404)})
    sesion = _SesionFake()

    with pytest.raises(ObjetoNoEncontrado):
        await servicio.crear_o_actualizar_botella_desde_vivo(cliente, sesion, n_id=BOTELLA_N_ID, usuario="tester")


@pytest.mark.asyncio
async def test_crear_botella_identidad_ya_resuelta_si_ya_existe_localmente():
    cliente = _ClienteFake({BOTELLA_N_ID: OBJ_VACIO, 9936500: OBJ_VIGENTE})
    fila_existente = CromoBotella(n_id=9936500, version_id=1, vmax=1, nombre="Ya existe", clase=68, payload_raw={})
    sesion = _SesionFake({(CromoBotella, 9936500): fila_existente})

    with pytest.raises(servicio.IdentidadYaResueltaError) as exc_info:
        await servicio.crear_o_actualizar_botella_desde_vivo(cliente, sesion, n_id=BOTELLA_N_ID, usuario="tester")

    assert exc_info.value.n_id_solicitado == BOTELLA_N_ID
    assert exc_info.value.n_id_resuelto == 9936500
    assert (CromoBotella, BOTELLA_N_ID) not in sesion._existentes  # no se creó fila duplicada


@pytest.mark.asyncio
async def test_crear_botella_propaga_clase_excluida(monkeypatch):
    cliente = _ClienteFake({BOTELLA_N_ID: OBJ_SIMPLE})
    sesion = _SesionFake()

    def _parse_que_rompe(obj):
        raise ClaseExcluidaError(120, "ODF, no es Botella")

    monkeypatch.setattr(servicio.cromo_parser, "parse_botella", _parse_que_rompe)

    with pytest.raises(ClaseExcluidaError):
        await servicio.crear_o_actualizar_botella_desde_vivo(cliente, sesion, n_id=BOTELLA_N_ID, usuario="tester")


@pytest.mark.asyncio
async def test_crear_botella_respeta_nombre_editado_manual_en_llamada_repetida():
    cliente = _ClienteFake({BOTELLA_N_ID: OBJ_SIMPLE})
    sesion = _SesionFake()

    primero = await servicio.crear_o_actualizar_botella_desde_vivo(
        cliente, sesion, n_id=BOTELLA_N_ID, usuario="tester"
    )
    assert primero.accion == "CREADA"

    fila = sesion._existentes[(CromoBotella, BOTELLA_N_ID)]
    fila.nombre = "Corregido a mano"
    fila.nombre_editado_manual = True

    segundo = await servicio.crear_o_actualizar_botella_desde_vivo(
        cliente, sesion, n_id=BOTELLA_N_ID, usuario="tester"
    )
    assert segundo.accion == "ACTUALIZADA"
    assert fila.nombre == "Corregido a mano"  # no lo pisó
    assert segundo.nombre == "Corregido a mano"


@pytest.mark.asyncio
async def test_crear_botella_crea_corrida_sintetica_manual_crear_botella_vivo(monkeypatch):
    import core.services.cromo.ingesta as ingesta_mod

    cliente = _ClienteFake({BOTELLA_N_ID: OBJ_SIMPLE})
    sesion = _SesionFake()

    llamadas: list[dict[str, Any]] = []
    original_iniciar_corrida = ingesta_mod.iniciar_corrida

    async def _iniciar_corrida_espia(sesion_, *, usuario, psize, max_paginas, clases, params_extra=None):
        llamadas.append(params_extra or {})
        return await original_iniciar_corrida(
            sesion_, usuario=usuario, psize=psize, max_paginas=max_paginas, clases=clases, params_extra=params_extra
        )

    monkeypatch.setattr(servicio.ingesta, "iniciar_corrida", _iniciar_corrida_espia)

    await servicio.crear_o_actualizar_botella_desde_vivo(cliente, sesion, n_id=BOTELLA_N_ID, usuario="tester")

    assert len(llamadas) == 1
    assert llamadas[0]["tipo"] == "MANUAL_CREAR_BOTELLA_VIVO"
    assert llamadas[0]["n_id"] == BOTELLA_N_ID
