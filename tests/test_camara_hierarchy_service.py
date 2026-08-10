# Nombre de archivo: test_camara_hierarchy_service.py
# Ubicación de archivo: tests/test_camara_hierarchy_service.py
# Descripción: Pruebas de la jerarquía Cámara/Botella — detección de sufijo "Bot N" y resolución/creación de la cámara padre

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.services.camara_hierarchy_service import (
    estado_mas_restrictivo,
    extraer_base,
    normalizar_para_agrupar,
    resolver_o_crear_padre,
)
from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos


@pytest.mark.parametrize(
    "nombre,base_esperada",
    [
        ("Cra 14 de Julio 240 Bot 2 CF", "Cra 14 de Julio 240 CF"),
        ("Cra Cerrito 208 Bot 2 CF", "Cra Cerrito 208 CF"),
        # Sin espacio tras el número ("Bot 3CF") — el lookahead (no un \b de cierre) permite que la
        # letra "C" siga inmediatamente al dígito.
        ("Cra Av Triunvirato 3174 Bot 3CF", "Cra Av Triunvirato 3174 CF"),
        # Sin espacio ANTES del número ("Bot2").
        ("Cra 25 de Mayo 201 Bot2 C.F.", "Cra 25 de Mayo 201 C.F."),
        # "Bot N" al inicio del string — la seguridad viene de la clase de un solo dígito, no de la
        # posición.
        ("Bot 2 Tunel Calle 1 N 2670", "Tunel Calle 1 N 2670"),
        # Minúscula — la regex es case-insensitive.
        ("bot 2 calle principal 100", "calle principal 100"),
    ],
)
def test_extraer_base_casos_reales(nombre: str, base_esperada: str) -> None:
    assert extraer_base(nombre) == base_esperada


@pytest.mark.parametrize(
    "nombre",
    [
        # Hallazgo real: "30" no es un índice de botella, es parte del nombre de la calle "30 de
        # Septiembre" — la clase de un solo dígito [1-9] evita este falso positivo a propósito.
        "Bot 30 de Septiembre y J.M.Estrada (Adrogue)",
        "Cra Concepcion Arenal 3602 CF",
        None,
        "",
    ],
)
def test_extraer_base_no_matchea_casos_ambiguos_o_ausentes(nombre) -> None:
    assert extraer_base(nombre) is None


def test_normalizar_para_agrupar_ignora_acentos_mayusculas_y_puntuacion() -> None:
    a = normalizar_para_agrupar("Cra. 14 de Julio 240, CF")
    b = normalizar_para_agrupar("cra 14 de julio 240 cf")
    assert a == b


def test_estado_mas_restrictivo_prioriza_baneada() -> None:
    resultado = estado_mas_restrictivo([CamaraEstado.LIBRE, CamaraEstado.BANEADA, CamaraEstado.OCUPADA])
    assert resultado == CamaraEstado.BANEADA


def test_estado_mas_restrictivo_ocupada_sobre_libre() -> None:
    resultado = estado_mas_restrictivo([CamaraEstado.LIBRE, CamaraEstado.OCUPADA])
    assert resultado == CamaraEstado.OCUPADA


def test_estado_mas_restrictivo_lista_vacia_da_libre() -> None:
    assert estado_mas_restrictivo([]) == CamaraEstado.LIBRE


def test_estado_mas_restrictivo_ignora_pendiente_revision() -> None:
    """Bug real encontrado corriendo el backfill contra datos reales: PENDIENTE_REVISION no es un
    nivel de severidad física — no debe "ganarle" a LIBRE ni a ningún otro estado del grupo."""
    resultado = estado_mas_restrictivo([CamaraEstado.LIBRE, CamaraEstado.PENDIENTE_REVISION])
    assert resultado == CamaraEstado.LIBRE


def test_estado_mas_restrictivo_solo_pendiente_revision_da_libre() -> None:
    resultado = estado_mas_restrictivo([CamaraEstado.PENDIENTE_REVISION, CamaraEstado.PENDIENTE_REVISION])
    assert resultado == CamaraEstado.LIBRE


def test_resolver_o_crear_padre_nombre_sin_sufijo_no_toca_la_db() -> None:
    session = MagicMock()

    resultado = resolver_o_crear_padre(session, "Cra Piedras 401 CF", usuario="test")

    assert resultado is None
    session.execute.assert_not_called()
    session.add.assert_not_called()


def test_resolver_o_crear_padre_reusa_padre_ya_establecido() -> None:
    """Un padre "ya establecido" es una fila raíz que YA tiene al menos una botella — sólo esas se
    reusan, para no promover por casualidad de nombre una fila que todavía no es un padre real."""
    session = MagicMock()
    padre_existente = Camara(id=99, nombre="Cra 14 de Julio 240 CF", camara_padre_id=None)
    padre_existente.botellas = [Camara(id=50, nombre="Cra 14 de Julio 240 Bot 5 CF")]
    session.query.return_value.filter.return_value.all.return_value = [padre_existente]

    resultado = resolver_o_crear_padre(session, "Cra 14 de Julio 240 Bot 2 CF", usuario="test")

    assert resultado is padre_existente
    session.add.assert_not_called()
    # Sí debe tomar el advisory lock antes de decidir — protege contra altas concurrentes.
    session.execute.assert_called_once()


def test_resolver_o_crear_padre_no_promueve_una_fila_pelada_sin_botellas_a_padre() -> None:
    """Hallazgo real: si sólo existe la fila "pelada" (sin sufijo, sin botellas todavía) con el mismo
    nombre base, NO se la promueve a padre — se crea una fila nueva y la pelada queda absorbida como
    botella más (mismo criterio que el backfill)."""
    session = MagicMock()
    pelada = Camara(id=5, nombre="Cra 14 de Julio 240 CF", camara_padre_id=None)
    session.query.return_value.filter.return_value.all.return_value = [pelada]

    resultado = resolver_o_crear_padre(session, "Cra 14 de Julio 240 Bot 2 CF", usuario="test")

    assert resultado is not pelada
    assert resultado.nombre == "Cra 14 de Julio 240 CF"
    assert resultado.origen_datos == CamaraOrigenDatos.INFERIDO
    # La fila pelada queda absorbida como botella del padre nuevo, no promovida a padre.
    assert pelada.camara_padre_id == resultado.id


def test_resolver_o_crear_padre_ignora_una_camara_con_nombre_distinto() -> None:
    session = MagicMock()
    otra_camara = Camara(id=5, nombre="Cra Otra Dirección 999 CF", camara_padre_id=None)
    session.query.return_value.filter.return_value.all.return_value = [otra_camara]

    resultado = resolver_o_crear_padre(session, "Cra 14 de Julio 240 Bot 2 CF", usuario="test")

    assert resultado is not otra_camara
    assert resultado.nombre == "Cra 14 de Julio 240 CF"
    assert otra_camara.camara_padre_id is None  # no se toca, el nombre no coincide
    session.add.assert_called_once_with(resultado)


def test_resolver_o_crear_padre_crea_uno_nuevo_si_no_existe() -> None:
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []

    resultado = resolver_o_crear_padre(session, "Cra 14 de Julio 240 Bot 2 CF", usuario="test")

    assert resultado is not None
    assert resultado.nombre == "Cra 14 de Julio 240 CF"
    assert resultado.estado == CamaraEstado.LIBRE
    assert resultado.origen_datos == CamaraOrigenDatos.INFERIDO
    session.add.assert_called_once_with(resultado)
    session.flush.assert_called()
