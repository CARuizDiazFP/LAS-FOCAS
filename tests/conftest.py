# Nombre de archivo: conftest.py
# Ubicación de archivo: tests/conftest.py
# Descripción: Genera archivos XLSX de ejemplo para las pruebas del bot

from pathlib import Path

import pandas as pd
import pytest


def _ensure_sla_sample(path: str | Path = "tests/data/sla_sample.xlsx") -> Path:
    """Crea un archivo XLSX mínimo para pruebas de SLA."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        df = pd.DataFrame(
            [
                {
                    "ID": 1,
                    "CLIENTE": "ACME",
                    "SERVICIO": "Default",
                    "FECHA_APERTURA": "2024-06-01",
                    "FECHA_CIERRE": "2024-06-02",
                },
                {
                    "ID": 2,
                    "CLIENTE": "ACME",
                    "SERVICIO": "Default",
                    "FECHA_APERTURA": "2024-06-01",
                    "FECHA_CIERRE": "2024-06-05",
                },
            ]
        )
        df.to_excel(p, index=False)
    return p


def _ensure_repetitividad_sample(
    path: str | Path = "tests/data/repetitividad_sample.xlsx",
) -> Path:
    """Crea un archivo XLSX mínimo para pruebas de repetitividad."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        df = pd.DataFrame(
            [
                {
                    "CLIENTE": "A",
                    "SERVICIO": "S1",
                    "FECHA": "2024-06-01",
                    "ID_SERVICIO": "x1",
                },
                {
                    "CLIENTE": "A",
                    "SERVICIO": "S1",
                    "FECHA": "2024-06-15",
                    "ID_SERVICIO": "x2",
                },
                {
                    "CLIENTE": "B",
                    "SERVICIO": "S2",
                    "FECHA": "2024-06-20",
                    "ID_SERVICIO": "y1",
                },
            ]
        )
        df.to_excel(p, index=False)
    return p


@pytest.fixture()
def sla_sample_file() -> Path:
    """Devuelve la ruta del archivo de SLA generado."""
    return _ensure_sla_sample()


@pytest.fixture()
def repetitividad_sample_file() -> Path:
    """Devuelve la ruta del archivo de repetitividad generado."""
    return _ensure_repetitividad_sample()

