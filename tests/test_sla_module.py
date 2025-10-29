# Nombre de archivo: test_sla_module.py
# Ubicación de archivo: tests/test_sla_module.py
# Descripción: Pruebas para parser, motor y servicios del módulo SLA

from __future__ import annotations

import io
from decimal import Decimal
import pandas as pd
import pytest

from core.sla import parser, engine, preview
from core.sla.config import DEFAULT_TZ
from core.services import sla as sla_service


@pytest.fixture
def sample_excel_bytes() -> bytes:
    tz = DEFAULT_TZ
    datos_reclamos = pd.DataFrame(
        [
            {
                "Número Reclamo": "100",
                "Número Línea": "SRV-1",
                "Nombre Cliente": "Cliente Uno",
                "Tipo Servicio": "Fibra",
                "Fecha Inicio Problema Reclamo": pd.Timestamp("2024-05-10 10:00:00", tz=tz),
                "Fecha Cierre Problema Reclamo": pd.Timestamp("2024-05-10 11:00:00", tz=tz),
                "Horas Netas Reclamo": "1",
                "Tipo Solución Reclamo": "Corte",
            },
            {
                "Número Reclamo": "101",
                "Número Línea": "SRV-1",
                "Nombre Cliente": "Cliente Uno",
                "Tipo Servicio": "Fibra",
                "Fecha Inicio Problema Reclamo": pd.Timestamp("2024-05-10 11:05:00", tz=tz),
                "Fecha Cierre Problema Reclamo": pd.Timestamp("2024-05-10 12:00:00", tz=tz),
                "Horas Netas Reclamo": "0:55:00",
                "Tipo Solución Reclamo": "Fibra",
            },
            {
                "Número Reclamo": "100",
                "Número Línea": "SRV-1",
                "Nombre Cliente": "Cliente Uno",
                "Tipo Servicio": "Fibra",
                "Fecha Inicio Problema Reclamo": pd.Timestamp("2024-05-10 10:00:00", tz=tz),
                "Fecha Cierre Problema Reclamo": pd.Timestamp("2024-05-10 11:10:00", tz=tz),
                "Horas Netas Reclamo": "1.2",
                "Tipo Solución Reclamo": "Corte",
            },
        ]
    )

    # Excel no admite timestamps con zona; se exportan como naive preservando la hora local
    datos_reclamos["Fecha Inicio Problema Reclamo"] = datos_reclamos["Fecha Inicio Problema Reclamo"].dt.tz_localize(None)
    datos_reclamos["Fecha Cierre Problema Reclamo"] = datos_reclamos["Fecha Cierre Problema Reclamo"].dt.tz_localize(None)

    datos_servicios = pd.DataFrame(
        [
            {
                "Número Primer Servicio": "SRV-1",
                "Tipo Servicio": "Fibra",
                "Nombre Cliente": "Cliente Uno",
                "SLA Entregado": 0.995,
                "Horas Reclamos Todos": "02:00:00",
            }
        ]
    )

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        datos_reclamos.to_excel(writer, sheet_name="Reclamos", index=False)
        datos_servicios.to_excel(writer, sheet_name="Servicios", index=False)
    buffer.seek(0)
    return buffer.read()


def test_parser_normaliza_y_deduplica(sample_excel_bytes: bytes) -> None:
    entrada = parser.cargar_fuente_excel(sample_excel_bytes)

    assert list(entrada.reclamos.columns) == [
        "ticket_id",
        "service_id",
        "cliente",
        "tipo_servicio",
        "inicio",
        "fin",
        "duracion_h",
        "causal",
        "descripcion",
        "estado",
        "criticidad",
        "sla_objetivo_h",
    ]
    # Se esperaba que el ticket duplicado quedara una sola vez
    assert len(entrada.reclamos) == 2
    # Las fechas deben tener la zona horaria configurada por defecto
    assert entrada.reclamos.loc[0, "inicio"].tzinfo == DEFAULT_TZ

    assert list(entrada.servicios.columns) == [
        "service_id",
        "cliente",
        "tipo_servicio",
        "sla_pct",
        "downtime_reportado_h",
    ]
    assert entrada.servicios.loc[0, "sla_pct"] == pytest.approx(0.995)


@pytest.fixture
def sample_computation(sample_excel_bytes: bytes) -> engine.SLAComputation:
    return sla_service.compute_from_excel(sample_excel_bytes, mes=5, anio=2024)


def test_engine_merge_intervalos_y_metricas(sample_computation: engine.SLAComputation) -> None:
    assert sample_computation.resumen.servicios == 1
    servicio = sample_computation.servicios[0]
    assert servicio.downtime_h == pytest.approx(2.0)
    assert servicio.tickets_unicos == 2
    assert servicio.incidentes_agrupados == 1
    assert servicio.intervals[0].incident_ids == ["100", "101"]
    # Disponibilidad sobre 744 horas de mayo
    assert sample_computation.resumen.disponibilidad_pct == pytest.approx(99.731, rel=1e-3)
    assert len(sample_computation.anexos) == 1


def test_preview_filters(sample_computation: engine.SLAComputation) -> None:
    vista = preview.construir_preview(sample_computation, servicio="Fibra")
    assert vista["resumen"]["downtime_total_h"] == pytest.approx(2.0)
    assert vista["servicios"][0]["service_id"] == "SRV-1"
    assert vista["servicios"][0]["downtime_hhmm"] == "02:00"


def test_service_generate_report_crea_docx(
    sample_excel_bytes: bytes,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.sla.config.REPORTS_DIR", tmp_path)
    monkeypatch.setattr("core.services.sla.REPORTS_DIR", tmp_path)

    resultado = sla_service.generate_report_from_excel(
        sample_excel_bytes,
        mes=5,
        anio=2024,
    )

    assert resultado.docx.exists()
    assert resultado.preview["resumen"]["servicios"] == 1


def test_compute_from_db_normaliza(monkeypatch: pytest.MonkeyPatch) -> None:
    tz = DEFAULT_TZ
    df = pd.DataFrame(
        [
            {
                "numero_reclamo": "DB-1",
                "numero_linea": "SRV-DB",
                "nombre_cliente": "Cliente DB",
                "tipo_servicio": "Internet Dedicado",
                "fecha_inicio": pd.Timestamp("2024-05-03 08:00:00", tz=tz),
                "fecha_cierre": pd.Timestamp("2024-05-03 10:15:00", tz=tz),
                "horas_netas": Decimal("2.25"),
                "tipo_solucion": "Reinicio",
                "descripcion_solucion": "Trabajo programado",
            },
            {
                "numero_reclamo": "DB-2",
                "numero_linea": "SRV-DB",
                "nombre_cliente": "Cliente DB",
                "tipo_servicio": "Internet Dedicado",
                "fecha_inicio": pd.Timestamp("2024-05-05 16:00:00", tz=tz),
                "fecha_cierre": pd.Timestamp("2024-05-05 17:10:00", tz=tz),
                "horas_netas": Decimal("1.1"),
                "tipo_solucion": "Incidente",
            },
        ]
    )

    monkeypatch.setattr(
        sla_service.repetitividad_service,
        "reclamos_from_db",
        lambda mes, anio: df.copy(),
    )

    computation = sla_service.compute_from_db(mes=5, anio=2024)

    assert computation.resumen.servicios == 1
    assert computation.resumen.tickets == 2
    assert computation.servicios[0].tickets_unicos == 2
    assert computation.servicios[0].downtime_h == pytest.approx(3.4167, rel=1e-3)
