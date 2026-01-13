# Nombre de archivo: infra.py
# Ubicación de archivo: db/models/infra.py
# Descripción: Modelos SQLAlchemy para infraestructura (cámaras, cables, empalmes, servicios, rutas, puntos terminales e ingresos)

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
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
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


class PuntoTerminalTipo(str, Enum):
    """Tipo de punto terminal (extremo de la ruta)."""

    A = "A"  # Origen/Punta A
    B = "B"  # Destino/Punta B


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
    es_transito = Column(Boolean, nullable=False, default=False)  # True si es punto de tránsito (ODF/NODO/RACK)

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
    cantidad_pelos = Column(Integer, nullable=True)  # Cantidad de pelos/hilos de la ruta (extraído del tracking)
    hash_contenido = Column(String(64), nullable=True, index=True)  # SHA256
    nombre_archivo_origen = Column(String(255), nullable=True)
    contenido_original = Column(Text, nullable=True)  # JSON parseado del tracking
    raw_file_content = Column(Text, nullable=True)  # Contenido EXACTO del archivo .txt original
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
    puntos_terminales = relationship(
        "PuntoTerminal",
        back_populates="ruta",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<RutaServicio id={self.id} servicio_id={self.servicio_id} nombre='{self.nombre}' tipo={self.tipo.value}>"

    @property
    def empalmes_ordenados(self) -> List["Empalme"]:
        """Retorna los empalmes en orden de aparición en la ruta."""
        return list(self.empalmes)

    @property
    def punta_a(self) -> Optional["PuntoTerminal"]:
        """Retorna el punto terminal A (origen) de la ruta."""
        for pt in self.puntos_terminales:
            if pt.tipo == PuntoTerminalTipo.A:
                return pt
        return None

    @property
    def punta_b(self) -> Optional["PuntoTerminal"]:
        """Retorna el punto terminal B (destino) de la ruta."""
        for pt in self.puntos_terminales:
            if pt.tipo == PuntoTerminalTipo.B:
                return pt
        return None


class PuntoTerminal(Base):
    """Punto terminal de una ruta de fibra óptica (extremos A y B).
    
    Representa los puntos físicos donde inicia y termina una ruta de fibra,
    típicamente un ODF (Optical Distribution Frame), NODO, o RACK.
    
    Attributes:
        tipo: A (origen) o B (destino)
        sitio_descripcion: Descripción del sitio (ej: "ODF MAIPU 316 1")
        identificador_fisico: Rack/posición física (ej: "RACK 1 BANDEJA 2")
        pelo_conector: Par pelo-conector (ej: "P09-C10")
    """

    __tablename__ = "puntos_terminales"
    __table_args__ = (
        UniqueConstraint("ruta_id", "tipo", name="uq_punto_terminal_ruta_tipo"),
        {"schema": "app"},
    )

    id = Column(Integer, primary_key=True)
    ruta_id = Column(Integer, ForeignKey("app.rutas_servicio.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo = Column(
        SQLEnum(PuntoTerminalTipo, name="punto_terminal_tipo", create_type=False),
        nullable=False,
    )
    sitio_descripcion = Column(String(255), nullable=True)  # ODF MAIPU 316 1
    identificador_fisico = Column(String(255), nullable=True)  # RACK 1 BANDEJA 2
    pelo_conector = Column(String(64), nullable=True)  # P09-C10

    # Relación
    ruta = relationship("RutaServicio", back_populates="puntos_terminales")

    def __repr__(self) -> str:
        return f"<PuntoTerminal id={self.id} ruta_id={self.ruta_id} tipo={self.tipo.value} sitio='{self.sitio_descripcion}'>"


class Servicio(Base):
    """Servicio de fibra óptica que pasa por múltiples empalmes/cámaras.
    
    Un servicio es una entidad lógica (cliente, ID, categoría) que puede tener
    múltiples rutas físicas (caminos de fibra).
    """

    __tablename__ = "servicios"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    servicio_id = Column(String(64), nullable=False, unique=True, index=True)
    alias_ids = Column(ARRAY(String(64)), nullable=True)  # IDs alternativos del servicio (ej: O1C1, O1C2)
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


class IncidenteBaneo(Base):
    """Registro de incidente de baneo/protección de cámaras.
    
    Implementa el "Protocolo de Protección" que permite bloquear el acceso
    físico a cámaras que contienen fibra de respaldo cuando la principal
    está cortada.
    
    Soporta redundancia cruzada: el servicio afectado (cortado) puede ser
    diferente al servicio protegido (baneado).
    
    Attributes:
        ticket_asociado: ID del ticket de soporte/incidente.
        servicio_afectado_id: ID del servicio que sufrió el corte (texto).
        servicio_protegido_id: ID del servicio cuya ruta se protege (baneando cámaras).
        ruta_protegida_id: FK opcional a RutaServicio específica a proteger.
        usuario_ejecutor: Usuario que ejecutó el baneo.
        motivo: Descripción del motivo del baneo.
        fecha_inicio: Timestamp de inicio del baneo.
        fecha_fin: Timestamp de fin del baneo (cuando se levanta).
        activo: Si el baneo sigue vigente.
    """

    __tablename__ = "incidentes_baneo"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    ticket_asociado = Column(String(64), nullable=True, index=True)
    servicio_afectado_id = Column(String(64), nullable=False, index=True)  # El que se cortó
    servicio_protegido_id = Column(String(64), nullable=False, index=True)  # El que vamos a banear
    ruta_protegida_id = Column(
        Integer,
        ForeignKey("app.rutas_servicio.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    usuario_ejecutor = Column(String(128), nullable=True)
    motivo = Column(String(512), nullable=True)
    fecha_inicio = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    fecha_fin = Column(DateTime(timezone=True), nullable=True)
    activo = Column(Boolean, nullable=False, default=True, index=True)

    # Relaciones
    ruta_protegida = relationship("RutaServicio", foreign_keys=[ruta_protegida_id])

    def __repr__(self) -> str:
        status = "ACTIVO" if self.activo else "CERRADO"
        return f"<IncidenteBaneo id={self.id} ticket={self.ticket_asociado} protegido={self.servicio_protegido_id} [{status}]>"

    @property
    def duracion_horas(self) -> float | None:
        """Calcula la duración del baneo en horas."""
        if not self.fecha_inicio:
            return None
        fin = self.fecha_fin or datetime.now(timezone.utc)
        delta = fin - self.fecha_inicio
        return delta.total_seconds() / 3600
