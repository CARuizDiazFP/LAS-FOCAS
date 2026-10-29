# Nombre de archivo: soporte_cromo_tracking.py
# Ubicación de archivo: tests/soporte_cromo_tracking.py
# Descripción: Fakes, semillas y fixtures compartidos por los tests de tracking por camino de Cromo (test_cromo_tracking_*.py)

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.services.cromo import tracking_service
from core.services.cromo.tracking_service import TrackingGenerado


AHORA = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _generado(pelo: int, pelos_camino: set[int]) -> TrackingGenerado:
    return TrackingGenerado(
        pelo_n_id=pelo,
        nombre_archivo="42351 CROMO.txt",
        contenido=f"camino de {pelo}",
        desde_cache=False,
        generado_at=AHORA,
        duracion_ms=100,
        pelos_camino=frozenset(pelos_camino),
    )


def _semilla(pelo: int, *, conector: bool = False):
    from core.services.cromo.camino_optico_service import PeloSemilla

    return PeloSemilla(
        pelo_n_id=pelo,
        servicio_numero="94673",
        metodo="REGEX_EXACTO",
        confianza=100,
        numero_pelo="21",
        color="AM",
        cable_n_id=1,
        cable_nombre="F-VIN-TEC",
        tiene_conector_odf=conector,
        servicio_raw=None,
    )


def _con_resumen(tracking: TrackingGenerado, resumen) -> TrackingGenerado:
    tracking.extremos = resumen
    return tracking


@pytest.fixture(autouse=True)
def _sin_evidencia(monkeypatch):
    """Estos tests usan sesiones fake: la evidencia del árbitro (tiene sus propios tests) se anula."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "core.services.cromo.arbitro.evidencia.registrar_y_encolar", AsyncMock(return_value=None)
    )


@pytest.fixture
def declaraciones(monkeypatch):
    """Sin nada declarado por defecto: la sesión de estos tests es un `object()`, sin DB."""
    from core.services.cromo.servicio_odf_confirmacion import Declaraciones

    estado = {"valor": Declaraciones()}

    async def _leer(_sesion, _servicio_id):
        return estado["valor"]

    async def _numero(_sesion, _servicio_id):
        return estado.get("numero")

    async def _posiciones(_sesion, _servicio_id, modo):
        # Único punto de lectura de posiciones (posibles y declaradas): vacío por defecto, así los
        # tests de antes de la posición vigente corren igual con la sesión `object()`.
        estado.setdefault("modos", []).append(modo)
        if modo == "ninguna":
            return [], []
        posibles = list(estado.get("posibles", [])) if modo == "todas" else []
        return posibles, list(estado.get("declaradas", []))

    async def _matches(_sesion, servicio_id, pelos):
        # El match vigente de los pelos de los caminos de posición (`estado["matches"]`, pelo →
        # `MatchDePelo`): ninguno por defecto. Se reemplaza sólo la lectura: la moda es la real.
        estado.setdefault("consultas_otro_activo", []).append((servicio_id, sorted(pelos)))
        matches = estado.get("matches", {})
        return {p: matches[p] for p in pelos if p in matches}

    from core.services.cromo import servicio_posicion_vigente as pv

    monkeypatch.setattr(tracking_service, "declaraciones_del_servicio", _leer)
    monkeypatch.setattr(tracking_service, "numero_del_servicio", _numero)
    monkeypatch.setattr(tracking_service, "posiciones_del_servicio", _posiciones)
    monkeypatch.setattr(pv, "_matches_de_pelos", _matches)
    return estado
