# Nombre de archivo: test_cromo_odf_detalle.py
# Ubicación de archivo: tests/test_cromo_odf_detalle.py
# Descripción: Pruebas del detalle de un ODF Cromo (metadata + cables asociados + vecinos de dirección), sin DB real

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.services.cromo import odf_detalle


class _ResultadoFilas:
    def __init__(self, filas: list[tuple]) -> None:
        self._filas = filas

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFake:
    """Matchea por substring de la consulta compilada, igual que test_cromo_detalle.py."""

    def __init__(self, respuestas: Optional[dict[str, list[tuple]]] = None) -> None:
        self._respuestas = respuestas or {}
        self.llamadas: list[tuple[str, Optional[dict]]] = []

    async def execute(self, stmt: Any, params: Optional[dict] = None) -> _ResultadoFilas:
        texto = str(stmt)
        self.llamadas.append((texto, params))
        for clave, filas in self._respuestas.items():
            if clave in texto:
                return _ResultadoFilas(filas)
        return _ResultadoFilas([])


_FILA_ODF = (
    901,  # n_id
    "ODF Calle 9 Nro 593 PILAR",  # nombre
    "ODF",  # tipo_elemento
    "Metrotel",  # propietario
    None,  # codigo_modelo
    None,  # id_legacy
    None,  # notas
    "Calle 9",  # calle
    "593",  # altura
    "PILAR",  # localidad
    "Buenos Aires",  # provincia
    None,  # ubicacion_fisica
    None,  # tendido
    None,  # latitud
    None,  # longitud
    True,  # vigente
    [111, 222],  # cables_asociados
)


@pytest.mark.asyncio
async def test_obtener_detalle_odf_no_encontrado():
    sesion = _SesionFake()
    with pytest.raises(odf_detalle.ObjetoNoEncontrado):
        await odf_detalle.obtener_detalle_odf(sesion, 999)


@pytest.mark.asyncio
async def test_obtener_detalle_odf_metadata_basica():
    sesion = _SesionFake(respuestas={"FROM app.cromo_odfs o": [_FILA_ODF]})

    detalle = await odf_detalle.obtener_detalle_odf(sesion, 901)

    assert detalle.n_id == 901
    assert detalle.nombre == "ODF Calle 9 Nro 593 PILAR"
    assert detalle.tipo_elemento == "ODF"
    assert detalle.calle == "Calle 9"
    assert detalle.altura == "593"
    assert detalle.localidad == "PILAR"
    assert detalle.vigente is True


@pytest.mark.asyncio
async def test_obtener_detalle_odf_resuelve_cables_asociados_por_nombre():
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_odfs o": [_FILA_ODF],
            "FROM app.cromo_cables": [(111, "Cable A"), (222, "Cable B")],
        }
    )

    detalle = await odf_detalle.obtener_detalle_odf(sesion, 901)

    assert detalle.cables_asociados == [
        {"n_id": 111, "nombre": "Cable A"},
        {"n_id": 222, "nombre": "Cable B"},
    ]


@pytest.mark.asyncio
async def test_obtener_detalle_odf_cable_asociado_sin_fila_propia_no_desaparece():
    """Un cable referenciado en `cables_asociados` que todavía no bajó (referencia colgada) aparece
    igual en la respuesta con `nombre=None`, en vez de perderse en silencio."""
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_odfs o": [_FILA_ODF],
            "FROM app.cromo_cables": [(111, "Cable A")],  # 222 no resuelve
        }
    )

    detalle = await odf_detalle.obtener_detalle_odf(sesion, 901)

    assert detalle.cables_asociados == [
        {"n_id": 111, "nombre": "Cable A"},
        {"n_id": 222, "nombre": None},
    ]


@pytest.mark.asyncio
async def test_obtener_detalle_odf_sin_cables_asociados_devuelve_lista_vacia():
    """`cables_asociados` NULL (ODF sin `tp` en el payload de Cromo) no debe explotar con
    `len(None)`/iterar sobre `None` — la query de resolución de nombres igual se ejecuta (siguen
    siendo "3 queries fijas"), sólo que con una lista de ids vacía."""
    fila_sin_cables = _FILA_ODF[:-1] + (None,)
    sesion = _SesionFake(respuestas={"FROM app.cromo_odfs o": [fila_sin_cables]})

    detalle = await odf_detalle.obtener_detalle_odf(sesion, 901)

    assert detalle.cables_asociados == []


@pytest.mark.asyncio
async def test_obtener_detalle_odf_vecinos_misma_direccion_excluye_propio():
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_odfs o": [_FILA_ODF],
            "FROM app.cromo_odfs\n    WHERE": [(902, "ODF Calle 9 Nro 595 PILAR")],
        }
    )

    detalle = await odf_detalle.obtener_detalle_odf(sesion, 901)

    assert detalle.odfs_en_la_misma_direccion == [{"n_id": 902, "nombre": "ODF Calle 9 Nro 595 PILAR"}]
    # El propio n_id se pasa como parámetro de exclusión, nunca se auto-incluye.
    llamada_vecinos = next(p for texto, p in sesion.llamadas if "FROM app.cromo_odfs\n    WHERE" in texto)
    assert llamada_vecinos["n_id"] == 901


@pytest.mark.asyncio
async def test_obtener_detalle_odf_sin_calle_no_agrupa_vecinos():
    """Guardrail del brief: si el ODF no tiene `calle` cargada, `odfs_en_la_misma_direccion` debe
    quedar vacío — no agrupar falsamente todos los ODFs sin dirección conocida entre sí."""
    fila_sin_calle = list(_FILA_ODF)
    fila_sin_calle[7] = None  # calle
    sesion = _SesionFake(
        respuestas={
            "FROM app.cromo_odfs o": [tuple(fila_sin_calle)],
            # Si la query se ejecutara sin guardia, esto se devolvería igual — el guard vive en el
            # WHERE de _SQL_VECINOS_DIRECCION, así que ni siquiera debería matchear con calle=None.
            "FROM app.cromo_odfs\n    WHERE": [(902, "Otro ODF")],
        }
    )

    detalle = await odf_detalle.obtener_detalle_odf(sesion, 901)

    llamada_vecinos = next(p for texto, p in sesion.llamadas if "FROM app.cromo_odfs\n    WHERE" in texto)
    assert llamada_vecinos["calle"] is None
    # La guardia real vive en SQL (`CAST(:calle AS text) IS NOT NULL`), no en Python — la sesión fake
    # de este archivo no ejecuta SQL de verdad, así que no puede confirmar que la guardia funciona
    # (de hecho, la respuesta fake de "Otro ODF" arriba se devolvería igual esté o no la guardia
    # presente). La cobertura contra un driver real vive en
    # tests/test_cromo_odf_inventario_real_db.py::test_obtener_detalle_odf_calle_null_no_agrupa_falsamente_contra_driver_real,
    # que inserta dos ODFs con `calle IS NULL` de verdad y assertea sobre
    # `odfs_en_la_misma_direccion` contra Postgres real. Acá sólo se confirma que el parámetro
    # `calle=None` efectivamente viaja tal cual, sin normalizarse a otra cosa.
    assert detalle.calle is None
