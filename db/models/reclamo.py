# Nombre de archivo: reclamo.py
# Ubicación de archivo: db/models/reclamo.py
# Descripción: Modelo SQLAlchemy para reclamos (ingesta híbrida Excel→DB)

from __future__ import annotations

from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, DateTime, Numeric, Text


Base = declarative_base()


class Reclamo(Base):
    __tablename__ = "reclamos"
    __table_args__ = {"schema": "app"}

    numero_reclamo = Column(String(64), primary_key=True)
    numero_evento = Column(String(64), nullable=True, index=True)
    numero_linea = Column(String(64), nullable=False, index=True)
    tipo_servicio = Column(String(80), nullable=True, index=True)
    nombre_cliente = Column(String(128), nullable=False, index=True)
    tipo_solucion = Column(String(80), nullable=True)
    fecha_inicio = Column(DateTime(timezone=True), nullable=True)
    fecha_cierre = Column(DateTime(timezone=True), nullable=True, index=True)
    horas_netas = Column(Numeric(10, 2), nullable=True)
    descripcion_solucion = Column(Text, nullable=True)
    latitud = Column(Numeric(9, 6), nullable=True)
    longitud = Column(Numeric(9, 6), nullable=True)
