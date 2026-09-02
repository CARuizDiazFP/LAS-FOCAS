# Nombre de archivo: test_cromo_empalmes.py
# Ubicación de archivo: tests/test_cromo_empalmes.py
# Descripción: Pruebas del armado de empalmes (fusiones) de una Botella Cromo y agrupación de Splitters, sin DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo import empalmes


class _ResultadoFilas:
    def __init__(self, filas: list[tuple]) -> None:
        self._filas = filas

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFake:
    """Reemplaza sólo `execute`: matchea por substring de la consulta compilada, mismo patrón que
    `test_cromo_verificador.py`. Claves elegidas para no solaparse entre sí (ver comentario en cada
    query de `empalmes.py`: la CTE `cables_botella` reusa `extremo_a_n_id`/`extremo_b_n_id`, por eso
    la clave del chequeo de existencia usa el prefijo `SELECT 1` que sólo tiene esa query)."""

    def __init__(self, respuestas: Optional[dict[str, list[tuple]]] = None) -> None:
        self._respuestas = respuestas or {}

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFilas:
        texto = str(stmt)
        for clave, filas in self._respuestas.items():
            if clave in texto:
                return _ResultadoFilas(filas)
        return _ResultadoFilas([])


def _fila_fusion(
    fusion_n_id: int,
    nombre_par: Optional[str],
    pelo_a: Optional[tuple],
    pelo_b: Optional[tuple],
) -> tuple:
    """Arma una fila cruda como la devuelve `_SQL_EMPALMES_DE_BOTELLA`: (n_id, nombre_par, *pelo_a[10], *pelo_b[10]).
    `pelo_a`/`pelo_b` son
    (n_id, cable_n_id, cable_nombre, tubo_n_id, tubo_color, numero_pelo, orden, color, servicio_raw, servicio_numero) o None.
    """
    vacio = (None,) * 10
    return (fusion_n_id, nombre_par, *(pelo_a or vacio), *(pelo_b or vacio))


@pytest.mark.asyncio
async def test_empalmes_de_botella_no_encontrada():
    sesion = _SesionFake()
    with pytest.raises(empalmes.ObjetoNoEncontrado):
        await empalmes.empalmes_de_botella(sesion, 999)


@pytest.mark.asyncio
async def test_empalmes_de_botella_fusion_simple():
    fila = _fila_fusion(
        9345925,
        "17-1",
        (9345620, 9345595, "F-ALB-SLL-A-A", 500, "AZ-R", "17", 4, "GR", "FO 12345", "12345"),
        (9344768, 9344766, "F-JBA-290", 600, "AZ", "1", 0, "AZ", "FO 99999", "99999"),
    )
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_botellas": [(6630979, "Cra Test 123")],
            "FROM app.cromo_fusiones": [fila],
        }
    )

    resultado = await empalmes.empalmes_de_botella(sesion, 6630979)

    assert resultado.nombre == "Cra Test 123"
    assert len(resultado.empalmes) == 1
    empalme = resultado.empalmes[0]
    assert empalme.es_splitter is False
    assert empalme.pelo_origen.n_id == 9345620
    assert empalme.pelo_origen.cable_nombre == "F-ALB-SLL-A-A"
    assert empalme.pelo_destino.n_id == 9344768
    assert empalme.pelo_destino.cable_nombre == "F-JBA-290"
    assert empalme.pelo_origen.servicio_raw == "FO 12345"
    assert empalme.pelo_destino.servicio_numero == "99999"
    assert empalme.splitter_ratio is None
    # El selector de cable ahora incluye ambos extremos de cada fusión simple (A/B).
    assert {c.n_id for c in resultado.cables} == {9345595, 9344766}
    assert all(c.cantidad_empalmes == 1 for c in resultado.cables)


@pytest.mark.asyncio
async def test_empalmes_de_botella_splitter_agrupado_por_pelo_repetido():
    """Un mismo pelo de entrada (n_id=100) fusionado con 3 salidas distintas dentro de la misma
    botella se agrupa en una sola fila con `es_splitter=True` y `splitter_ratio=3` ("Splitter 1-3")."""
    origen = (100, 10, "Cable Entrada", 200, "AZ", "1", 0, "AZ")
    filas = [
        _fila_fusion(1, "1-1", (*origen, None, None), (201, 20, "Cable Salida 1", 300, "NR", "1", 0, "NR", None, None)),
        _fila_fusion(2, "1-2", (*origen, None, None), (202, 20, "Cable Salida 1", 300, "NR", "2", 1, "VR", None, None)),
        _fila_fusion(3, "1-3", (203, 20, "Cable Salida 1", 300, "NR", "3", 2, "AM", None, None), (*origen, None, None)),
    ]
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_botellas": [(1, "Botella Splitter")],
            "FROM app.cromo_fusiones": filas,
        }
    )

    resultado = await empalmes.empalmes_de_botella(sesion, 1)

    assert len(resultado.empalmes) == 1
    grupo = resultado.empalmes[0]
    assert grupo.es_splitter is True
    assert grupo.pelo_origen.n_id == 100
    assert grupo.splitter_ratio == 3
    assert {d.n_id for d in grupo.splitter_destinos} == {201, 202, 203}


@pytest.mark.asyncio
async def test_empalmes_de_botella_fusion_duplicada_no_se_clasifica_como_splitter():
    """Caso real (botella_n_id=9450157, 2026-08-24): la MISMA fusión física (idéntico par de pelos)
    quedó ingerida 3 veces bajo 3 `fusion.n_id` distintos (bug de duplicación de ingesta, análogo al
    "ID dual" ya resuelto para Cables en `repoblacion_service.py` pero no aplicado a Fusiones). Sin
    deduplicar por par de pelos antes de contar, se agrupaba como "Splitter 1-3" — una fusión 1 a 1
    real nunca debe mostrarse como Splitter."""
    origen = (9443224, 10, "Cable A", 200, "AZ", "1", 0, "AZ")
    destino = (9447426, 20, "Cable B", 300, "NR", "1", 0, "NR")
    filas = [
        _fila_fusion(9730259, "1-1", (*origen, None, None), (*destino, None, None)),
        _fila_fusion(9730270, "1-1", (*origen, None, None), (*destino, None, None)),
        _fila_fusion(9730279, "1-1", (*origen, None, None), (*destino, None, None)),
    ]
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_botellas": [(9450157, "Botella Duplicada")],
            "FROM app.cromo_fusiones": filas,
        }
    )

    resultado = await empalmes.empalmes_de_botella(sesion, 9450157)

    assert len(resultado.empalmes) == 1
    empalme = resultado.empalmes[0]
    assert empalme.es_splitter is False
    assert empalme.fusion_n_id == 9730259
    assert empalme.pelo_origen.n_id == 9443224
    assert empalme.pelo_destino.n_id == 9447426


@pytest.mark.asyncio
async def test_empalmes_de_botella_splitter_con_pata_colgada_nunca_es_splitter_1_1():
    """Caso real (botella_n_id=6632435, pelo 7056127, 2026-08-24): el pelo de entrada tiene 2 patas
    reales — una resuelta ("8-6") y una colgada ("S4-6", el componente Splitter no se modela como
    pelo en Cromo) — pero `splitter_ratio` sólo contaba patas con destino RESUELTO (`len(destinos)`),
    mostrando el imposible físico "Splitter 1-1". El ratio debe reflejar la cantidad de patas reales
    (2) aunque sólo una tenga destino resuelto."""
    origen = (7056127, 10, "Cable Entrada", 200, "AZ", "1", 0, "AZ")
    salida_resuelta = (6797262, 20, "Cable Salida", 300, "NR", "6", 0, "NR")
    filas = [
        _fila_fusion(9615388, "8-6", (*salida_resuelta, None, None), (*origen, None, None)),
        _fila_fusion(8958083, "S4-6", (*origen, None, None), None),
    ]
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_botellas": [(6632435, "Botella Colgada")],
            "FROM app.cromo_fusiones": filas,
        }
    )

    resultado = await empalmes.empalmes_de_botella(sesion, 6632435)

    assert len(resultado.empalmes) == 1
    grupo = resultado.empalmes[0]
    assert grupo.es_splitter is True
    assert grupo.splitter_ratio == 2
    assert {d.n_id for d in grupo.splitter_destinos} == {6797262}


@pytest.mark.asyncio
async def test_empalmes_de_botella_dos_origenes_candidatos_comparten_pata_resuelta():
    """Caso real (botella_n_id=6632435, pelos 7056127 y 6797262, 2026-09-02): un puente 1-1 real
    ("8-6") conecta 2 pelos que CADA UNO tiene además su propia pata colgada aislada ("S4-6" y
    "8-E1"). Cada pelo individualmente cuenta >=2 apariciones y se agrupa como origen de Splitter,
    pero sólo uno de los 2 puede quedarse con la única pata resuelta (9615388) — el otro queda con
    una sola pata (la colgada) y mostraba el imposible físico "Splitter 1-1". Un grupo con una sola
    pata real no es un Splitter."""
    origen_a = (7056127, 10, "Cable A", 200, "AZ", "1", 0, "AZ")
    origen_b = (6797262, 20, "Cable B", 300, "NR", "6", 0, "NR")
    filas = [
        _fila_fusion(8958083, "S4-6", (*origen_a, None, None), None),
        _fila_fusion(9155417, "8-E1", (*origen_b, None, None), None),
        _fila_fusion(9615388, "8-6", (*origen_b, None, None), (*origen_a, None, None)),
    ]
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_botellas": [(6632435, "Botella Colgada")],
            "FROM app.cromo_fusiones": filas,
        }
    )

    resultado = await empalmes.empalmes_de_botella(sesion, 6632435)

    ratios_invalidos = [e.splitter_ratio for e in resultado.empalmes if e.es_splitter and e.splitter_ratio == 1]
    assert ratios_invalidos == []


@pytest.mark.asyncio
async def test_empalmes_de_botella_splitter_pata_aislada_referencia_colgada():
    """Caso real observado (n_id 9997965, nombre_par "S7-1"): el otro extremo del par no resuelve a
    ningún pelo (el componente Splitter no se modela como pelo) y no hay otra fila para agrupar —
    se muestra igual como Splitter, sin proporción calculable."""
    fila = _fila_fusion(9997965, "S7-1", None, None)
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_botellas": [(1, "Botella X")],
            "FROM app.cromo_fusiones": [fila],
        }
    )

    resultado = await empalmes.empalmes_de_botella(sesion, 1)

    assert len(resultado.empalmes) == 1
    empalme = resultado.empalmes[0]
    assert empalme.es_splitter is True
    assert empalme.pelo_origen is None
    assert empalme.splitter_ratio is None
    assert resultado.cables == []


@pytest.mark.asyncio
async def test_empalmes_de_botella_referencia_colgada_con_cables():
    """La botella no tiene fila propia en `cromo_botellas` pero sí hay cables que la referencian
    como extremo — no debe tratarse como "no encontrada" (mismo criterio que verificador.py)."""
    sesion = _SesionFake(respuestas={"SELECT 1 FROM app.cromo_cables": [(1,)]})

    resultado = await empalmes.empalmes_de_botella(sesion, 42)

    assert resultado.botella_n_id == 42
    assert resultado.nombre is None
    assert resultado.empalmes == []
