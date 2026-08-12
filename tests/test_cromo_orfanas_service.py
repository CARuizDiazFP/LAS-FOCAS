# Nombre de archivo: test_cromo_orfanas_service.py
# Ubicación de archivo: tests/test_cromo_orfanas_service.py
# Descripción: Pruebas del listado y asociación manual de Botellas Cromo huérfanas (Caso 1)

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from core.services.cromo import orfanas_service as servicio
from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos


class _ResultadoFake:
    def __init__(self, escalar: Any = None, filas: Optional[list[tuple]] = None) -> None:
        self._escalar = escalar
        self._filas = filas or []

    def scalar_one(self):
        return self._escalar

    def all(self):
        return self._filas


class _SesionFake:
    def __init__(self, total: int = 0, filas: Optional[list[tuple]] = None) -> None:
        self._total = total
        self._filas = filas or []
        self.llamadas: list[str] = []

    async def execute(self, stmt: Any) -> _ResultadoFake:
        texto = str(stmt)
        self.llamadas.append(texto)
        if "count" in texto.lower():
            return _ResultadoFake(escalar=self._total)
        return _ResultadoFake(filas=self._filas)


_FILA = (6638808, "Cra Plaza de los Ingleses CF", "Plaza de los Ingleses", "CABA")


@pytest.mark.asyncio
async def test_buscar_huerfanas_devuelve_pagina():
    sesion = _SesionFake(total=1, filas=[_FILA])

    resultado = await servicio.buscar_huerfanas(sesion)

    assert resultado.total == 1
    assert len(resultado.botellas) == 1
    assert resultado.botellas[0].n_id == 6638808
    assert resultado.botellas[0].nombre == "Cra Plaza de los Ingleses CF"


@pytest.mark.asyncio
async def test_buscar_huerfanas_sin_resultados():
    sesion = _SesionFake(total=0, filas=[])

    resultado = await servicio.buscar_huerfanas(sesion, q="no existe")

    assert resultado.total == 0
    assert resultado.botellas == []


def test_asociar_huerfanas_falla_sin_n_ids():
    session = MagicMock()
    with pytest.raises(servicio.AsociarHuerfanasError, match="No se especificaron"):
        servicio.asociar_huerfanas(session, n_ids=[], camara_id=1, nombre_nueva_camara=None, usuario="test")


def test_asociar_huerfanas_falla_si_no_especifica_exactamente_uno():
    session = MagicMock()
    with pytest.raises(servicio.AsociarHuerfanasError, match="exactamente uno"):
        servicio.asociar_huerfanas(session, n_ids=[1], camara_id=None, nombre_nueva_camara=None, usuario="test")
    with pytest.raises(servicio.AsociarHuerfanasError, match="exactamente uno"):
        servicio.asociar_huerfanas(session, n_ids=[1], camara_id=5, nombre_nueva_camara="Cra X", usuario="test")


def test_asociar_huerfanas_falla_si_camara_existente_no_existe():
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    with pytest.raises(servicio.AsociarHuerfanasError, match="no existe"):
        servicio.asociar_huerfanas(session, n_ids=[1], camara_id=99, nombre_nueva_camara=None, usuario="test")


def test_asociar_huerfanas_falla_si_camara_existente_es_una_botella():
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = Camara(id=5, nombre="Bot 2", camara_padre_id=10)
    with pytest.raises(servicio.AsociarHuerfanasError, match="Cámara padre"):
        servicio.asociar_huerfanas(session, n_ids=[1], camara_id=5, nombre_nueva_camara=None, usuario="test")


def test_asociar_huerfanas_falla_si_alguna_botella_no_existe():
    camara = Camara(id=5, nombre="Cra Existente CF", estado=CamaraEstado.LIBRE)
    camara.botellas = []
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = camara
    session.query.return_value.filter.return_value.all.return_value = [CromoBotella(n_id=1, nombre="Solo esta")]

    with pytest.raises(servicio.AsociarHuerfanasError, match="no existe"):
        servicio.asociar_huerfanas(session, n_ids=[1, 2], camara_id=5, nombre_nueva_camara=None, usuario="test")


def test_asociar_huerfanas_a_camara_existente_hereda_estado_real():
    camara = Camara(id=5, nombre="Cra Existente CF", estado=CamaraEstado.OCUPADA)
    camara.botellas = []
    botella = CromoBotella(n_id=1, nombre="Cra Existente Bot 2 CF", estado=CamaraEstado.NO_OPERATIVA)

    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = camara
    session.query.return_value.filter.return_value.all.return_value = [botella]

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "core.services.cromo.orfanas_service.miembros_del_grupo", return_value=[camara]
    ):
        resultado = servicio.asociar_huerfanas(
            session, n_ids=[1], camara_id=5, nombre_nueva_camara=None, usuario="admin"
        )

    assert resultado.camara_id == 5
    assert resultado.camara_creada is False
    assert resultado.botellas_vinculadas == 1
    assert resultado.estado_asignado == "OCUPADA"
    assert botella.camara_id == 5
    assert botella.estado == CamaraEstado.OCUPADA


def test_asociar_huerfanas_crea_camara_nueva_no_operativa():
    botella = CromoBotella(n_id=1, nombre="Botella 2 Combate de los pozos 1881 CF")

    session = MagicMock()

    def fake_query(model):
        query = MagicMock()
        if model is CromoBotella:
            query.filter.return_value.all.return_value = [botella]
        return query

    session.query.side_effect = fake_query

    from unittest.mock import patch

    nueva_camara_creada: dict = {}

    def fake_add(obj):
        if isinstance(obj, Camara):
            obj.id = 777
            nueva_camara_creada["camara"] = obj

    session.add.side_effect = fake_add

    with patch(
        "core.services.cromo.orfanas_service.miembros_del_grupo",
        side_effect=lambda camara: [camara],
    ):
        resultado = servicio.asociar_huerfanas(
            session,
            n_ids=[1],
            camara_id=None,
            nombre_nueva_camara="Combate de los pozos 1881 CF",
            usuario="admin",
        )

    camara_creada = nueva_camara_creada["camara"]
    assert camara_creada.estado == CamaraEstado.NO_OPERATIVA
    assert camara_creada.origen_datos == CamaraOrigenDatos.INFERIDO_CROMO
    assert resultado.camara_creada is True
    assert resultado.botellas_vinculadas == 1
    assert resultado.estado_asignado == "NO_OPERATIVA"
    assert botella.camara_id == 777
