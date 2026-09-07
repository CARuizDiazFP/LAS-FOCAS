# Nombre de archivo: test_camara_busqueda_service.py
# Ubicación de archivo: tests/test_camara_busqueda_service.py
# Descripción: Pruebas de la búsqueda liviana de Cámaras raíz (picker de unificación/asociación de huérfanas)

from __future__ import annotations

from unittest.mock import MagicMock

from core.services.camara_busqueda_service import buscar_camaras_ligero
from db.models.cromo import CromoBotella
from db.models.infra import Cable, Camara, CamaraEstado


def _sesion_con_resultado(camaras: list[Camara]) -> MagicMock:
    """Configura el resultado tanto si `buscar_camaras_ligero` encadena un solo `.filter()` (sin
    `q`/`excluir_id`) como si encadena varios (con `q` y/o `excluir_id`) — cada `.filter()`
    adicional devuelve el mismo mock base, así que el `.filter` anidado también queda cubierto."""
    session = MagicMock()
    filtro_base = session.query.return_value.filter.return_value
    filtro_base.filter.return_value = filtro_base
    filtro_base.order_by.return_value.limit.return_value.all.return_value = camaras
    return session


def test_buscar_camaras_ligero_devuelve_campos_minimos() -> None:
    camara = Camara(id=1, nombre="Cra Plaza de los Ingleses CF", direccion="Plaza de los Ingleses", estado=CamaraEstado.LIBRE)
    camara.botellas = [Camara(id=2, nombre="Cra Plaza de los Ingleses Bot 2 CF")]
    camara.cromo_botellas = []
    camara.cables_origen = [Cable(id=3, nombre="Cable A")]
    session = _sesion_con_resultado([camara])

    resultado = buscar_camaras_ligero(session, "Plaza")

    assert len(resultado) == 1
    item = resultado[0]
    assert item.id == 1
    assert item.nombre == "Cra Plaza de los Ingleses CF"
    assert item.estado == "LIBRE"
    assert item.botellas_count == 1
    assert item.cables_count == 1


def test_buscar_camaras_ligero_q_vacio_no_filtra_por_texto() -> None:
    session = _sesion_con_resultado([])

    buscar_camaras_ligero(session, "   ")

    # Sólo el filtro estructural (camara_padre_id IS NULL) — nunca un segundo .filter() por texto.
    assert session.query.return_value.filter.call_count == 1


def test_buscar_camaras_ligero_q_no_vacio_agrega_filtro_ilike() -> None:
    session = _sesion_con_resultado([])

    buscar_camaras_ligero(session, "Ingleses")

    assert session.query.return_value.filter.call_count == 1
    assert session.query.return_value.filter.return_value.filter.call_count == 1


def test_buscar_camaras_ligero_excluir_id_agrega_filtro_adicional() -> None:
    session = _sesion_con_resultado([])

    buscar_camaras_ligero(session, None, excluir_id=42)

    assert session.query.return_value.filter.return_value.filter.call_count == 1


def test_buscar_camaras_ligero_limit_clamp() -> None:
    session = _sesion_con_resultado([])

    buscar_camaras_ligero(session, None, limit=500)

    session.query.return_value.filter.return_value.order_by.return_value.limit.assert_called_once_with(50)


def test_buscar_camaras_ligero_estado_default_libre_si_falta() -> None:
    camara = Camara(id=1, nombre="Cra Sin Estado CF", estado=None)
    camara.botellas = []
    session = _sesion_con_resultado([camara])

    resultado = buscar_camaras_ligero(session, None)

    assert resultado[0].estado == "LIBRE"


def test_buscar_camaras_ligero_cuenta_botellas_cromo_de_camara_inferida() -> None:
    """~9.770/10.212 Cámaras raíz son INFERIDO_CROMO y nunca tienen Botellas legado propias —
    botellas_count debía incluir también cromo_botellas."""
    camara = Camara(id=1, nombre="Cra Bernardo de Irigoyen 194 CF", estado=CamaraEstado.LIBRE)
    camara.botellas = []
    camara.cromo_botellas = [CromoBotella(n_id=100), CromoBotella(n_id=101)]
    session = _sesion_con_resultado([camara])

    resultado = buscar_camaras_ligero(session, None)

    assert resultado[0].botellas_count == 2


def test_buscar_camaras_ligero_solo_raiz_false_no_aplica_filtro_estructural() -> None:
    """`solo_raiz=False` no debe anidar el filtro `camara_padre_id.is_(None)` antes del ILIKE —
    a diferencia del default (`solo_raiz=True`), donde ese filtro estructural sí se aplica primero
    y el ILIKE queda anidado como segundo `.filter()`. Además, el resultado incluye tanto la raíz
    como la botella (picker de asociación manual, Tarea 5)."""
    raiz = Camara(id=1, nombre="Cra Plaza de los Ingleses CF", estado=CamaraEstado.LIBRE)
    raiz.botellas = []
    raiz.cromo_botellas = []
    botella = Camara(
        id=2,
        nombre="Cra Plaza de los Ingleses Bot 2 CF",
        estado=CamaraEstado.LIBRE,
        camara_padre_id=1,
    )
    botella.camara_padre = raiz
    botella.botellas = []
    botella.cromo_botellas = []
    session = _sesion_con_resultado([raiz, botella])

    resultado = buscar_camaras_ligero(session, "Plaza", solo_raiz=False)

    # Un solo `.filter()` de primer nivel (el ILIKE) y ninguno anidado — el filtro estructural que
    # sí aplica el default (`solo_raiz=True`) queda deshabilitado.
    assert session.query.return_value.filter.call_count == 1
    assert session.query.return_value.filter.return_value.filter.call_count == 0
    assert len(resultado) == 2
    assert [item.es_botella for item in resultado] == [False, True]


def test_buscar_camaras_ligero_solo_raiz_true_default_preserva_comportamiento() -> None:
    """`solo_raiz=True` (default, sin pasar el argumento) sigue anidando el filtro estructural
    antes del ILIKE — comportamiento idéntico al actual, sin regresión al agregar el parámetro."""
    session = _sesion_con_resultado([])

    buscar_camaras_ligero(session, "Ingleses")

    assert session.query.return_value.filter.call_count == 1
    assert session.query.return_value.filter.return_value.filter.call_count == 1


def test_buscar_camaras_ligero_serializa_botella_con_camara_padre() -> None:
    padre = Camara(id=10, nombre="Cra Plaza de los Ingleses CF")
    botella = Camara(
        id=2,
        nombre="Cra Plaza de los Ingleses Bot 2 CF",
        estado=CamaraEstado.LIBRE,
        camara_padre_id=10,
    )
    botella.camara_padre = padre
    botella.botellas = []
    botella.cromo_botellas = []
    session = _sesion_con_resultado([botella])

    resultado = buscar_camaras_ligero(session, "Plaza", solo_raiz=False)

    item = resultado[0]
    assert item.es_botella is True
    assert item.camara_padre_id == 10
    assert item.camara_padre_nombre == "Cra Plaza de los Ingleses CF"


def test_buscar_camaras_ligero_serializa_raiz_sin_padre() -> None:
    camara = Camara(id=1, nombre="Cra Plaza de los Ingleses CF", estado=CamaraEstado.LIBRE)
    camara.botellas = []
    camara.cromo_botellas = []
    session = _sesion_con_resultado([camara])

    resultado = buscar_camaras_ligero(session, "Plaza")

    item = resultado[0]
    assert item.es_botella is False
    assert item.camara_padre_id is None
    assert item.camara_padre_nombre is None
