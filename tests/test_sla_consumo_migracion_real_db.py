# Nombre de archivo: test_sla_consumo_migracion_real_db.py
# Ubicación de archivo: tests/test_sla_consumo_migracion_real_db.py
# Descripción: El esquema del histórico SLA consumido existe en Postgres real (tablas, columnas, vista)

from __future__ import annotations

from sqlalchemy import text

from db.session import SessionLocal
from tests.soporte_postgres_real import requiere_postgres_real

pytestmark = requiere_postgres_real


def _columnas(session, tabla: str) -> dict[str, str]:
    filas = session.execute(text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'app' AND table_name = :t"), {"t": tabla}).all()
    return {f.column_name: f.data_type for f in filas}


def test_esquema_historico_sla():
    with SessionLocal() as session:
        reclamos = _columnas(session, "reclamos")
        for col in ("horas_totales_problema", "horas_indisponibilidad_problema",
                    "horas_netas_escalamiento_carrier", "carrier", "numero_reclamo_carrier",
                    "numero_primer_servicio", "sector_responsable", "descripcion_problema",
                    "codigo_cierre", "grupo_cierre", "ingesta_id", "first_seen_at", "last_seen_at"):
            assert col in reclamos, col
        assert reclamos["horas_netas"] == "numeric"
        assert {"fecha_corte", "hash_servicios", "hash_reclamos"} <= set(_columnas(session, "sla_ingestas"))
        assert {"numero_linea", "fecha_corte", "sla_prometido", "sla_entregado"} <= set(
            _columnas(session, "servicio_sla_snapshot"))
        session.execute(text("SELECT * FROM app.v_eventos_sla LIMIT 1"))
