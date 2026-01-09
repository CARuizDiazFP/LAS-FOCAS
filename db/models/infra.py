# Nombre de archivo: infra.py
# Ubicación de archivo: db/models/infra.py
# Descripción: Modelos SQLAlchemy para infraestructura (cámaras, cables, empalmes, servicios, rutas e ingresos)

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import (
    Boolean,
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

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


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


class RutaTipo(str, Enum):
    """Tipo de ruta de un servicio de fibra óptica."""

    PRINCIPAL = "PRINCIPAL"
    BACKUP = "BACKUP"
    ALTERNATIVA = "ALTERNATIVA"


# =============================================================================
# TABLAS ASOCIATIVAS (Many-to-Many)
# =============================================================================

# DEPRECATED: Esta tabla se mantiene por retrocompatibilidad durante la migración.
# Las nuevas implementaciones deben usar ruta_empalme_association.
servicio_empalme_association = Table(
    "servicio_empalme_association",
    Base.metadata,
    Column("servicio_id", Integer, ForeignKey("app.servicios.id"), primary_key=True),
    Column("empalme_id", Integer, ForeignKey("app.empalmes.id"), primary_key=True),
    schema="app",
)

# Nueva tabla asociativa: RutaServicio <-> Empalme
ruta_empalme_association = Table(
    "ruta_empalme_association",
    Base.metadata,
    Column("ruta_id", Integer, ForeignKey("app.rutas_servicio.id", ondelete="CASCADE"), primary_key=True),
    Column("empalme_id", Integer, ForeignKey("app.empalmes.id", ondelete="CASCADE"), primary_key=True),
    Column("orden", Integer, nullable=True),  # Orden del empalme en la ruta (1, 2, 3...)
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
    
    # DEPRECATED: Relación directa servicio<->empalme (mantener por retrocompatibilidad)
    servicios = relationship(
        "Servicio",
        secondary=servicio_empalme_association,
        back_populates="empalmes",
    )
    
    # Nueva relación: empalme pertenece a rutas
    rutas = relationship(
        "RutaServicio",
        secondary=ruta_empalme_association,
        back_populates="empalmes",
    )

    def __repr__(self) -> str:
        return f"<Empalme id={self.id} tracking_id='{self.tracking_empalme_id}'>"


class RutaServicio(Base):
    """Ruta de un servicio de fibra óptica (camino principal, backup, alternativo).
    
    Cada servicio puede tener múltiples rutas (similar a branches en Git).
    Una ruta es una secuencia ordenada de empalmes que representa un camino físico.
    
    Attributes:
        nombre: Nombre descriptivo de la ruta (ej: "Principal", "Backup Panamericana")
        tipo: Tipo de ruta (PRINCIPAL, BACKUP, ALTERNATIVA)
        hash_contenido: Hash SHA256 del contenido del tracking para comparaciones rápidas
        activa: Si la ruta está activa o fue deprecada
    """

    __tablename__ = "rutas_servicio"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    servicio_id = Column(Integer, ForeignKey("app.servicios.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = Column(String(255), nullable=False, default="Principal")
    tipo = Column(
        SQLEnum(RutaTipo, name="ruta_tipo", create_type=False),
        nullable=False,
        default=RutaTipo.PRINCIPAL,
    )
    hash_contenido = Column(String(64), nullable=True, index=True)  # SHA256
    nombre_archivo_origen = Column(String(255), nullable=True)
    contenido_original = Column(Text, nullable=True)  # Contenido raw del tracking para debugging
    activa = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    # Relaciones
    servicio = relationship("Servicio", back_populates="rutas")
    empalmes = relationship(
        "Empalme",
        secondary=ruta_empalme_association,
        back_populates="rutas",
        order_by=ruta_empalme_association.c.orden,
    )

    def __repr__(self) -> str:
        return f"<RutaServicio id={self.id} servicio_id={self.servicio_id} nombre='{self.nombre}' tipo={self.tipo.value}>"

    @property
    def empalmes_ordenados(self) -> List["Empalme"]:
        """Retorna los empalmes en orden de aparición en la ruta."""
        return list(self.empalmes)


class Servicio(Base):
    """Servicio de fibra óptica que pasa por múltiples empalmes/cámaras.
    
    Un servicio es una entidad lógica (cliente, ID, categoría) que puede tener
    múltiples rutas físicas (caminos de fibra).
    """

    __tablename__ = "servicios"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    servicio_id = Column(String(64), nullable=False, unique=True, index=True)
    cliente = Column(String(255), nullable=True)
    categoria = Column(Integer, nullable=True)
    nombre_archivo_origen = Column(String(255), nullable=True)  # DEPRECATED: Mover a RutaServicio
    raw_tracking_data = Column(JSON, nullable=True)  # DEPRECATED: Mover a RutaServicio

    # Nueva relación: un servicio tiene múltiples rutas
    rutas = relationship(
        "RutaServicio",
        back_populates="servicio",
        cascade="all, delete-orphan",
        order_by="RutaServicio.created_at",
    )

    # DEPRECATED: Relación directa servicio<->empalme (mantener por retrocompatibilidad)
    empalmes = relationship(
        "Empalme",
        secondary=servicio_empalme_association,
        back_populates="servicios",
    )

    def __repr__(self) -> str:
        return f"<Servicio id={self.id} servicio_id='{self.servicio_id}'>"

    @property
    def ruta_principal(self) -> Optional["RutaServicio"]:
        """Retorna la ruta principal activa del servicio (o la primera ruta)."""
        for ruta in self.rutas:
            if ruta.activa and ruta.tipo == RutaTipo.PRINCIPAL:
                return ruta
        # Fallback: primera ruta activa
        for ruta in self.rutas:
            if ruta.activa:
                return ruta
        return None

    @property
    def rutas_activas(self) -> List["RutaServicio"]:
        """Retorna todas las rutas activas del servicio."""
        return [r for r in self.rutas if r.activa]

    @property
    def todos_los_empalmes(self) -> List["Empalme"]:
        """Retorna todos los empalmes de todas las rutas activas (sin duplicados).
        
        Útil para retrocompatibilidad con código que usaba servicio.empalmes directamente.
        """
        empalmes_set = {}
        for ruta in self.rutas_activas:
            for empalme in ruta.empalmes:
                if empalme.id not in empalmes_set:
                    empalmes_set[empalme.id] = empalme
        return list(empalmes_set.values())


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
