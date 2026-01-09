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
    Text,
)
from sqlalchemy.orm import relationship

from db.base import Base


class CamaraEstado(str, Enum):
    """Estado de una cámara de fibra óptica."""

    LIBRE = "LIBRE"
    OCUPADA = "OCUPADA"
    BANEADA = "BANEADA"
    DETECTADA = "DETECTADA"  # Cámaras creadas automáticamente desde tracking


class CamaraOrigenDatos(str, Enum):
    """Origen de los datos de una cámara."""

    MANUAL = "MANUAL"
    TRACKING = "TRACKING"
    SHEET = "SHEET"


servicio_empalme_association = Table(
    "servicio_empalme_association",
    Base.metadata,
    Column("servicio_id", Integer, ForeignKey("app.servicios.id"), primary_key=True),
    Column("empalme_id", Integer, ForeignKey("app.empalmes.id"), primary_key=True),
    schema="app",
)


class Camara(Base):
    """Cámara de fibra óptica en la red de infraestructura."""

    __tablename__ = "camaras"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    fontine_id = Column(String(64), nullable=True, unique=True, index=True)
    nombre = Column(String(255), nullable=False, index=True)
    latitud = Column(Float, nullable=True)
    longitud = Column(Float, nullable=True)
    direccion = Column(String(255), nullable=True)
    estado = Column(
        SQLEnum(CamaraEstado, name="camara_estado", create_type=False),
        nullable=False,
        default=CamaraEstado.LIBRE,
    )
    origen_datos = Column(
        SQLEnum(CamaraOrigenDatos, name="camara_origen_datos", create_type=False),
        nullable=False,
        default=CamaraOrigenDatos.MANUAL,
    )
    last_update = Column(DateTime(timezone=True), nullable=True)

    empalmes = relationship("Empalme", back_populates="camara", cascade="all, delete-orphan")
    cables_origen = relationship("Cable", back_populates="origen_camara", foreign_keys="Cable.origen_camara_id")
    cables_destino = relationship("Cable", back_populates="destino_camara", foreign_keys="Cable.destino_camara_id")
    ingresos = relationship("Ingreso", back_populates="camara", cascade="all, delete-orphan")

    @property
    def cables(self) -> list["Cable"]:
        """Retorna todos los cables asociados a esta cámara (origen + destino)."""
        return self.cables_origen + self.cables_destino

    def __repr__(self) -> str:
        return f"<Camara id={self.id} nombre='{self.nombre}' estado={self.estado.value}>"


class Cable(Base):
    """Cable de fibra óptica que conecta dos cámaras."""

    __tablename__ = "cables"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    nombre = Column(String(128), nullable=True)
    origen_camara_id = Column(Integer, ForeignKey("app.camaras.id", ondelete="SET NULL"), nullable=True)
    destino_camara_id = Column(Integer, ForeignKey("app.camaras.id", ondelete="SET NULL"), nullable=True)

    origen_camara = relationship("Camara", back_populates="cables_origen", foreign_keys=[origen_camara_id])
    destino_camara = relationship("Camara", back_populates="cables_destino", foreign_keys=[destino_camara_id])

    def __repr__(self) -> str:
        return f"<Cable id={self.id} nombre='{self.nombre}'>"


class Empalme(Base):
    """Empalme de fibra óptica ubicado en una cámara."""

    __tablename__ = "empalmes"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    tracking_empalme_id = Column(String(64), nullable=False, index=True)
    camara_id = Column(Integer, ForeignKey("app.camaras.id"), nullable=True, index=True)
    tipo = Column(String(64), nullable=True)

    camara = relationship("Camara", back_populates="empalmes")
    servicios = relationship(
        "Servicio",
        secondary="app.servicio_empalme_association",
        back_populates="empalmes",
    )

    def __repr__(self) -> str:
        return f"<Empalme id={self.id} tracking_id='{self.tracking_empalme_id}'>"


class Servicio(Base):
    """Servicio de fibra óptica que pasa por múltiples empalmes/cámaras."""

    __tablename__ = "servicios"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    servicio_id = Column(String(64), nullable=False, unique=True, index=True)
    cliente = Column(String(255), nullable=True)
    categoria = Column(Integer, nullable=True)
    nombre_archivo_origen = Column(String(255), nullable=True)
    raw_tracking_data = Column(JSON, nullable=True)

    empalmes = relationship(
        "Empalme",
        secondary="app.servicio_empalme_association",
        back_populates="servicios",
    )

    def __repr__(self) -> str:
        return f"<Servicio id={self.id} servicio_id='{self.servicio_id}'>"


class Ingreso(Base):
    """Registro de ingreso de técnico a una cámara."""

    __tablename__ = "ingresos"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    camara_id = Column(Integer, ForeignKey("app.camaras.id"), nullable=False, index=True)
    tecnico_id = Column(String(128), nullable=True)
    fecha_inicio = Column(DateTime(timezone=True), nullable=True)
    fecha_fin = Column(DateTime(timezone=True), nullable=True)

    camara = relationship("Camara", back_populates="ingresos")

    def __repr__(self) -> str:
        return f"<Ingreso id={self.id} camara_id={self.camara_id}>"
