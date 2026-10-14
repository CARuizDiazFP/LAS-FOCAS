# Nombre de archivo: sla_consumo.py
# Ubicación de archivo: db/models/sla_consumo.py
# Descripción: Ingestas del informe SLA consumido y fotos de SLA por servicio y fecha de corte

from __future__ import annotations

from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, Numeric, String, UniqueConstraint, func

from db.base import Base


class SlaIngesta(Base):
    __tablename__ = "sla_ingestas"
    __table_args__ = (UniqueConstraint("hash_servicios", "hash_reclamos", name="uq_sla_ingestas_hashes"),
                      {"schema": "app"})

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    fecha_corte = Column(Date, nullable=False, index=True)
    hash_servicios = Column(String(64), nullable=False)
    hash_reclamos = Column(String(64), nullable=False)
    usuario = Column(String(128), nullable=True)
    reclamos_insertados = Column(Integer, nullable=False, default=0)
    reclamos_actualizados = Column(Integer, nullable=False, default=0)
    servicios_snapshot = Column(Integer, nullable=False, default=0)
    report_history_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ServicioSlaSnapshot(Base):
    __tablename__ = "servicio_sla_snapshot"
    __table_args__ = (UniqueConstraint("numero_linea", "fecha_corte", name="uq_sla_snapshot_linea_corte"),
                      {"schema": "app"})

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    numero_linea = Column(String(64), nullable=False, index=True)
    numero_primer_servicio = Column(String(64), nullable=True, index=True)
    fecha_corte = Column(Date, nullable=False, index=True)
    nombre_cliente = Column(String(128), nullable=True)
    tipo_servicio = Column(String(80), nullable=True)
    sla_prometido = Column(Numeric(6, 3), nullable=True)
    sla_entregado = Column(Numeric(9, 6), nullable=True)
    horas_reclamos_mes = Column(Numeric(12, 4), nullable=True)
    horas_carriers_mes = Column(Numeric(12, 4), nullable=True)
    horas_reclamos_todos = Column(Numeric(12, 4), nullable=True)
    horas_carriers_todos = Column(Numeric(12, 4), nullable=True)
    horas_restantes = Column(Numeric(12, 4), nullable=True)
    abono_usd = Column(Numeric(14, 2), nullable=True)
    cantidad_reclamos_todos = Column(Integer, nullable=True)
    ingesta_id = Column(BigInteger, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
