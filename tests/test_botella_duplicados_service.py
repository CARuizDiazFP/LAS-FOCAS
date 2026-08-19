# Nombre de archivo: test_botella_duplicados_service.py
# Ubicación de archivo: tests/test_botella_duplicados_service.py
# Descripción: Pruebas de la detección de Botellas (Cromo + legado) candidatas a duplicado dentro de la misma Cámara padre

from __future__ import annotations

from unittest.mock import MagicMock

from core.services.botella_duplicados_service import (
    BotellaDuplicadaItem,
    GrupoBotellasDuplicadas,
    detectar_grupos_duplicados_botellas,
    sugerir_apropiacion,
)
from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado


def _sesion_con_filas(legado_rows: list[Camara], cromo_rows: list[CromoBotella]) -> MagicMock:
    session = MagicMock()
    model_mocks: dict[object, MagicMock] = {}

    def mock_para(modelo: object) -> MagicMock:
        if modelo not in model_mocks:
            model_mocks[modelo] = MagicMock()
        return model_mocks[modelo]

    mock_para(Camara).filter.return_value.options.return_value.all.return_value = legado_rows
    mock_para(CromoBotella).filter.return_value.options.return_value.all.return_value = cromo_rows

    session.query.side_effect = lambda modelo, *a: mock_para(modelo)
    return session


def _legado(id_: int, nombre: str, padre: Camara, estado=CamaraEstado.LIBRE) -> Camara:
    botella = Camara(id=id_, nombre=nombre, estado=estado, camara_padre_id=padre.id)
    botella.camara_padre = padre
    return botella


def _cromo(n_id: int, nombre: str, padre: Camara, estado=CamaraEstado.LIBRE) -> CromoBotella:
    cromo_botella = CromoBotella(n_id=n_id, nombre=nombre, estado=estado, camara_id=padre.id)
    cromo_botella.camara = padre
    return cromo_botella


def test_detectar_agrupa_duplicado_mixto_dentro_del_mismo_padre() -> None:
    padre = Camara(id=100, nombre="Cra Rivadavia 100 CF")
    legado = _legado(1, "Camara Rivadavia 100 Bot 2", padre)
    cromo = _cromo(200, "Cra Rivadavia 100 Bot 2", padre)
    session = _sesion_con_filas([legado], [cromo])

    grupos = detectar_grupos_duplicados_botellas(session)

    assert len(grupos) == 1
    grupo = grupos[0]
    assert grupo.camara_padre_id == 100
    assert grupo.resoluble is True
    origenes = {m.origen for m in grupo.miembros}
    assert origenes == {"legado", "cromo"}


def test_detectar_grupo_todo_legado_no_es_resoluble_pero_se_reporta() -> None:
    padre = Camara(id=100, nombre="Cra Rivadavia 100 CF")
    a = _legado(1, "Cra Rivadavia 100 Bot 2", padre)
    b = _legado(2, "Cra Rivadavia 100 Bot 2", padre)
    session = _sesion_con_filas([a, b], [])

    grupos = detectar_grupos_duplicados_botellas(session)

    assert len(grupos) == 1
    assert grupos[0].resoluble is False


def test_detectar_grupo_todo_cromo_no_es_resoluble_pero_se_reporta() -> None:
    padre = Camara(id=100, nombre="Cra Rivadavia 100 CF")
    a = _cromo(200, "Cra Rivadavia 100 Bot 2", padre)
    b = _cromo(201, "Camara Rivadavia 100 Bot 2", padre)
    session = _sesion_con_filas([], [a, b])

    grupos = detectar_grupos_duplicados_botellas(session)

    assert len(grupos) == 1
    assert grupos[0].resoluble is False


def test_detectar_grupo_mixto_con_dos_legado_no_es_resoluble() -> None:
    padre = Camara(id=100, nombre="Cra Rivadavia 100 CF")
    a = _legado(1, "Cra Rivadavia 100 Bot 2", padre)
    b = _legado(2, "Camara Rivadavia 100 Bot 2", padre)
    c = _cromo(200, "Cra Rivadavia 100 Bot 2", padre)
    session = _sesion_con_filas([a, b], [c])

    grupos = detectar_grupos_duplicados_botellas(session)

    assert len(grupos) == 1
    assert grupos[0].resoluble is False


def test_detectar_no_agrupa_entre_padres_distintos() -> None:
    padre_a = Camara(id=100, nombre="Cra Rivadavia 100 CF")
    padre_b = Camara(id=101, nombre="Cra San Martin 200 CF")
    legado_a = _legado(1, "Bot 2", padre_a)
    legado_b = _legado(2, "Bot 2", padre_b)
    session = _sesion_con_filas([legado_a, legado_b], [])

    grupos = detectar_grupos_duplicados_botellas(session)

    assert grupos == []


def test_detectar_estados_en_conflicto_y_estado_mas_restrictivo() -> None:
    padre = Camara(id=100, nombre="Cra Rivadavia 100 CF")
    legado = _legado(1, "Camara Rivadavia 100 Bot 2", padre, estado=CamaraEstado.LIBRE)
    cromo = _cromo(200, "Cra Rivadavia 100 Bot 2", padre, estado=CamaraEstado.BANEADA)
    session = _sesion_con_filas([legado], [cromo])

    grupos = detectar_grupos_duplicados_botellas(session)

    assert grupos[0].estados_en_conflicto is True
    assert grupos[0].estado_mas_restrictivo == "BANEADA"


def test_detectar_sin_conflicto_de_estado() -> None:
    padre = Camara(id=100, nombre="Cra Rivadavia 100 CF")
    legado = _legado(1, "Camara Rivadavia 100 Bot 2", padre, estado=CamaraEstado.LIBRE)
    cromo = _cromo(200, "Cra Rivadavia 100 Bot 2", padre, estado=CamaraEstado.LIBRE)
    session = _sesion_con_filas([legado], [cromo])

    grupos = detectar_grupos_duplicados_botellas(session)

    assert grupos[0].estados_en_conflicto is False


def _grupo(miembros: list[BotellaDuplicadaItem], resoluble: bool) -> GrupoBotellasDuplicadas:
    return GrupoBotellasDuplicadas(
        camara_padre_id=100,
        camara_padre_nombre="Cra Rivadavia 100 CF",
        clave_normalizada="clave",
        criterio="normalizacion_extendida",
        miembros=miembros,
        estados_en_conflicto=False,
        estado_mas_restrictivo="LIBRE",
        resoluble=resoluble,
    )


def test_sugerir_apropiacion_devuelve_par_si_es_resoluble() -> None:
    grupo = _grupo(
        [
            BotellaDuplicadaItem(origen="legado", id=1, nombre="Bot 2", estado="LIBRE"),
            BotellaDuplicadaItem(origen="cromo", id=200, nombre="Botella 2", estado="LIBRE"),
        ],
        resoluble=True,
    )
    assert sugerir_apropiacion(grupo) == (1, 200)


def test_sugerir_apropiacion_devuelve_none_si_no_es_resoluble() -> None:
    grupo = _grupo(
        [
            BotellaDuplicadaItem(origen="legado", id=1, nombre="Bot 2", estado="LIBRE"),
            BotellaDuplicadaItem(origen="legado", id=2, nombre="Bot 2", estado="LIBRE"),
        ],
        resoluble=False,
    )
    assert sugerir_apropiacion(grupo) is None
