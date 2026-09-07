# Nombre de archivo: test_camara_duplicados_service.py
# Ubicación de archivo: tests/test_camara_duplicados_service.py
# Descripción: Pruebas de la detección de Cámaras raíz candidatas a duplicado por nombre normalizado extendido

from __future__ import annotations

from unittest.mock import MagicMock

from core.services.camara_duplicados_service import (
    CamaraDuplicadaItem,
    GrupoDuplicados,
    detectar_grupos_duplicados,
    sugerir_principal,
)
from db.models.cromo import CromoBotella
from db.models.infra import Camara, CamaraEstado


def _sesion_con_camaras(camaras: list[Camara]) -> MagicMock:
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = camaras
    return session


def test_detectar_grupos_duplicados_agrupa_caso_real() -> None:
    a = Camara(id=1, nombre="Cámara 14 de Julio 240", estado=CamaraEstado.LIBRE)
    b = Camara(id=2, nombre="Cra 14 de Julio 240 CF", estado=CamaraEstado.LIBRE)
    session = _sesion_con_camaras([a, b])

    grupos = detectar_grupos_duplicados(session)

    assert len(grupos) == 1
    ids = {m.id for m in grupos[0].miembros}
    assert ids == {1, 2}
    assert grupos[0].criterio == "normalizacion_extendida"


def test_detectar_grupos_duplicados_excluye_sufijo_bot_n() -> None:
    """Una fila con sufijo Bot-N ya está resuelta por la jerarquía Cámara/Botella — no debe
    aparecer nunca como candidata a duplicado, aunque comparta base normalizada con otras dos."""
    principal_a = Camara(id=1, nombre="Cra Rivadavia 100 CF", estado=CamaraEstado.LIBRE)
    principal_b = Camara(id=2, nombre="Camara Rivadavia 100", estado=CamaraEstado.LIBRE)
    botella = Camara(id=3, nombre="Cra Rivadavia 100 Bot 2 CF", estado=CamaraEstado.LIBRE)
    session = _sesion_con_camaras([principal_a, principal_b, botella])

    grupos = detectar_grupos_duplicados(session)

    assert len(grupos) == 1
    ids = {m.id for m in grupos[0].miembros}
    assert ids == {1, 2}
    assert 3 not in ids


def test_detectar_grupos_duplicados_omite_grupos_de_un_solo_miembro() -> None:
    unica = Camara(id=1, nombre="Cra Sin Duplicados 500 CF", estado=CamaraEstado.LIBRE)
    session = _sesion_con_camaras([unica])

    grupos = detectar_grupos_duplicados(session)

    assert grupos == []


def test_detectar_grupos_duplicados_marca_conflicto_y_estado_mas_restrictivo() -> None:
    a = Camara(id=1, nombre="Cámara Eduardo Madero 1180", estado=CamaraEstado.LIBRE)
    b = Camara(id=2, nombre="Cra Eduardo Madero 1180", estado=CamaraEstado.BANEADA)
    session = _sesion_con_camaras([a, b])

    grupos = detectar_grupos_duplicados(session)

    assert len(grupos) == 1
    assert grupos[0].estados_en_conflicto is True
    assert grupos[0].estado_mas_restrictivo == "BANEADA"


def test_detectar_grupos_duplicados_sin_conflicto_de_estado() -> None:
    a = Camara(id=1, nombre="Cámara Eduardo Madero 1180", estado=CamaraEstado.LIBRE)
    b = Camara(id=2, nombre="Cra Eduardo Madero 1180", estado=CamaraEstado.LIBRE)
    session = _sesion_con_camaras([a, b])

    grupos = detectar_grupos_duplicados(session)

    assert len(grupos) == 1
    assert grupos[0].estados_en_conflicto is False
    assert grupos[0].estado_mas_restrictivo == "LIBRE"


def test_detectar_grupos_duplicados_cuenta_botellas_cromo_de_camara_inferida() -> None:
    """~9.770/10.212 Cámaras raíz son INFERIDO_CROMO y nunca tienen Botellas legado propias —
    botellas_count debía incluir también cromo_botellas."""
    a = Camara(id=1, nombre="Cámara 14 de Julio 240", estado=CamaraEstado.LIBRE)
    a.cromo_botellas = [CromoBotella(n_id=1), CromoBotella(n_id=2)]
    b = Camara(id=2, nombre="Cra 14 de Julio 240 CF", estado=CamaraEstado.LIBRE)
    session = _sesion_con_camaras([a, b])

    grupos = detectar_grupos_duplicados(session)

    item_a = next(m for m in grupos[0].miembros if m.id == 1)
    assert item_a.botellas_count == 2


def _grupo(miembros: list[CamaraDuplicadaItem]) -> GrupoDuplicados:
    return GrupoDuplicados(
        clave_normalizada="clave",
        criterio="normalizacion_extendida",
        miembros=miembros,
        estados_en_conflicto=False,
        estado_mas_restrictivo="LIBRE",
    )


def test_sugerir_principal_elige_mas_botellas_y_cables() -> None:
    grupo = _grupo([
        CamaraDuplicadaItem(id=1, nombre="A", estado="LIBRE", botellas_count=0, cables_count=0),
        CamaraDuplicadaItem(id=2, nombre="B", estado="LIBRE", botellas_count=3, cables_count=1),
    ])
    assert sugerir_principal(grupo) == 2


def test_sugerir_principal_empate_elige_id_mas_bajo() -> None:
    grupo = _grupo([
        CamaraDuplicadaItem(id=5, nombre="A", estado="LIBRE", botellas_count=1, cables_count=1),
        CamaraDuplicadaItem(id=3, nombre="B", estado="LIBRE", botellas_count=1, cables_count=1),
    ])
    assert sugerir_principal(grupo) == 3
