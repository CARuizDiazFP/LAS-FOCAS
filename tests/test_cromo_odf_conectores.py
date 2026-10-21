# Nombre de archivo: test_cromo_odf_conectores.py
# Ubicación de archivo: tests/test_cromo_odf_conectores.py
# Descripción: Pruebas del servicio de conectores de ODF Cromo (core/services/cromo/odf_conectores.py), sin DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo import odf_conectores


class _ResultadoFilas:
    def __init__(self, filas: list[tuple]) -> None:
        self._filas = filas

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFake:
    """Reemplaza sólo `execute`: matchea por substring de la consulta compilada, mismo criterio
    que `test_cromo_verificador.py`."""

    def __init__(self, respuestas: Optional[dict[str, list[tuple]]] = None) -> None:
        self._respuestas = respuestas or {}

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFilas:
        texto = str(stmt)
        for clave, filas in self._respuestas.items():
            if clave in texto:
                return _ResultadoFilas(filas)
        return _ResultadoFilas([])


_FILA_CONECTOR = (
    8539345,  # n_id
    8539330,  # bandeja_n_id
    "O-1238223-1",  # bandeja_nombre
    "15",  # numero_conector
    6777271,  # pelo_n_id
    "1",  # pelo_numero
    "61943",  # servicio_resuelto
    "41140",  # servicio_id_historico
    "61943",  # s.servicio_id (servicio_id_externo)
    "Banco Comafi SA",  # nombre_cliente
    None,  # cliente
    "Activo",  # estado_servicio
)


@pytest.mark.asyncio
async def test_conectores_de_odf_no_encontrado():
    sesion = _SesionFake()
    with pytest.raises(odf_conectores.ObjetoNoEncontrado):
        await odf_conectores.conectores_de_odf(sesion, 999)


@pytest.mark.asyncio
async def test_conectores_de_odf_sin_conectores_pero_odf_existe():
    sesion = _SesionFake(respuestas={"FROM app.cromo_odfs": [("ODF Test",)]})

    resultado = await odf_conectores.conectores_de_odf(sesion, 6642085)

    assert resultado.odf_n_id == 6642085
    assert resultado.odf_nombre == "ODF Test"
    assert resultado.conectores == []


@pytest.mark.asyncio
async def test_conectores_de_odf_referencia_colgada_via_conectores():
    """La ODF no tiene fila propia (`cromo_odfs`) pero sí tiene conectores que la referencian —
    no debe tratarse como "no encontrado", sólo `odf_nombre` queda en `None`."""
    sesion = _SesionFake(respuestas={"FROM app.cromo_odf_conectores c": [_FILA_CONECTOR]})

    resultado = await odf_conectores.conectores_de_odf(sesion, 6642085)

    assert resultado.odf_nombre is None
    assert len(resultado.conectores) == 1


@pytest.mark.asyncio
async def test_conectores_de_odf_mapea_fila_completa():
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_odfs": [("ODF Rack Netizen 5 de Julio 478 C.F.",)],
            "FROM app.cromo_odf_conectores c": [_FILA_CONECTOR],
        }
    )

    resultado = await odf_conectores.conectores_de_odf(sesion, 6642085)

    assert resultado.odf_nombre == "ODF Rack Netizen 5 de Julio 478 C.F."
    assert len(resultado.conectores) == 1
    c = resultado.conectores[0]
    assert c.n_id == 8539345
    assert c.bandeja_nombre == "O-1238223-1"
    assert c.numero_conector == "15"
    assert c.pelo_n_id == 6777271
    assert c.pelo_numero == "1"
    assert c.servicio_resuelto == "61943"
    assert c.servicio_id_historico == "41140"
    assert c.servicio_id_externo == "61943"
    assert c.nombre_cliente == "Banco Comafi SA"
    assert c.estado_servicio == "Activo"


# ── `track odf`: patchera por nombre y conectores de una bandeja ─────────────


class _SesionQueRegistra(_SesionFake):
    def __init__(self, respuestas=None) -> None:
        super().__init__(respuestas)
        self.params: list[Optional[dict]] = []

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFilas:
        self.params.append(params)
        return await super().execute(stmt, params)


@pytest.mark.parametrize(
    "nombre, esperado",
    [
        ("O-1252871-1", ["O-1252871-1", "0-1252871-1"]),
        ("o-1252871-1", ["O-1252871-1", "0-1252871-1"]),
        # Hay 2.760 conectores reales con patchera "0-…": se prueban las dos formas.
        ("0-1252871-1", ["0-1252871-1", "O-1252871-1"]),
        ("  ODF Castillo, Ramon   2502 CF ", ["ODF CASTILLO, RAMON 2502 CF"]),
        ("ODF : ODF-CALLE 14 LIMA(PRACTICA) - LIMA CALLE 14", ["ODF : ODF-CALLE 14 LIMA(PRACTICA) - LIMA CALLE 14"]),
    ],
)
def test_variantes_nombre_patchera(nombre, esperado):
    assert odf_conectores.variantes_nombre_patchera(nombre) == esperado


def test_lateral_servicio_es_uno_solo_para_odf_y_bandeja():
    """El anti-ambigüedad no se duplica: `conectores_de_odf` y `conectores_de_bandeja` lo arman de
    la misma plantilla, así que no pueden divergir."""
    lateral = odf_conectores.lateral_servicio("c.servicio_resuelto")
    assert lateral in str(odf_conectores._SQL_CONECTORES_DE_ODF)
    assert lateral in str(odf_conectores._SQL_CONECTORES_DE_BANDEJA)
    assert odf_conectores.lateral_servicio("c.servicio_id_historico") in str(
        odf_conectores._SQL_CONECTORES_DE_BANDEJA
    )
    assert "{col}" not in str(odf_conectores._SQL_CONECTORES_DE_ODF)


@pytest.mark.asyncio
async def test_bandejas_por_nombre_busca_las_variantes_y_mapea():
    sesion = _SesionQueRegistra(
        {"FROM app.cromo_odf_conectores c": [(8604881, "O-1252871-1", 6644560, "ODF San Martin 137 P5 D")]}
    )
    bandejas = await odf_conectores.bandejas_por_nombre(sesion, "0-1252871-1")
    assert bandejas == [
        odf_conectores.BandejaCandidata(8604881, "O-1252871-1", 6644560, "ODF San Martin 137 P5 D")
    ]
    assert sesion.params[0] == {"nombres": ["0-1252871-1", "O-1252871-1"]}


@pytest.mark.asyncio
async def test_bandejas_por_nombre_vacio_no_consulta():
    sesion = _SesionQueRegistra()
    assert await odf_conectores.bandejas_por_nombre(sesion, "   ") == []
    assert sesion.params == []


_FILA_BANDEJA = (
    8604882,  # n_id
    "1",  # numero_conector
    7028862,  # pelo_n_id
    None,  # patch_conector_n_id
    None,  # patch_pelo_n_id
    "1",  # numero_pelo
    "F-PC-CC",  # cable_nombre
    "93150",  # servicio_resuelto
    4,  # sr.id
    "93150",  # sr.servicio_id
    "BANCO DE LA PROVINCIA DE BUENOS AIRES",  # sr.nombre_cliente
    None,  # sr.cliente
    "Activo",  # sr.estado_servicio
    "44649",  # servicio_id_historico
    "Baja",  # sh.estado_servicio
    "44649",  # p.servicio_numero (etiqueta cruda del pelo)
    "44649",  # sp.servicio_id
    "Baja",  # sp.estado_servicio
)


@pytest.mark.asyncio
async def test_conectores_de_bandeja_mapea_fila_completa():
    sesion = _SesionQueRegistra({"FROM app.cromo_odf_conectores c": [_FILA_BANDEJA]})
    conectores = await odf_conectores.conectores_de_bandeja(sesion, 8604881, ["1", "2"])
    assert sesion.params[-1] == {"bandeja_n_id": 8604881, "numeros": ["1", "2"]}
    c = conectores[0]
    assert (c.n_id, c.numero_conector, c.pelo_n_id, c.numero_pelo, c.cable_nombre) == (
        8604882, "1", 7028862, "1", "F-PC-CC"
    )
    assert (c.servicio_pk, c.servicio_numero, c.estado_servicio) == (4, "93150", "Activo")
    assert c.nombre_cliente == "BANCO DE LA PROVINCIA DE BUENOS AIRES"
    assert (c.historico_numero, c.historico_estado) == ("44649", "Baja")
    assert (c.etiqueta_pelo, c.etiqueta_numero, c.etiqueta_estado) == ("44649", "44649", "Baja")
    assert c.pelo_efectivo == 7028862


def test_pelo_efectivo_sigue_un_salto_de_patch():
    base = dict(zip(
        [f.name for f in odf_conectores.ConectorDePatchera.__dataclass_fields__.values()],
        [None] * len(odf_conectores.ConectorDePatchera.__dataclass_fields__),
    ))
    sin_nada = odf_conectores.ConectorDePatchera(**{**base, "n_id": 1, "numero_conector": "5"})
    con_patch = odf_conectores.ConectorDePatchera(
        **{**base, "n_id": 2, "numero_conector": "9", "patch_conector_n_id": 3, "patch_pelo_n_id": 77}
    )
    assert sin_nada.pelo_efectivo is None
    assert con_patch.pelo_efectivo == 77


@pytest.mark.asyncio
async def test_conectores_de_bandeja_con_odf_filtra_por_la_odf_indexada():
    class _Sesion(_SesionQueRegistra):
        def __init__(self) -> None:
            super().__init__()
            self.sentencias: list[str] = []

        async def execute(self, stmt, params=None):
            self.sql = str(stmt)
            self.sentencias.append(self.sql)
            return await super().execute(stmt, params)

    sesion = _Sesion()
    await odf_conectores.conectores_de_bandeja(sesion, 8604881, ["1"], odf_n_id=6644560)
    # Sin JIT: compilarlo costaba 1,5 s de 1,6 s en dev para 3 filas.
    assert sesion.sentencias[0] == "SET LOCAL jit = off"
    assert sesion.params[-1] == {"bandeja_n_id": 8604881, "numeros": ["1"], "odf_n_id": 6644560}
    assert "c.odf_n_id = :odf_n_id" in sesion.sql
    await odf_conectores.conectores_de_bandeja(sesion, 8604881, ["1"])
    assert "c.odf_n_id = :odf_n_id" not in sesion.sql
