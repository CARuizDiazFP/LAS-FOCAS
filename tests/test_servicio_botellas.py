# Nombre de archivo: test_servicio_botellas.py
# Ubicación de archivo: tests/test_servicio_botellas.py
# Descripción: Tests unitarios de core/services/servicio_botellas.py: parseo de trazas, deduplicación y precedencia de capas

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from core.services import servicio_botellas as sb

# Extracto con la gramática real de `camino_optico_txt.renderizar_tracking_txt` (servicio 120393 en
# dev): la ODF y el rack de nodo salen con el mismo `Empalme <id>:` que las botellas.
TRAZA = """# Tracking óptico GENERADO desde Cromo por LAS-FOCAS — no es una medición de campo.
Cable: CABLE X
Empalme 6646700: Nodo Atento - Rack 1 FO
Empalme 6639467: Bot 1 Velez Sarfield 2551 MARTINEZ
  Tramo 1 -> 2  120 m
Empalme 6637919: Cra Velez Sarfield 2402 y Panama MARTINEZ
Empalme 6639467: Bot 1 Velez Sarfield 2551 MARTINEZ
Empalme 6645370: ODF La Paz 1282 Rack 4 -  MARTINEZ
# Elemento 123 del camino no vino resuelto en la respuesta de Cromo.
"""


def test_ids_empalme_en_orden_conserva_orden_y_deduplica() -> None:
    assert sb.ids_empalme_en_orden([TRAZA]) == [6646700, 6639467, 6637919, 6645370]


def test_ids_empalme_varias_trazas_concatena_sin_repetir() -> None:
    otra = "Empalme 6637919: X\nEmpalme 7000001: Nueva\n"
    assert sb.ids_empalme_en_orden([TRAZA, otra]) == [6646700, 6639467, 6637919, 6645370, 7000001]


def test_ids_empalme_ignora_lineas_que_no_son_empalme() -> None:
    assert sb.ids_empalme_en_orden(["Empalmes totales: 3\n# Empalme 1: comentario\nEmpalme abc: x"]) == []


def test_deduplicar_descarta_nulos_vacios_y_repetidos() -> None:
    assert sb.deduplicar(["B", None, "", "  ", "A", "B", " A "]) == ["B", "A"]


class _SesionNombres:
    """Devuelve sólo los ids que están en `cromo_botellas` (ni la ODF ni el rack)."""

    def __init__(self, filas_cache, botellas: dict[int, str]) -> None:
        self._filas_cache = filas_cache
        self._botellas = botellas

    async def execute(self, stmt, params):
        clase = self

        class _R:
            def all(self_inner):
                if "ids" in params:
                    return [(i, clase._botellas[i]) for i in params["ids"] if i in clase._botellas]
                return clase._filas_cache

        return _R()


def test_traza_cromo_filtra_odf_y_racks_y_usa_nombre_de_cromo_botellas() -> None:
    from datetime import datetime, timezone

    ahora = datetime.now(timezone.utc)
    sesion = _SesionNombres(
        [(1, TRAZA, ahora)],
        {6639467: "Bot 1 Velez Sarfield 2551 MARTINEZ", 6637919: "Cra Velez Sarfield 2402 (nombre Cromo)"},
    )

    nombres = asyncio.run(sb._botellas_traza_cromo(sesion, 737, ahora=ahora))

    assert nombres == ["Bot 1 Velez Sarfield 2551 MARTINEZ", "Cra Velez Sarfield 2402 (nombre Cromo)"]


def test_traza_cromo_ignora_entradas_vencidas() -> None:
    from datetime import datetime, timedelta, timezone

    ahora = datetime.now(timezone.utc)
    sesion = _SesionNombres([(1, TRAZA, ahora - timedelta(days=3))], {6639467: "Bot 1"})

    assert asyncio.run(sb._botellas_traza_cromo(sesion, 737, ahora=ahora)) == []


def _capas(traza, legada, inventario):
    return (
        patch.object(sb, "_botellas_traza_cromo", AsyncMock(return_value=traza)),
        patch.object(sb, "_botellas_ruta_legada", AsyncMock(return_value=legada)),
        patch.object(sb, "_botellas_inventario", AsyncMock(return_value=inventario)),
    )


@pytest.mark.parametrize(
    "traza,legada,inventario,esperado,fuente,consulta_legada",
    [
        (["T1", "T2"], ["L1"], ["A", "T1"], ["T1", "T2", "A"], "traza_cromo", False),
        ([], ["L2", "L1"], ["A", "L1"], ["L2", "L1", "A"], "traza_legada", True),
        ([], [], ["A", "B"], ["A", "B"], "inventario", True),
        ([], [], [], [], "sin_datos", True),
    ],
    ids=["traza_gana", "legada_si_no_hay_traza", "solo_inventario", "sin_datos"],
)
def test_precedencia_de_capas(traza, legada, inventario, esperado, fuente, consulta_legada) -> None:
    p1, p2, p3 = _capas(traza, legada, inventario)
    with p1, p2 as m_legada, p3:
        resultado = asyncio.run(sb.botellas_de_servicio(object(), 737))

    assert resultado.nombres == esperado
    assert resultado.orden_fuente == fuente
    assert m_legada.await_count == (1 if consulta_legada else 0)


def test_resolver_identificador_vacio_no_consulta() -> None:
    sesion = AsyncMock()
    assert asyncio.run(sb.resolver_servicio_por_identificador(sesion, "   ")) is None
    sesion.execute.assert_not_awaited()
