# Nombre de archivo: test_cromo_camara_padre_service.py
# Ubicación de archivo: tests/test_cromo_camara_padre_service.py
# Descripción: Pruebas del regex combinado (sufijo+prefijo) y resolución de Cámara padre para Botellas Cromo

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.services.cromo.camara_padre_service import extraer_base_cromo, resolver_o_crear_padre_cromo
from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos


@pytest.mark.parametrize(
    "nombre,base_esperada",
    [
        # Patrón real confirmado (sufijo "Bot N") — mismo caso real documentado en docs/infra.md.
        ("Cra Plaza de los Ingleses CF", None),  # sin sufijo/prefijo, no matchea
        ("Cra Plaza de los Ingleses Bot 2 CF", "Cra Plaza de los Ingleses CF"),
        # Patrón de prefijo pedido explícitamente (número después de la palabra completa "Botella").
        ("Botella 2 Combate de los pozos 1881 CF", "Combate de los pozos 1881 CF"),
        ("botella 3  Calle Con Espacios Extra", "Calle Con Espacios Extra"),
    ],
)
def test_extraer_base_cromo_combina_sufijo_y_prefijo(nombre: str, base_esperada: str | None) -> None:
    assert extraer_base_cromo(nombre) == base_esperada


def test_extraer_base_cromo_prioriza_sufijo_sobre_prefijo_si_ambos_pudieran_aplicar() -> None:
    """El sufijo real "Bot N" se intenta primero — es el único patrón confirmado en datos reales."""
    assert extraer_base_cromo("Cra Test 100 Bot 2 CF") == "Cra Test 100 CF"


@pytest.mark.parametrize("nombre", [None, "", "Cra Sin Ningun Patron 100 CF"])
def test_extraer_base_cromo_no_matchea_casos_ausentes(nombre) -> None:
    assert extraer_base_cromo(nombre) is None


def test_resolver_o_crear_padre_cromo_nombre_sin_patron_no_toca_la_db() -> None:
    session = MagicMock()

    resultado = resolver_o_crear_padre_cromo(session, "Cra Sin Ningun Patron 100 CF")

    assert resultado is None
    session.add.assert_not_called()


def test_resolver_o_crear_padre_cromo_crea_padre_nuevo_no_operativa() -> None:
    """Sin señal operativa real de origen, el padre nuevo nace NO_OPERATIVA (fail-closed), nunca
    LIBRE — resuelve el riesgo de seguridad de campo ya señalado para este dominio."""
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []

    resultado = resolver_o_crear_padre_cromo(session, "Botella 2 Combate de los pozos 1881 CF")

    assert resultado is not None
    assert resultado.nombre == "Combate de los pozos 1881 CF"
    assert resultado.estado == CamaraEstado.NO_OPERATIVA
    assert resultado.origen_datos == CamaraOrigenDatos.INFERIDO_CROMO


def test_resolver_o_crear_padre_cromo_reusa_camara_legado_existente_y_hereda_su_estado_real() -> None:
    """Reutilizar una Cámara legado ya existente no es inferencia — es leer un dato real que ya
    tiene auditoría propia. El estado de la fila reusada no se toca."""
    session = MagicMock()
    padre_real = Camara(id=42, nombre="Combate de los pozos 1881 CF", estado=CamaraEstado.BANEADA, camara_padre_id=None)
    padre_real.botellas = [Camara(id=43, nombre="Combate de los pozos 1881 Bot 3 CF")]
    session.query.return_value.filter.return_value.all.return_value = [padre_real]

    resultado = resolver_o_crear_padre_cromo(session, "Botella 2 Combate de los pozos 1881 CF")

    assert resultado is padre_real
    assert resultado.estado == CamaraEstado.BANEADA
    session.add.assert_not_called()
