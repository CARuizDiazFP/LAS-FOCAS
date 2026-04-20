# Nombre de archivo: servicios.py
# Ubicación de archivo: db/models/servicios.py
# Descripción: Modelo SQLAlchemy para configuración de servicios automatizados (notificaciones, workers)

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from db.base import Base


class ConfigServicios(Base):
    """Configuración persistente de servicios automatizados.

    Cada fila representa un servicio (ej. ``slack_baneo_notifier``) con su
    intervalo de ejecución, canales destino y estado operativo.
    """

    __tablename__ = "config_servicios"
    __table_args__ = {"schema": "app"}

    id = Column(Integer, primary_key=True)
    nombre_servicio = Column(
        String(128), nullable=False, unique=True, index=True,
        comment="Identificador único del servicio (ej: slack_baneo_notifier)",
    )
    intervalo_horas = Column(
        Integer, nullable=False, default=4,
        comment="Intervalo de ejecución en horas",
    )
    slack_channels = Column(
        String(512), nullable=False, default="",
        comment="Canales Slack separados por coma",
    )
    ultima_ejecucion = Column(
        DateTime(timezone=True), nullable=True,
        comment="Timestamp de la última ejecución exitosa",
    )
    activo = Column(
        Boolean, nullable=False, default=True,
        comment="Si el servicio está habilitado",
    )
    ultimo_error = Column(
        Text, nullable=True,
        comment="Último error registrado (NULL si la última ejecución fue exitosa)",
    )
