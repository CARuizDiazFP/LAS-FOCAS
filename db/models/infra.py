# Nombre de archivo: infra.py
# Ubicación de archivo: db/models/infra.py
# Descripción: Modelos SQLAlchemy para infraestructura (cámaras, cables, empalmes, servicios e ingresos)

from __future__ import annotations

from enum import Enum
from sqlalchemy import (
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Table,
)
from sqlalchemy.orm import relationship

from db.base import Base


class CamaraEstado(str, Enum):
    LIBRE = "LIBRE"
    OCUPADA = "OCUPADA"
    BANEADA = "BANEADA"


servicio_empalme_association = Table(
    "servicio_empalme_association",
    Base.metadata,
    Column("servicio_id", Integer, ForeignKey("app.servicios.id"), primary_key=True),
    Column("empalme_id", Integer, ForeignKey("app.empalmes.id"), primary_key=True),
    schema="app",
)


class Camara(Base):
    __tablename__ = "camaras"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    fontine_id = Column(String(64), nullable=False, unique=True, index=True)
    nombre = Column(String(128), nullable=True)
    latitud = Column(Float, nullable=True)
    longitud = Column(Float, nullable=True)
    direccion = Column(String(255), nullable=True)
    estado = Column(SQLEnum(CamaraEstado, name="camara_estado"), nullable=False, default=CamaraEstado.LIBRE)
    last_update = Column(DateTime(timezone=True), nullable=True)

    empalmes = relationship("Empalme", back_populates="camara", cascade="all, delete-orphan")
    cables_origen = relationship("Cable", back_populates="origen_camara", foreign_keys="Cable.origen_camara_id")
    cables_destino = relationship("Cable", back_populates="destino_camara", foreign_keys="Cable.destino_camara_id")
    ingresos = relationship("Ingreso", back_populates="camara", cascade="all, delete-orphan")


class Cable(Base):
    __tablename__ = "cables"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    nombre = Column(String(128), nullable=True)
    origen_camara_id = Column(Integer, ForeignKey("app.camaras.id", ondelete="SET NULL"), nullable=True)
    destino_camara_id = Column(Integer, ForeignKey("app.camaras.id", ondelete="SET NULL"), nullable=True)

    origen_camara = relationship("Camara", back_populates="cables_origen", foreign_keys=[origen_camara_id])
    destino_camara = relationship("Camara", back_populates="cables_destino", foreign_keys=[destino_camara_id])


class Empalme(Base):
    __tablename__ = "empalmes"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    tracking_empalme_id = Column(String(64), nullable=False, unique=True, index=True)
    camara_id = Column(Integer, ForeignKey("app.camaras.id"), nullable=True, index=True)
    tipo = Column(String(64), nullable=True)

    camara = relationship("Camara", back_populates="empalmes")
    servicios = relationship(
        "Servicio",
        secondary="app.servicio_empalme_association",
        back_populates="empalmes",
    )


class Servicio(Base):
    __tablename__ = "servicios"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    cliente = Column(String(255), nullable=True)
    categoria = Column(Integer, nullable=True)
    raw_tracking_data = Column(JSON, nullable=True)

    empalmes = relationship(
        "Empalme",
        secondary="app.servicio_empalme_association",
        back_populates="servicios",
    )


class Ingreso(Base):
    __tablename__ = "ingresos"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    camara_id = Column(Integer, ForeignKey("app.camaras.id"), nullable=False, index=True)
    tecnico_id = Column(String(128), nullable=True)
    fecha_inicio = Column(DateTime(timezone=True), nullable=True)
    fecha_fin = Column(DateTime(timezone=True), nullable=True)

    camara = relationship("Camara", back_populates="ingresos")
