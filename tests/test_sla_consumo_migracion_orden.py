# Nombre de archivo: test_sla_consumo_migracion_orden.py
# Ubicación de archivo: tests/test_sla_consumo_migracion_orden.py
# Descripción: La migración 20261005_02 convierte horas_netas (min→h) DESPUÉS de ampliar la columna a Numeric(12,4)

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

RUTA = Path(__file__).resolve().parents[1] / "db/alembic/versions/20261005_02_sla_consumo_historico.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("mig_20261005_02", RUTA)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _correr_upgrade(filas: int) -> list[str]:
    """Ejecuta upgrade() con ``op`` mockeado y devuelve la secuencia de llamadas relevantes."""
    mod = _cargar()
    eventos: list[str] = []
    op = MagicMock()
    op.get_bind.return_value.execute.return_value.scalar_one.return_value = filas
    op.execute.side_effect = lambda sql, *a, **k: eventos.append(f"execute:{sql}")
    op.alter_column.side_effect = lambda tabla, col, **k: eventos.append(f"alter:{col}")
    with patch.object(mod, "op", op):
        mod.upgrade()
    return eventos


def test_update_horas_netas_va_despues_del_alter_column():
    eventos = _correr_upgrade(filas=3)
    idx_alter = eventos.index("alter:horas_netas")
    idx_update = next(i for i, e in enumerate(eventos) if "horas_netas / 60.0" in e)
    assert idx_update > idx_alter


def test_tabla_vacia_no_ejecuta_conversion():
    eventos = _correr_upgrade(filas=0)
    assert not any("/ 60.0" in e for e in eventos)
    assert "alter:horas_netas" in eventos
