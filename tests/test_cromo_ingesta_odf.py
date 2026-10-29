# Nombre de archivo: test_cromo_ingesta_odf.py
# Ubicación de archivo: tests/test_cromo_ingesta_odf.py
# Descripción: Tests de la ingesta de Cromo Red: ODFs (clase 69), ODF Nodo (clase 86) y resolución de servicio de conectores

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo import ingesta
from core.services.cromo.alias_service import AliasBotella
from core.services.cromo.client import CromoClientError
from core.services.cromo.modelos import ConectorOdf
from db.models.cromo import (
    CromoIngestaCorrida,
    CromoIngestaEvento,
    CromoOdf,
    CromoOdfConector,
)
from tests.soporte_cromo_ingesta import (
    _ClientePaginado,
    _SesionFake,
    _SesionFakeCorrida,
)
from tests.soporte_cromo_ingesta import geometria_fo  # noqa: F401 - fixture


# ── ODFs (Task 3, submódulo ODFs, clase 69) ──────────────────────────────────


class _ClienteGetInnerFake:
    """Fake de `CromoClient.get_inner` — diagnóstico real (2026-08-31): el `inner[]` embebido en
    el barrido de colección (`show=ALL`) es la forma LIVIANA, sin el atributo id=62 de servicio
    directo; ese atributo sólo viaja en la respuesta de `GET /db/objects/{id}/inner`, una llamada
    por objeto que `_procesar_odf_directo` hace aparte."""

    def __init__(self, respuesta: Optional[dict] = None, excepcion: Optional[Exception] = None) -> None:
        self._respuesta = respuesta if respuesta is not None else {"response": []}
        self._excepcion = excepcion

    async def get_inner(self, n_id: int) -> dict:
        if self._excepcion is not None:
            raise self._excepcion
        return self._respuesta


@pytest.mark.asyncio
async def test_procesar_odf_directo_crea_y_registra_evento():
    obj = {
        "id": 900010,
        "n_id": 800010,
        "class": 69,
        "vmax": 1,
        "at": [{"id": 34, "value": "ODF Calle Falsa 123"}, {"id": 47, "value": "Metrotel"}],
        "tp": [{"class": 51, "n_id": 6613848, "id_to": 9739619}],
    }
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    cliente = _ClienteGetInnerFake()

    await ingesta._procesar_odf_directo(cliente, sesion, corrida_id=1, obj=obj, contadores=contadores)

    assert contadores.leidas == 1
    assert contadores.creadas == 1
    assert contadores.errores == 0
    odfs_agregados = [o for o in sesion.agregados if isinstance(o, CromoOdf)]
    assert len(odfs_agregados) == 1
    assert odfs_agregados[0].n_id == 800010
    assert odfs_agregados[0].nombre == "ODF Calle Falsa 123"
    assert odfs_agregados[0].cables_asociados == [6613848]
    eventos = [o for o in sesion.agregados if isinstance(o, CromoIngestaEvento)]
    assert len(eventos) == 1
    assert eventos[0].accion == "CREADA"
    assert eventos[0].n_id == 800010
    assert eventos[0].clase == ingesta.CLASE_ODF


@pytest.mark.asyncio
async def test_procesar_odf_directo_guarda_conectores_via_get_inner_completo():
    """El `inner[]` embebido en el barrido de colección es la forma LIVIANA (sin atributo id=62) —
    sólo sirve para detectar "esta ODF tiene patchera" y disparar `cliente.get_inner()`, cuya
    respuesta completa (con id=62) es la que efectivamente se parsea y guarda."""
    obj = {
        "id": 900010,
        "n_id": 800010,
        "class": 69,
        "vmax": 1,
        "at": [{"id": 34, "value": "ODF Calle Falsa 123"}],
        # Liviano a propósito: sin atributo id=62 ni bandeja_modelo, sólo para que "inner" sea truthy.
        "inner": [
            {"id": 8539330, "n_id": 8539330, "class": 135, "name": "O-1238223-1"},
            {"id": 8539345, "n_id": 8539345, "class": 136, "name": "15", "parent": 8539330},
        ],
    }
    inner_completo = {
        "response": [
            {"id": 8539330, "n_id": 8539330, "class": 135, "name": "O-1238223-1", "at": [{"id": 89, "value": "SC-APCx24"}]},
            {
                "id": 8539345, "n_id": 8539345, "class": 136, "name": "15", "parent": 8539330,
                "at": [{"id": 62, "value": "41140"}],
                "tp": [{"id_to": 6777271, "class": 130}],
            },
        ]
    }
    cliente = _ClienteGetInnerFake(respuesta=inner_completo)
    sesion = _SesionFake(respuestas_execute={"FROM app.cromo_pelos": [(6777271, "61943", 51)]})
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_odf_directo(cliente, sesion, corrida_id=1, obj=obj, contadores=contadores)

    assert contadores.errores == 0
    conectores = [o for o in sesion.agregados if isinstance(o, CromoOdfConector)]
    assert len(conectores) == 1
    c = conectores[0]
    assert c.n_id == 8539345
    assert c.odf_n_id == 800010
    assert c.bandeja_nombre == "O-1238223-1"
    assert c.bandeja_modelo == "SC-APCx24"
    assert c.numero_conector == "15"
    assert c.pelo_n_id == 6777271
    assert c.servicio_numero_atributo == "41140"
    # El regex del pelo ("61943") es mayor que el atributo ("41140") -> gana como resuelto.
    assert c.servicio_resuelto == "61943"
    assert c.servicio_id_historico == "41140"


_INNER_KORN_CON_FUSION_ODF = [
    {"id": 8539330, "class": 135, "name": "O-1259853-3"},
    {
        "id": 8685667, "class": 136, "name": "39", "at": [{"id": 71, "value": "8539330"}],
        "tp": [{"id_to": 8884671, "class": 141}],
    },
    {
        "id": 8884671, "class": 141, "name": "39-39",
        "tp": [{"id_to": 8685667, "class": 136}, {"id_to": 7914406, "class": 130}],
    },
]


@pytest.mark.asyncio
async def test_procesar_odf_directo_guarda_pelo_y_fusion_de_odf_141():
    """Conector cuyo `tp` apunta a una fusión de ODF (141): el pelo sale de la 141 y la 141 queda
    en `fusion_odf_n_id` (caso real KORN O-1259853-3:39 → 8884671 → pelo 7914406)."""
    obj = {
        "id": 6646686, "n_id": 6646686, "class": 69, "vmax": 1,
        "at": [{"id": 34, "value": "NODO Alejandro KORN"}],
        "inner": [{"id": 8685667, "class": 136}],
    }
    cliente = _ClienteGetInnerFake(respuesta={"response": _INNER_KORN_CON_FUSION_ODF})
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_odf_directo(cliente, sesion, corrida_id=1, obj=obj, contadores=contadores)

    assert contadores.errores == 0
    [c] = [o for o in sesion.agregados if isinstance(o, CromoOdfConector)]
    assert c.n_id == 8685667
    assert c.pelo_n_id == 7914406
    assert c.fusion_odf_n_id == 8884671


@pytest.mark.asyncio
async def test_relevar_odf_guarda_pelo_y_fusion_de_odf_141(monkeypatch):
    from core.services.cromo import normalizacion_consistencia_service as norm

    obj = {"id": 6646686, "n_id": 6646686, "class": 69, "at": [{"id": 34, "value": "NODO Alejandro KORN"}]}
    guardados = []

    async def _fetch(cliente, n_id):
        return obj

    async def _upsert(sesion, modelo, dom, campos):
        return "ACTUALIZADA"

    async def _evento(*args, **kwargs):
        return None

    async def _upsert_simple(sesion, modelo, dom, campos):
        guardados.append((dom, campos))

    async def _resolver(sesion, conectores):
        return None

    monkeypatch.setattr(norm.id_dual_resolver, "fetch_objeto", _fetch)
    monkeypatch.setattr(norm.ingesta, "upsert_forzado", _upsert)
    monkeypatch.setattr(norm.ingesta, "registrar_evento", _evento)
    monkeypatch.setattr(norm.ingesta, "upsert_simple", _upsert_simple)
    monkeypatch.setattr(norm.ingesta, "resolver_servicio_conectores", _resolver)

    await norm.relevar_odf(
        _ClienteGetInnerFake(respuesta={"response": _INNER_KORN_CON_FUSION_ODF}), _SesionFake(), 1, 6646686
    )

    [(conector, campos)] = guardados
    assert (conector.pelo_n_id, conector.fusion_odf_n_id) == (7914406, 8884671)
    assert "fusion_odf_n_id" in campos


@pytest.mark.asyncio
async def test_procesar_odf_directo_get_inner_falla_no_pierde_el_odf():
    """Un fallo de red en `get_inner` (segunda llamada, sólo enriquece conectores) no debe hacer
    perder el ODF ya parseado en la primera parte del savepoint — se degrada a conectores sin
    atributo directo en vez de abortar todo."""
    obj = {
        "id": 900012, "n_id": 800012, "class": 69, "vmax": 1,
        "at": [{"id": 34, "value": "ODF Con Falla De Red"}],
        "inner": [{"id": 8539345, "n_id": 8539345, "class": 136, "name": "15", "parent": 8539330}],
    }
    cliente = _ClienteGetInnerFake(excepcion=CromoClientError("timeout"))
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()

    await ingesta._procesar_odf_directo(cliente, sesion, corrida_id=1, obj=obj, contadores=contadores)

    assert contadores.errores == 0
    odfs_agregados = [o for o in sesion.agregados if isinstance(o, CromoOdf)]
    assert len(odfs_agregados) == 1
    assert odfs_agregados[0].n_id == 800012
    # El conector se guarda igual, sin atributo directo (degradado a sólo la forma liviana).
    conectores = [o for o in sesion.agregados if isinstance(o, CromoOdfConector)]
    assert len(conectores) == 1
    assert conectores[0].servicio_numero_atributo is None


@pytest.mark.asyncio
async def test_procesar_odf_directo_sin_inner_no_llama_get_inner_ni_guarda_conectores():
    obj = {"id": 900011, "n_id": 800011, "class": 69, "vmax": 1, "at": [{"id": 34, "value": "ODF Sin Inner"}]}
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    llamadas: list[int] = []

    class _ClienteEspia(_ClienteGetInnerFake):
        async def get_inner(self, n_id: int) -> dict:
            llamadas.append(n_id)
            return await super().get_inner(n_id)

    await ingesta._procesar_odf_directo(_ClienteEspia(), sesion, corrida_id=1, obj=obj, contadores=contadores)

    assert llamadas == []
    assert [o for o in sesion.agregados if isinstance(o, CromoOdfConector)] == []


# ── Resolución de servicio de conectores (atributo vs. regex del pelo) ───────


def test_mayor_menor_servicio_numero_compara_numericamente():
    assert ingesta.mayor_menor_servicio_numero("41140", "61943") == ("61943", "41140")
    assert ingesta.mayor_menor_servicio_numero("61943", "41140") == ("61943", "41140")


def test_mayor_menor_servicio_numero_no_numerico_cae_a_string():
    assert ingesta.mayor_menor_servicio_numero("O1C1", "A1B2") == ("O1C1", "A1B2")


@pytest.mark.asyncio
async def test_resolver_servicio_conectores_ambos_presentes_y_distintos():
    conector = ConectorOdf(
        n_id=1, odf_n_id=800010, bandeja_n_id=None, bandeja_nombre=None, bandeja_modelo=None,
        numero_conector="15", pelo_n_id=6777271, servicio_numero_atributo="41140",
    )
    sesion = _SesionFake(respuestas_execute={"FROM app.cromo_pelos": [(6777271, "61943", 51)]})

    await ingesta.resolver_servicio_conectores(sesion, [conector])

    assert conector.servicio_resuelto == "61943"
    assert conector.servicio_id_historico == "41140"


@pytest.mark.asyncio
async def test_resolver_servicio_conectores_ambos_presentes_y_coinciden_sin_historico():
    conector = ConectorOdf(
        n_id=1, odf_n_id=800010, bandeja_n_id=None, bandeja_nombre=None, bandeja_modelo=None,
        numero_conector="5", pelo_n_id=6777260, servicio_numero_atributo="38105",
    )
    sesion = _SesionFake(respuestas_execute={"FROM app.cromo_pelos": [(6777260, "38105", 51)]})

    await ingesta.resolver_servicio_conectores(sesion, [conector])

    assert conector.servicio_resuelto == "38105"
    assert conector.servicio_id_historico is None


@pytest.mark.asyncio
async def test_resolver_servicio_conectores_solo_atributo_sin_pelo():
    conector = ConectorOdf(
        n_id=1, odf_n_id=800010, bandeja_n_id=None, bandeja_nombre=None, bandeja_modelo=None,
        numero_conector="20", pelo_n_id=None, servicio_numero_atributo="12345",
    )
    sesion = _SesionFake()

    await ingesta.resolver_servicio_conectores(sesion, [conector])

    assert conector.servicio_resuelto == "12345"
    assert conector.servicio_id_historico is None


@pytest.mark.asyncio
async def test_resolver_servicio_conectores_libre_sin_ninguna_senal():
    conector = ConectorOdf(
        n_id=1, odf_n_id=800010, bandeja_n_id=None, bandeja_nombre=None, bandeja_modelo=None,
        numero_conector="14", pelo_n_id=6777270, servicio_numero_atributo=None,
    )
    sesion = _SesionFake(respuestas_execute={"FROM app.cromo_pelos": [(6777270, None, 51)]})

    await ingesta.resolver_servicio_conectores(sesion, [conector])

    assert conector.servicio_resuelto is None
    assert conector.servicio_id_historico is None


@pytest.mark.asyncio
async def test_resolver_servicio_conectores_elige_el_pelo_ingerido_entre_los_candidatos():
    """Caso real TASA conector 2: el primer pelo de `tp` es de un cable de tercero (clase 59) que
    no está en `cromo_pelos`; el segundo es el del cable propio. El conector tiene que quedar
    vinculado al que existe, o el Servicio pierde esa posición de ODF."""
    conector = ConectorOdf(
        n_id=8595049, odf_n_id=6644198, bandeja_n_id=None, bandeja_nombre=None, bandeja_modelo=None,
        numero_conector="2", pelo_n_id=7968239, servicio_numero_atributo="42351",
        pelos_candidatos=[7968239, 6976963],
    )
    sesion = _SesionFake(respuestas_execute={"FROM app.cromo_pelos": [(6976963, "42351", 51)]})

    await ingesta.resolver_servicio_conectores(sesion, [conector])

    assert conector.pelo_n_id == 6976963
    assert conector.servicio_resuelto == "42351"


@pytest.mark.asyncio
async def test_resolver_servicio_conectores_ningun_candidato_ingerido_conserva_el_primero():
    """Si ninguno de los dos pelos está ingerido (ODF TECO, ambos de terceros) no se inventa nada:
    queda el primero, igual que antes."""
    conector = ConectorOdf(
        n_id=1, odf_n_id=6644360, bandeja_n_id=None, bandeja_nombre=None, bandeja_modelo=None,
        numero_conector="3", pelo_n_id=7968250, servicio_numero_atributo="42351",
        pelos_candidatos=[7968250, 7968010],
    )
    sesion = _SesionFake(respuestas_execute={"FROM app.cromo_pelos": []})

    await ingesta.resolver_servicio_conectores(sesion, [conector])

    assert conector.pelo_n_id == 7968250
    assert conector.servicio_resuelto == "42351"


@pytest.mark.asyncio
async def test_procesar_odf_directo_objeto_malformado_no_rompe_registra_error():
    obj = {"class": 69, "id": 1, "n_id": 1}  # sin vmax coherente: fuerza un camino de error real
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    sesion._existentes[(CromoOdf, 1)] = object()  # sin atributo .vmax -> AttributeError real al comparar

    await ingesta._procesar_odf_directo(
        _ClienteGetInnerFake(), sesion, corrida_id=1, obj=obj, contadores=contadores
    )

    assert contadores.errores == 1
    assert contadores.creadas == 0
    eventos_error = [o for o in sesion.agregados if getattr(o, "accion", None) == "ERROR"]
    assert len(eventos_error) == 1
    assert eventos_error[0].n_id == 1


@pytest.mark.asyncio
async def test_fase_odfs_procesa_pagina_y_registra_creada_actualizada_sin_cambios():
    """Contrato central del brief: `fase_odfs` crea/actualiza filas `CromoOdf` a partir de una
    respuesta paginada fake, y registra correctamente los eventos CREADA/ACTUALIZADA —
    mismo objeto (n_id=800100) a través de tres páginas con `vmax` creciente y luego repetido.
    El tercer arribo (SIN_CAMBIOS) no genera evento (decisión 2026-10-27), pero sí suma al contador
    de la corrida."""

    def _odf_obj(vmax: int) -> dict[str, Any]:
        return {
            "id": 900100 + vmax,
            "n_id": 800100,
            "class": 69,
            "vmax": vmax,
            "at": [{"id": 34, "value": "ODF Calle 9 Nro 593 PILAR"}],
        }

    cliente = _ClientePaginado(
        [
            {"response": [_odf_obj(1)]},  # CREADA
            {"response": [_odf_obj(2)]},  # ACTUALIZADA (vmax cambió)
            {"response": [_odf_obj(2)]},  # SIN_CAMBIOS (mismo vmax)
        ]
    )
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)

    await ingesta.fase_odfs(cliente, sesion, corrida, contadores, psize=5, max_paginas=None)

    assert contadores.leidas == 3
    assert contadores.creadas == 1
    assert contadores.actualizadas == 1
    assert contadores.sin_cambios == 1
    assert contadores.errores == 0
    odfs_agregados = [o for o in sesion.agregados if isinstance(o, CromoOdf)]
    assert len(odfs_agregados) == 1  # misma fila, actualizada in-place — no una segunda inserción
    assert odfs_agregados[0].vmax == 2
    eventos_del_odf = [
        o.accion for o in sesion.agregados if isinstance(o, CromoIngestaEvento) and o.n_id == 800100
    ]
    assert eventos_del_odf == ["CREADA", "ACTUALIZADA"]
    assert corrida.creadas == 1
    assert corrida.actualizadas == 1
    assert corrida.sin_cambios == 1


@pytest.mark.asyncio
async def test_fase_odfs_pide_show_all_desde_el_arranque(monkeypatch):
    """A diferencia de `fase_cables` (`["SHOW", "TIME"]`), `fase_odfs` debe pedir `show=["ALL"]`
    desde la primera página — es lo único que expone tanto `tp[]` (cables asociados) como
    `inner[]` (conectores de patchera, class 135/136, sumado 2026-08-31); `REL_ATTRIBUTE` solo no
    trae `inner[]` (confirmado real contra Cromo, ver docstring de `fase_odfs`)."""
    recibido: dict[str, Any] = {}

    class _ClienteCaptura:
        async def iterar_coleccion(self, filtro, *, psize=None, show=None, max_paginas=None):
            recibido["filtro"] = filtro
            recibido["show"] = show
            return
            yield  # pragma: no cover - hace de este método un generador async vacío

    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)

    await ingesta.fase_odfs(_ClienteCaptura(), sesion, corrida, contadores, psize=5, max_paginas=None)

    assert recibido["filtro"] == "69,86"
    assert ingesta.CLASES_ODF == (69, 86)
    assert ingesta.CLASE_ODF == 69
    assert recibido["show"] == ["ALL"]


@pytest.mark.asyncio
async def test_fase_odfs_pasa_alias_por_origen_a_procesar_odf_directo(monkeypatch):
    """Mismo contrato de firma que `fase_cables`/`fase_fusiones`: `alias_por_origen` se enhebra
    hasta `_procesar_odf_directo`, aunque este último no lo use para nada (ver su docstring)."""
    obj = {"id": 900200, "n_id": 800200, "class": 69, "vmax": 1, "at": []}
    cliente = _ClientePaginado([{"response": [obj]}])
    sesion = _SesionFake()
    contadores = ingesta.ContadoresCorrida()
    corrida = CromoIngestaCorrida(id=1)
    alias_por_origen = {10178728: AliasBotella(accion="fusionar", id_cromo_destino=999999)}
    recibido: dict[str, Any] = {}

    async def _procesar_fake(cliente, sesion, corrida_id, obj, contadores, *, alias_por_origen=None):
        recibido["alias_por_origen"] = alias_por_origen

    monkeypatch.setattr(ingesta, "_procesar_odf_directo", _procesar_fake)

    await ingesta.fase_odfs(
        cliente, sesion, corrida, contadores, psize=5, max_paginas=None, alias_por_origen=alias_por_origen
    )

    assert recibido["alias_por_origen"] is alias_por_origen


def test_solo_odf_apunta_a_las_clases_69_y_86():
    assert ingesta.MODOS_ACOTADOS["SOLO_ODF"].clases_objetivo == (69, 86)
    assert 86 in ingesta.CLASES_CONTEO


@pytest.mark.asyncio
async def test_continuar_corrida_solo_odf_suma_odf_y_odf_nodo_en_total_objetivo(monkeypatch):
    sesion = _SesionFakeCorrida()
    sesion._existentes[(CromoIngestaCorrida, 42)] = CromoIngestaCorrida(id=42, usuario="tester", estado="EN_CURSO")

    async def _fase_conteo_fake(cliente, **_kwargs):
        return {68: 100, 69: 7, 86: 3}

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ingesta, "fase_conteo", _fase_conteo_fake)
    monkeypatch.setattr(ingesta, "fase_odfs", _noop)

    corrida = await ingesta.continuar_corrida(
        cliente=object(), sesion=sesion, corrida_id=42, psize=5, max_paginas=None,
        clases=ingesta.CLASES_BOTELLA, modo="SOLO_ODF",
    )

    assert corrida.total_objetivo == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("clase", [69, 86])
async def test_relevar_odf_acepta_odf_y_odf_nodo_y_registra_la_clase_real(monkeypatch, clase):
    from core.services.cromo import normalizacion_consistencia_service as norm

    obj = {"id": 5, "n_id": 5, "class": clase, "at": [{"id": 34, "value": "NODO X"}], "inner": []}
    eventos = []

    async def _fetch(cliente, n_id):
        return obj

    async def _upsert(sesion, modelo, dom, campos):
        return "CREADA"

    async def _evento(sesion, corrida_id, n_id, cls, accion, detalle=None):
        eventos.append((n_id, cls, accion))

    class _Cliente:
        async def get_inner(self, n_id):
            return {"response": []}

    monkeypatch.setattr(norm.id_dual_resolver, "fetch_objeto", _fetch)
    monkeypatch.setattr(norm.ingesta, "upsert_forzado", _upsert)
    monkeypatch.setattr(norm.ingesta, "registrar_evento", _evento)

    accion = await norm.relevar_odf(_Cliente(), _SesionFake(), 1, 5)

    assert accion == "CREADA"
    assert eventos == [(5, clase, "CREADA")]


@pytest.mark.asyncio
async def test_relevar_odf_rechaza_una_clase_que_no_es_odf(monkeypatch):
    from core.services.cromo import normalizacion_consistencia_service as norm

    async def _fetch(cliente, n_id):
        return {"id": 5, "n_id": 5, "class": 51}

    monkeypatch.setattr(norm.id_dual_resolver, "fetch_objeto", _fetch)

    with pytest.raises(ValueError, match="no es una ODF"):
        await norm.relevar_odf(object(), _SesionFake(), 1, 5)
