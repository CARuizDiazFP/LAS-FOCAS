# Nombre de archivo: test_cromo_camara_padre_service.py
# Ubicación de archivo: tests/test_cromo_camara_padre_service.py
# Descripción: Pruebas de la extracción de nombre de Cámara padre (sufijo, prefijo, fallback de nombre exacto) y resolución de Cámara padre para Botellas Cromo

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.services.cromo.camara_padre_service import extraer_base_cromo, resolver_o_crear_padre_cromo
from db.models.infra import Camara, CamaraEstado, CamaraOrigenDatos


@pytest.fixture(autouse=True)
def _sin_botellas_cromo(monkeypatch):
    """Por defecto, ninguna Cámara candidata tiene Botellas Cromo propias — ver el mismo fixture y su
    razón de ser en `tests/test_camara_hierarchy_service.py` (hallazgo real, 2026-08-12)."""
    monkeypatch.setattr(
        "core.services.camara_hierarchy_service.ids_camaras_con_cromo_hijos",
        lambda session: set(),
    )


@pytest.mark.parametrize(
    "nombre,base_esperada",
    [
        # Patrón real confirmado (sufijo "Bot N") — mismo caso real documentado en docs/infra.md.
        ("Cra Plaza de los Ingleses Bot 2 CF", "Cra Plaza de los Ingleses CF"),
        # Patrón de prefijo pedido explícitamente (número después de la palabra completa "Botella").
        ("Botella 2 Combate de los pozos 1881 CF", "Combate de los pozos 1881 CF"),
        ("botella 3  Calle Con Espacios Extra", "Calle Con Espacios Extra"),
        # Punto DESPUÉS del dígito (2026-08-14, bug real vía el camino de sufijo — ids reales 7683 y
        # 6561, ver docs/decisiones.md). El punto interno legítimo ("Poste Est .") se preserva intacto.
        ("Bot 2. Cra Marcos Sastre y Colectora Este", "Cra Marcos Sastre y Colectora Este"),
        ("Bot 2. Poste Est . Bs. As. C.F", "Poste Est . Bs. As. C.F"),
        # Mismo fix aplicado también al camino de PREFIJO por consistencia — nunca confirmado en datos
        # reales para este camino específico (a diferencia del sufijo), ver docstring de
        # `RE_BOTELLA_PREFIJO`.
        ("Botella 2. Nombre De Prueba Sintetico", "Nombre De Prueba Sintetico"),
    ],
)
def test_extraer_base_cromo_combina_sufijo_y_prefijo(nombre: str, base_esperada: str | None) -> None:
    assert extraer_base_cromo(nombre) == base_esperada


def test_extraer_base_cromo_prioriza_sufijo_sobre_prefijo_si_ambos_pudieran_aplicar() -> None:
    """El sufijo real "Bot N" se intenta primero — es el único patrón confirmado en datos reales."""
    assert extraer_base_cromo("Cra Test 100 Bot 2 CF") == "Cra Test 100 CF"


@pytest.mark.parametrize("nombre", [None, "", "   "])
def test_extraer_base_cromo_no_matchea_casos_ausentes(nombre) -> None:
    """Único caso sin resolución automática: nombre vacío/`None`/sólo espacios."""
    assert extraer_base_cromo(nombre) is None


@pytest.mark.parametrize(
    "nombre,base_esperada",
    [
        # Sin sufijo "Bot N" ni prefijo "Botella N" — no es "sin información", Cromo ya la
        # trackea como sitio real. Ejemplo real del pedido de negocio (2026-08-12).
        ("Av Rivadavia 6041", "Av Rivadavia 6041"),
        ("Cra Sin Ningun Patron 100 CF", "Cra Sin Ningun Patron 100 CF"),
        ("  Av Rivadavia 6041  ", "Av Rivadavia 6041"),  # recorta espacios en los extremos
    ],
)
def test_extraer_base_cromo_fallback_nombre_exacto_sin_patron(nombre: str, base_esperada: str) -> None:
    assert extraer_base_cromo(nombre) == base_esperada


def test_resolver_o_crear_padre_cromo_nombre_vacio_no_toca_la_db() -> None:
    session = MagicMock()

    resultado = resolver_o_crear_padre_cromo(session, "   ")

    assert resultado is None
    session.add.assert_not_called()


def test_resolver_o_crear_padre_cromo_fallback_nombre_exacto_crea_padre_libre() -> None:
    """El fallback de nombre exacto crea Cámara padre igual que el camino de sufijo/prefijo —
    misma política (2026-08-13: LIBRE por defecto), ninguna señal operativa real de por medio en
    ningún caso."""
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []

    resultado = resolver_o_crear_padre_cromo(session, "Av Rivadavia 6041")

    assert resultado is not None
    assert resultado.nombre == "Av Rivadavia 6041"
    assert resultado.estado == CamaraEstado.LIBRE
    assert resultado.origen_datos == CamaraOrigenDatos.INFERIDO_CROMO


def test_resolver_o_crear_padre_cromo_crea_padre_nuevo_libre() -> None:
    """Decisión 2026-08-13: el padre nuevo nace LIBRE — una Cámara recién creada no tiene
    empalmes/rutas propios todavía, así que no puede haber un IncidenteBaneo activo real que la
    afecte en el momento del alta."""
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []

    resultado = resolver_o_crear_padre_cromo(session, "Botella 2 Combate de los pozos 1881 CF")

    assert resultado is not None
    assert resultado.nombre == "Combate de los pozos 1881 CF"
    assert resultado.estado == CamaraEstado.LIBRE
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
