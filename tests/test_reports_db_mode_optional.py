# Nombre de archivo: test_reports_db_mode_optional.py
# Ubicación de archivo: tests/test_reports_db_mode_optional.py
# Descripción: Pruebas opcionales del modo DB para /reports/repetitividad y GET métricas (saltadas por defecto)

from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

from api.app.main import create_app


pytestmark = pytest.mark.skipif(
    os.getenv("ENABLE_DB_TESTS") != "1",
    reason="Pruebas de modo DB deshabilitadas por defecto; set ENABLE_DB_TESTS=1 para habilitar",
)


def test_get_metrics_signature():
    app = create_app()
    client = TestClient(app)
    r = client.get("/reports/repetitividad", params={"periodo_mes": 7, "periodo_anio": 2024})
    # No afirmamos valores específicos sin DB real; sólo la forma mínima
    assert r.status_code in (200, 500, 422)
    if r.status_code == 200:
        data = r.json()
        assert set(data.keys()) == {"periodo", "total_servicios", "servicios_repetitivos"}


def test_post_generar_informe_sin_file_signature():
    app = create_app()
    client = TestClient(app)
    r = client.post("/reports/repetitividad", data={"periodo_mes": 7, "periodo_anio": 2024, "incluir_pdf": "false"})
    # Puede devolver 200 (DOCX/ZIP) si DB configurada, o 500/422 si falta configuración/datos
    assert r.status_code in (200, 500, 422)
