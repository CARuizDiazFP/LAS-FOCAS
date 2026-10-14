# Nombre de archivo: reclamo.py
# Ubicación de archivo: db/models/reclamo.py
# Descripción: Modelo SQLAlchemy para reclamos (ingesta híbrida Excel→DB)

from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, func

from db.base import Base


class Reclamo(Base):
    __tablename__ = "reclamos"
    __table_args__ = {"schema": "app"}

    numero_reclamo = Column(String(64), primary_key=True)
    numero_evento = Column(String(64), nullable=True, index=True)
    numero_linea = Column(String(64), nullable=False, index=True)
    numero_primer_servicio = Column(String(64), nullable=True, index=True)
    tipo_servicio = Column(String(80), nullable=True, index=True)
    nombre_cliente = Column(String(128), nullable=False, index=True)
    tipo_solucion = Column(String(160), nullable=True)
    codigo_cierre = Column(Integer, nullable=True)
    grupo_cierre = Column(String(40), nullable=True, index=True)
    fecha_inicio = Column(DateTime(timezone=True), nullable=True, index=True)
    fecha_cierre = Column(DateTime(timezone=True), nullable=True, index=True)
    # Horas decimales (no minutos). Base del SLA: Horas Netas Problema Reclamo.
    horas_netas = Column(Numeric(12, 4), nullable=True)
    horas_totales_problema = Column(Numeric(12, 4), nullable=True)
    horas_indisponibilidad_problema = Column(Numeric(12, 4), nullable=True)
    horas_netas_escalamiento_carrier = Column(Numeric(12, 4), nullable=True)
    carrier = Column(String(128), nullable=True)
    numero_reclamo_carrier = Column(String(128), nullable=True)
    sector_responsable = Column(String(80), nullable=True)
    descripcion_problema = Column(Text, nullable=True)
    descripcion_solucion = Column(Text, nullable=True)
    latitud = Column(Numeric(9, 6), nullable=True)
    longitud = Column(Numeric(9, 6), nullable=True)
    ingesta_id = Column(BigInteger, ForeignKey("app.sla_ingestas.id", ondelete="SET NULL"), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=True, server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=True, server_default=func.now())
