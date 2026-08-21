# Nombre de archivo: test_cromo_separacion_service.py
# Ubicación de archivo: tests/test_cromo_separacion_service.py
# Descripción: Pruebas de separación manual de una Botella Cromo de su Cámara padre (agrupamiento erróneo por nombre)

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.services.cromo import separacion_service as servicio
from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos


def test_separar_botella_de_padre_falla_si_no_existe():
    session = MagicMock()
    session.get.return_value = None

    with pytest.raises(servicio.BotellaNoEncontradaError, match="9057909"):
        servicio.separar_botella_de_padre(
            session, botella_n_id=9057909, nombre="Cra Nueva CF", motivo="agrupada mal", usuario="admin"
        )


def test_separar_botella_de_padre_falla_si_nombre_vacio():
    botella = CromoBotella(n_id=1, nombre="Original")
    session = MagicMock()
    session.get.return_value = botella

    with pytest.raises(servicio.SeparacionBotellaError, match="vacío"):
        servicio.separar_botella_de_padre(session, botella_n_id=1, nombre="   ", motivo="motivo", usuario="admin")


def test_separar_botella_de_padre_falla_si_colisiona_con_camara_raiz_existente():
    botella = CromoBotella(n_id=1, nombre="Cra San Martin 201")
    camara_existente = Camara(id=99, nombre="cra. San Martín 201", camara_padre_id=None)
    session = MagicMock()
    session.get.return_value = botella
    session.query.return_value.filter.return_value.all.return_value = [camara_existente]

    with pytest.raises(servicio.SeparacionBotellaError, match="ya lo usa"):
        servicio.separar_botella_de_padre(
            session, botella_n_id=1, nombre="Cra San Martin 201", motivo="motivo", usuario="admin"
        )


def test_separar_botella_de_padre_crea_camara_nueva_y_actualiza_botella():
    botella = CromoBotella(n_id=1, nombre="Nombre viejo", camara_id=50, nombre_editado_manual=False)
    session = MagicMock()
    session.get.return_value = botella
    session.query.return_value.filter.return_value.all.return_value = []  # sin colisión

    camara_creada: dict = {}

    def fake_add(obj):
        if isinstance(obj, Camara):
            obj.id = 777
            camara_creada["camara"] = obj

    session.add.side_effect = fake_add

    resultado = servicio.separar_botella_de_padre(
        session,
        botella_n_id=1,
        nombre="Nombre corregido y distinto",
        motivo="agrupada con otra por error",
        usuario="admin_test",
    )

    assert resultado.botella_n_id == 1
    assert resultado.camara_anterior_id == 50
    assert resultado.camara_nueva_id == 777
    assert resultado.camara_nueva_nombre == "Nombre corregido y distinto"
    assert botella.nombre == "Nombre corregido y distinto"
    assert botella.nombre_editado_manual is True
    assert botella.camara_id == 777
    assert botella.separada_manualmente is True
    assert botella.separada_motivo == "agrupada con otra por error"
    assert botella.separada_por == "admin_test"
    assert botella.separada_at is not None

    camara = camara_creada["camara"]
    assert camara.origen_datos == CamaraOrigenDatos.MANUAL
    assert camara.estado == CamaraEstado.LIBRE
    session.flush.assert_called_once()


def test_separar_botella_de_padre_no_toca_camara_padre_anterior():
    botella = CromoBotella(n_id=1, nombre="Nombre viejo", camara_id=50)
    session = MagicMock()
    session.get.return_value = botella
    session.query.return_value.filter.return_value.all.return_value = []

    servicio.separar_botella_de_padre(
        session, botella_n_id=1, nombre="Nombre nuevo distinto", motivo="motivo", usuario="admin"
    )

    session.get.assert_called_once_with(CromoBotella, 1)
