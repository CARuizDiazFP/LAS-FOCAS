# Nombre de archivo: test_cromo_retencion_eventos.py
# Ubicación de archivo: tests/test_cromo_retencion_eventos.py
# Descripción: Tests unitarios de la retención de eventos Cromo — cálculo del corte y argumentos del script (dry-run por defecto)

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.services.cromo import retencion_eventos
from scripts import cromo_retencion_eventos


def test_calcular_corte_resta_los_dias():
    ahora = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    assert retencion_eventos.calcular_corte(90, ahora) == datetime(2026, 7, 29, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("dias", [0, -5])
def test_calcular_corte_rechaza_dias_no_positivos(dias):
    with pytest.raises(ValueError):
        retencion_eventos.calcular_corte(dias)


def test_script_es_dry_run_por_defecto():
    args = cromo_retencion_eventos._argumentos([])
    assert args.aplicar is False
    assert args.dias == 90
    assert args.incluir_sin_cambios is False


def test_script_aplicar_y_sin_cambios_son_explicitos():
    args = cromo_retencion_eventos._argumentos(["--aplicar", "--incluir-sin-cambios", "--dias", "30"])
    assert (args.aplicar, args.incluir_sin_cambios, args.dias) == (True, True, 30)
