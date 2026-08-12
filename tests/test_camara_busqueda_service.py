# Nombre de archivo: test_camara_busqueda_service.py
# Ubicación de archivo: tests/test_camara_busqueda_service.py
# Descripción: Pruebas de la búsqueda liviana de Cámaras raíz (picker de unificación/asociación de huérfanas)

from __future__ import annotations

from unittest.mock import MagicMock

from core.services.camara_busqueda_service import buscar_camaras_ligero
from db.models.infra import Camara, CamaraEstado


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
    session = _sesion_con_resultado([camara])

    resultado = buscar_camaras_ligero(session, "Plaza")

    assert len(resultado) == 1
    item = resultado[0]
    assert item.id == 1
    assert item.nombre == "Cra Plaza de los Ingleses CF"
    assert item.estado == "LIBRE"
    assert item.botellas_count == 1


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
